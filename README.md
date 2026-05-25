# URL Shortener Microservice

An enterprise-grade URL shortener built with Django and Django REST Framework.

---

## Module 6 — ORM & Data Access Layer

This module expands the data model to support user ownership, tagging, and deep analytics. The implementation focuses on fetching data efficiently without putting strain on the database.

---

## Data Schema

```
User (core.User — extends AbstractUser)
├── is_premium  BooleanField  — quick flag for premium feature gates
└── tier        CharField     — 'free' | 'pro' | 'enterprise'

Tag (shortener.Tag)
└── name        CharField(50, unique)

URL (shortener.URL)
├── original_url   URLField
├── short_code     CharField(10, unique)  ← db_index=True (fast lookups)
├── custom_alias   CharField(50, unique, nullable)
├── owner          ForeignKey → User      (who created this link)
├── is_active      BooleanField
├── expires_at     DateTimeField (nullable)
├── click_count    PositiveIntegerField   (denormalised counter)
├── title          CharField (nullable)
├── description    CharField (nullable)
├── favicon        CharField (nullable)
├── tags           ManyToManyField → Tag  (categorisation)
├── created_at     DateTimeField          ← db_index=True (time-range queries)
└── updated_at     DateTimeField

Click (shortener.Click)
├── url         ForeignKey → URL  (every visit is logged)
├── clicked_at  DateTimeField     ← db_index=True
├── ip_address  GenericIPAddressField
├── city        CharField
├── country     CharField
├── user_agent  TextField
└── referrer    URLField
```

### Relationships
- `URL → User`: many-to-one (many URLs can belong to one user)
- `URL ↔ Tag`: many-to-many (a URL can have multiple tags; a tag can apply to many URLs)
- `Click → URL`: many-to-one (every click is tied to one URL)

---

## Migrations

| Migration | Description |
|---|---|
| `core/0004_user_premium_tier` | Adds `is_premium` and `tier` fields to the User model |
| `shortener/0002_module6_schema` | Creates Tag, Click; expands URL with all Module 6 fields |
| `shortener/0003_seed_default_tags` | **Data migration** — seeds 8 default tags (Marketing, Social, Blog, Campaign, Product, Support, Internal, News) |

Run migrations:
```bash
python manage.py migrate
```

---

## Custom Managers & QuerySets

### `URLManager`

All methods return **optimized querysets** — `select_related('owner')` and `prefetch_related('tags')` are applied automatically to prevent N+1 queries.

| Method | Description |
|---|---|
| `URL.objects.active_urls()` | Non-expired, active URLs only |
| `URL.objects.expired_urls()` | Deactivated or past-expiry URLs |
| `URL.objects.popular_urls()` | Ordered by `click_count` descending |
| `URL.objects.with_click_stats()` | Annotates each URL with `total_clicks_recorded` (DB aggregation via `annotate`) |

### `ClickManager`

| Method | Description |
|---|---|
| `Click.objects.clicks_per_country(url_id)` | Returns `{'country': ..., 'total': ...}` dicts ordered by count — all computed in the database using `values().annotate(Count)`, never in Python |

---

## Query Optimisation

### N+1 Prevention
Every queryset that touches `owner` or `tags` uses:
```python
.select_related('owner')      # single JOIN for the FK — no extra queries per URL
.prefetch_related('tags')     # single IN query for M2M — no extra queries per URL
```
Without this, fetching 100 URLs would fire 201 queries (1 + 100 owners + 100 tag sets).
With it, it fires exactly 2.

### Database Indexes
```python
short_code = CharField(db_index=True)   # every redirect is a lookup on this
created_at = DateTimeField(db_index=True)  # time-range dashboard queries
```

### DB-Level Aggregation
Click stats are computed with `annotate()` and `values()` — the database does the grouping and counting, not a Python loop:
```python
Click.objects.filter(url_id=url_id)
    .values('country')
    .annotate(total=Count('id'))
    .order_by('-total')
```

---

## Caching Strategy

**Backend:** Redis in production (`REDIS_URL` env var); `LocMemCache` in development (no setup needed).

**What is cached:** URL objects, keyed as `url:<short_code>`, with a 15-minute TTL.

**Cache lifecycle:**
1. `GET /r/<short_code>/` — checks `cache.get('url:<short_code>')` first. On a miss it queries the DB and calls `cache.set(...)`.
2. `POST /deactivate/<short_code>/` — calls `cache.delete('url:<short_code>')` inside the same `transaction.atomic()` block so the cache is never out of sync with the DB.
3. `POST /shorten/` — calls `cache.delete(...)` after creation to invalidate any stale entry.

**Why Redis?** Redis is an in-memory store with sub-millisecond latency. For a URL shortener, every redirect benefits from avoiding a DB round-trip. At 10,000 redirects/minute, caching cuts database load by ~95% for hot URLs.

---

## Multi-Database Routing

**File:** `config/routers.py` — `AnalyticsReplicaRouter`

The router implements Django's database-routing interface to separate high-volume analytics reads from transactional writes.

| Operation | Database |
|---|---|
| All writes | `default` (primary) |
| `Click` model reads | `analytics_replica` |
| All other reads | `default` |
| Migrations | `default` only |

**Configuration:**
```env
# .env
DATABASE_URL=postgres://user:pass@primary-host:5432/urlshortener
ANALYTICS_REPLICA_URL=postgres://user:pass@replica-host:5432/urlshortener
```

If `ANALYTICS_REPLICA_URL` is not set, the router mirrors `default` transparently — no code changes needed between development and production.

**Why a separate replica?**
The `Click` table grows unboundedly (one row per visit). At scale this table will be orders of magnitude larger than all others combined. Routing its reads to a replica keeps the primary database free for low-latency writes (URL creation, click logging) while long-running analytics queries run on the replica without causing lock contention.

---

## Atomic Transactions

All view operations that touch multiple tables are wrapped in `transaction.atomic()`:

- `ShortenURLView.post` — URL creation + tag assignment in one transaction. If tag assignment fails, the URL record is rolled back.
- `RedirectView.get` — Click logging + `click_count` increment in a nested atomic block. If analytics logging fails, the redirect still completes.
- `DeactivateURLView.post` — DB update + cache eviction in one atomic block. The cache is never evicted for a deactivation that was rolled back.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | insecure dev key | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `DATABASE_URL` | SQLite | Primary DB connection string |
| `ANALYTICS_REPLICA_URL` | mirrors default | Analytics read-replica connection string |
| `REDIS_URL` | LocMemCache | Redis connection string for caching |

---

## Running the Project

```bash
# Install dependencies
pip install -r backend/requirements.txt

# Apply migrations (includes seeding default tags)
python backend/manage.py migrate

# Run the development server
python backend/manage.py runserver

# Run tests
python backend/manage.py test shortener
```
