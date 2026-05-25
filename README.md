# URL Shortener Microservice

Enterprise-grade URL shortener — Django + Celery + Redis + PostgreSQL.

---

## Architecture Diagram

```
                          ┌──────────────────────────────────────────────────┐
  React / Next.js         │              API Gateway (Nginx / AWS ALB)        │
  http://localhost:3000   │                  /api/v1/*  →  Main Service       │
        │                 └─────────────────────────┬────────────────────────┘
        │  CORS headers                             │
        ▼                                           ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         Main Service  :8000                                │
│                                                                            │
│  Interface Layer      │  api/views.py (CQRS — delegates to cmd/query)      │
│  Application Layer    │  shortener/commands.py  shortener/queries.py       │
│  Domain Services      │  shortener/saga.py      shortener/services.py      │
│  Infrastructure       │  shortener/tasks.py     circuit_breaker.py         │
│                                                                            │
│  Sync HTTP call ──────────────────────────────────────────────────────►   │
│                                              Preview Service :8001         │
│                                              /api/preview/?url=...         │
│                                              scrapes title/desc/favicon    │
│                                                                            │
│  Celery .delay() ──► Redis Broker ──► Celery Worker                        │
│                                           track_click_task                  │
│                                           fetch_url_preview_task            │
│                                                                            │
│  Celery Beat ──────────────────────────► clean_expired_urls  (nightly)     │
│                                          warm_popular_cache  (every 6h)    │
└───────────────────────────────────────┬───────────────────────────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │    PostgreSQL :5432  │
                              │    Redis      :6379  │
                              └────────────────────-┘
```

---

## Microservices

| Service | Port | Role |
|---|---|---|
| `web` | 8000 | Main Django API (Gunicorn) |
| `preview_service` | 8001 | URL metadata scraper (stateless) |
| `celery_worker` | — | Background task processor |
| `celery_beat` | — | Periodic task scheduler |
| `db` | 5432 | PostgreSQL primary |
| `redis` | 6379 | Cache + Celery broker |

### Service Discovery
Services find each other via Docker Compose DNS. The main service calls the preview service at `http://preview_service:8001` (the container name is the hostname). Override via `PREVIEW_SERVICE_URL` env var.

---

## Design Patterns

### CQRS (Command Query Responsibility Segregation)
All database operations are separated into:
- **Commands** (`shortener/commands.py`) — mutate state: `CreateURLCommand`, `UpdateURLCommand`, `DeleteURLCommand`
- **Queries** (`shortener/queries.py`) — read state: `get_url_by_code`, `list_user_urls`, `get_url_analytics`

Views never call ORM methods directly — they go through command or query handlers.

### Saga Pattern (URL Creation)
URL creation is a 2-step distributed transaction:
1. **Step 1 (local)**: `CreateURLCommand` saves the URL to PostgreSQL
2. **Step 2 (async)**: `fetch_url_preview_task.delay()` calls the Preview Service

**Compensation**: If Step 2 fails (Celery down, preview service unavailable), Step 1 is NOT rolled back. The URL is valid and functional without preview data. This is **Forward Recovery** — eventual consistency for a non-critical metadata field.

### Circuit Breaker (Redis-backed)
`shortener/circuit_breaker.py` — `CircuitBreaker('preview_service')`:

```
CLOSED ──(5 failures in 5min)──► OPEN ──(30s cooldown)──► HALF_OPEN
  ▲                                                            │
  └──────────────────────(probe succeeds)─────────────────────┘
```

When the circuit is OPEN, the preview fetch is skipped immediately (fail-fast) instead of waiting for timeouts. The URL is still created successfully.

### Retries with Exponential Backoff
`PreviewServiceClient` retries failed HTTP calls up to 3 times:
- Attempt 1: immediate
- Attempt 2: wait 1s
- Attempt 3: wait 2s

Only connection errors and 5xx responses are retried. 4xx responses fail immediately (not retriable).

---

## API Endpoints

### Authentication
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register/` | None | Create account, returns JWT |
| POST | `/api/v1/auth/login/` | None | Returns access + refresh tokens (5/min) |
| POST | `/api/v1/auth/refresh/` | None | Refresh access token |
| POST | `/api/v1/auth/logout/` | JWT | Blacklist refresh token |
| POST | `/api/v1/auth/social/` | None | Google OAuth2 → JWT |

### URL Operations
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/urls/` | JWT | Create short URL (triggers Saga) |
| GET | `/api/v1/urls/list/` | JWT | List your URLs (pagination, ?tag=, ?search=) |
| GET | `/api/v1/urls/{code}/` | Public | Get URL details |
| PUT | `/api/v1/urls/{code}/` | JWT + owner | Full update |
| PATCH | `/api/v1/urls/{code}/` | JWT + owner | Partial update |
| DELETE | `/api/v1/urls/{code}/` | JWT + owner | Delete URL |

### Public
| Method | Endpoint | Description |
|---|---|---|
| GET | `/{short_code}/` | 302 redirect (cache-first, async click tracking) |

### Analytics & Monitoring
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/analytics/{code}/` | JWT + Premium | Geo & time-series stats |
| GET | `/health/` | Public | DB + Redis + circuit breaker status |
| GET | `/api/docs/` | Public | Swagger UI |

### Preview Microservice
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/preview/?url=<url>` | Scrape title/description/favicon |
| GET | `/health/` | Liveness probe |

---

## CORS — Frontend Integration

CORS headers are set for all `/api/v1/` responses. A React/Next.js frontend at `http://localhost:3000` can call the API directly:

```javascript
// Login
const res = await fetch('http://localhost:8000/api/v1/auth/login/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
  body: JSON.stringify({ username, password }),
});
const { access, refresh } = await res.json();

// Create URL
const url = await fetch('http://localhost:8000/api/v1/urls/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${access}`,
  },
  body: JSON.stringify({ original_url: 'https://google.com' }),
});
```

Allowed origins are configured via `CORS_ALLOWED_ORIGINS` in `.env`.

---

## Running the Project

### Docker (recommended — runs all 6 services)

```bash
git clone <repo>
cd url_shortener
cp backend/.env.example backend/.env   # edit as needed
docker-compose up --build
```

Services start in dependency order (PostgreSQL → Redis → Preview Service → Web → Workers).

Visit:
- API: http://localhost:8000/api/docs/
- Preview Service: http://localhost:8001/health/

### Manual

```bash
pip install -r backend/requirements.txt
python backend/manage.py migrate
gunicorn -c gunicorn.conf.py config.wsgi:application &
celery -A config worker -l info &
celery -A config beat -l info &
cd preview_service && pip install -r requirements.txt && python manage.py runserver 8001
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | insecure dev key | Django secret key |
| `DATABASE_URL` | SQLite | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for cache + Celery |
| `PREVIEW_SERVICE_URL` | `http://preview_service:8001` | Preview microservice URL |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Allowed frontend origins |
| `DEBUG` | `True` | Debug mode |

### Tests

```bash
python backend/manage.py test tests shortener
```
