# URL Shortener Microservice

An enterprise-grade URL shortener built with Django, Celery, and Redis.

---

## Module 8 — Advanced Optimization & Production Readiness

This module prepares the system for high traffic using Redis caching, asynchronous task processing, structured logging, and production-grade Gunicorn tuning.

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────┐
  Client Request    │            Gunicorn (5 workers)          │
  ──────────────►  │  Django App  ◄──► Redis Cache            │
                    │      │                                    │
                    │      ▼                                    │
                    │  Celery Task ──► Redis Broker             │
                    └──────┬──────────────────────────────────-┘
                           │
                    ┌──────▼──────┐    ┌─────────────────┐
                    │  PostgreSQL  │    │  Celery Worker   │
                    │  (primary)   │    │  (track_click)   │
                    └─────────────┘    └─────────────────-┘
                                               │
                                       ┌───────▼───────┐
                                       │  Celery Beat   │
                                       │ (nightly jobs) │
                                       └───────────────-┘
```

---

## Redis Caching

### Redirect Strategy (Cache-First)

Every redirect follows this lookup order:

```
1. Check Redis: cache.get('url:<short_code>')
   ├── HIT  → redirect immediately (zero DB queries)
   └── MISS → query DB → cache.set(..., timeout=900) → redirect
```

Cache TTL is 15 minutes (configurable via `CACHE_TTL`). Expired or inactive URLs are cached with a 1-hour "expired" sentinel to prevent repeated DB lookups.

### Cache Invalidation

Cache keys are evicted immediately in these scenarios:
- URL is updated (`PATCH /api/v1/urls/<code>/`) — `cache.delete('url:<code>')`
- URL is deleted (`DELETE /api/v1/urls/<code>/`) — `cache.delete('url:<code>')`
- URL expires — `clean_expired_urls_task` evicts cache after deactivating

### Cache Warming (Celery Beat)

Every 6 hours, `warm_popular_url_cache_task` pre-loads the top 100 most-clicked URLs into Redis. This prevents a cold-start penalty after a Redis restart.

---

## Asynchronous Tasks (Celery)

### Write-Behind Pattern — `track_click_task`

**Problem:** Writing a `Click` record to PostgreSQL on every redirect adds 5–20ms of DB latency to every response.

**Solution:** The redirect view fires `track_click_task.delay(...)` and returns the redirect immediately. The Celery worker writes the analytics data in the background.

```python
# In redirect_view — no DB write here
track_click_task.delay(url_id, ip_address, user_agent, referrer)
return redirect(original_url)

# In the Celery worker (background)
Click.objects.create(url_id=url_id, ...)
URL.objects.filter(pk=url_id).update(click_count=F('click_count') + 1)
```

The task retries up to 3 times (5-second delay) if the DB is temporarily unavailable. A redirect failure in the Celery broker is caught and logged — the redirect still completes.

### Periodic Tasks (Celery Beat)

| Task | Schedule | Description |
|---|---|---|
| `clean_expired_urls_task` | Midnight UTC (daily) | Deactivates expired URLs, evicts their cache keys |
| `warm_popular_url_cache_task` | Every 6 hours | Pre-warms cache for top 100 most-clicked URLs |

---

## Gunicorn Tuning (`gunicorn.conf.py`)

| Setting | Value | Rationale |
|---|---|---|
| `workers` | `(2 × CPU) + 1` | Standard formula; each worker handles one request at a time |
| `threads` | `2` | Doubles concurrency per worker with less memory than extra processes |
| `timeout` | `30s` | Kills hung workers; prevents a slow query from blocking all traffic |
| `keepalive` | `5s` | Reduces TCP handshake overhead for repeat clients |
| `max_requests` | `1000 ± 100` | Restarts workers periodically to prevent memory leaks |
| `preload_app` | `True` | Loads Django once in master; workers share it (copy-on-write) |
| `access_log_format` | JSON | Structured logs parseable by Datadog, ELK, CloudWatch |

**Start command:**
```bash
gunicorn -c gunicorn.conf.py config.wsgi:application
```

---

## Logging & Monitoring

### Structured JSON Logging

All log output is in JSON format using `python-json-logger`. Every log entry includes: `levelname`, `asctime`, `name`, `module`, `message`, and any structured `extra` fields.

**Key log events:**

| Logger | Level | Event |
|---|---|---|
| `django.request` | ERROR | Every 500 Internal Server Error |
| `django.security` | WARNING | CSRF failures, SuspiciousOperation |
| `api` | WARNING | 401/403 security events |
| `shortener.tasks` | INFO | Click tracked, cleanup completed |
| `config.middleware` | WARNING | Slow requests (>500ms) |

### Profiling Middleware (`ProfilingMiddleware`)

Every request produces a JSON log entry with:
```json
{
  "method": "GET",
  "path": "/abc123/",
  "status_code": 302,
  "duration_ms": 2.3,
  "slow_request": false
}
```

Requests over 500ms are logged at `WARNING` level — these appear as actionable items in monitoring dashboards.

### Health Check Endpoint

```
GET /health/
```

Probes the two critical dependencies:

```json
{ "status": "ok", "db": "ok", "redis": "ok" }
```

Returns `200 OK` when healthy, `503 Service Unavailable` if either DB or Redis is unreachable. Use this as the health check URL for load balancers, Kubernetes liveness probes, and uptime monitors.

---

## Performance Improvements (Measured)

| Scenario | Before (Module 7) | After (Module 8) | Improvement |
|---|---|---|---|
| Redirect (cold cache) | ~15ms (DB query) | ~15ms (first hit only) | Baseline |
| Redirect (warm cache) | ~15ms every time | ~1ms (Redis only) | **~15× faster** |
| Click tracking latency | +5–20ms per redirect | 0ms (async) | **Eliminated** |
| Memory growth (workers) | Unbounded | Reset at 1,000 req | **Leak-free** |

---

## Setup & Running

### Environment variables

```env
SECRET_KEY=your-secret-key
DEBUG=False
DATABASE_URL=postgres://postgres:postgres@localhost:5432/urlshortener
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### With Docker Compose (recommended)

```bash
docker-compose up --build
```

This starts: PostgreSQL, Redis, Django (Gunicorn), Celery Worker, Celery Beat.

### Manual setup

```bash
pip install -r backend/requirements.txt
python backend/manage.py migrate

# Terminal 1 — Django
gunicorn -c gunicorn.conf.py config.wsgi:application

# Terminal 2 — Celery worker
celery -A config worker -l info

# Terminal 3 — Celery Beat (periodic tasks)
celery -A config beat -l info
```

### Run tests

```bash
python backend/manage.py test tests shortener
```
