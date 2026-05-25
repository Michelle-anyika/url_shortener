# URL Shortener Microservice

An enterprise-grade URL shortener built with Django and Django REST Framework.

---

## Module 7 — Authentication & Authorization

This module locks down the API, enforces role-based business rules, and hardens the application against common security threats.

---

## User Roles & Tiers

| Tier | Active URLs | Custom Aliases | Analytics | Notes |
|---|---|---|---|---|
| **Free** | Max 10 | ✗ | ✗ | Default for new accounts |
| **Premium** | Unlimited | ✓ | ✓ | Paid tier |
| **Admin** | Unlimited | ✓ | ✓ | Staff access |

The `is_premium` flag on the User model is kept in sync automatically with the `tier` field via the model's `save()` method.

---

## API Endpoints

### Authentication

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register/` | None | Create a new account |
| POST | `/api/v1/auth/login/` | None | Obtain JWT access + refresh tokens (rate-limited: 5/min) |
| POST | `/api/v1/auth/refresh/` | None | Refresh an access token |
| POST | `/api/v1/auth/logout/` | JWT | Blacklist a refresh token (logout) |
| POST | `/api/v1/auth/social/` | None | Social login (Google ID token → JWT) |

### URL Management

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/urls/` | JWT | Create a short URL (tier rules apply) |
| GET | `/api/v1/urls/list/` | JWT | List your own URLs |
| GET | `/api/v1/urls/<code>/` | Public | Retrieve URL details |
| PATCH | `/api/v1/urls/<code>/` | JWT + owner | Update your URL |
| DELETE | `/api/v1/urls/<code>/` | JWT + owner | Delete your URL |
| GET | `/api/v1/analytics/<code>/` | JWT + Premium + owner | Detailed analytics |

### Public

| Method | Endpoint | Description |
|---|---|---|
| GET | `/<short_code>/` | Redirect to original URL |

---

## Permission Classes

All permission classes live in `api/permissions.py`.

**`IsOwnerOrReadOnly`**
Safe HTTP methods (GET, HEAD, OPTIONS) are open to anyone including anonymous users. Mutating methods (POST, PUT, PATCH, DELETE) are restricted to the resource's `owner`. Returns `403 Forbidden` for non-owners.

**`IsOwnerOnly`**
All methods — including reads — are restricted to the owner. Used on the analytics endpoint so users can't peek at each other's stats.

**`IsPremiumUser`**
View-level gate. Allows access only to users with `tier == 'Premium'` or `tier == 'Admin'`. Returns `403` with a message directing the user to upgrade.

**`CanUseCustomAlias`**
Request-level gate checked before the serializer. If a `custom_alias` field is present in the request body, the user must be Premium or Admin. Returns `403` immediately — never reaches the serializer.

---

## JWT Configuration

- **Algorithm:** HS256
- **Access token lifetime:** 60 minutes
- **Refresh token lifetime:** 1 day
- **Refresh rotation:** enabled (old token invalidated on each refresh)
- **Blacklisting:** enabled — `POST /auth/logout/` blacklists the refresh token so it cannot be reused even if intercepted

---

## Social Authentication (Google)

`POST /api/v1/auth/social/`

```json
{ "provider": "google", "token": "<Google ID token from the client>" }
```

Flow:
1. Client authenticates with Google and receives a Google ID token.
2. Client sends the ID token to this endpoint.
3. The backend verifies the token with Google's `tokeninfo` endpoint.
4. If valid, the backend gets-or-creates the user by email.
5. Returns a JWT pair immediately — no session is created.

---

## Security Best Practices

### Password Hashing
Passwords are hashed with **Argon2** (the strongest Django-supported algorithm), with PBKDF2 as a fallback. Argon2 is memory-hard and recommended by OWASP.

### JWT Security
- Tokens are stateless and signed with `SECRET_KEY` (HS256).
- Refresh tokens are rotated on every use and blacklisted after rotation.
- `POST /auth/logout/` explicitly blacklists the refresh token — even if an attacker captures the token they cannot reuse it after logout.

### Rate Limiting (Brute Force Protection)
The login endpoint (`/auth/login/`) is throttled to **5 requests per minute** per IP/user via DRF's `ScopedRateThrottle`. All anonymous traffic is limited to 100 requests/day and authenticated users to 1,000 requests/day.

### CSRF Protection
- `CsrfViewMiddleware` is enabled.
- `CSRF_COOKIE_HTTPONLY = True` and `CSRF_COOKIE_SECURE = True` in production.
- JWT-based API endpoints are CSRF-exempt by design (no session cookie is used).

### Security Headers (SecurityHeadersMiddleware)
Applied on every response via `config/middleware.py`:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | geolocation, mic, camera, payment disabled |
| `Content-Security-Policy` | `default-src 'self'` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (production only) |

### Input Sanitisation
- All URL inputs are validated by Django's `URLField` which rejects malformed URLs.
- `custom_alias` is constrained to `max_length=50, unique=True` at the model level.
- The `URLSerializer` enforces business rules before any DB write occurs.

---

## Setup & Installation

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd url_shortener/backend
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp ../.env.example .env
```

Edit `.env`:

```env
SECRET_KEY=your-very-secret-key
DEBUG=True
DATABASE_URL=postgres://user:pass@localhost:5432/urlshortener
REDIS_URL=redis://localhost:6379/0
ANALYTICS_REPLICA_URL=             # optional read replica
ALLOWED_HOSTS=localhost,127.0.0.1
```

### 3. Run migrations

```bash
python manage.py migrate
```

This applies all schema migrations and seeds the default tags.

### 4. Create a superuser (Admin tier)

```bash
python manage.py createsuperuser
# Then in the Django admin, set tier = Admin
```

### 5. Run the server

```bash
python manage.py runserver
```

Visit `http://localhost:8000/api/docs/` for the interactive Swagger UI.

### 6. Run tests

```bash
python manage.py test tests shortener
```

---

## Module 6 — ORM & Data Access Layer

See the Module 6 section in the git history or the previous README for details on the data schema, caching strategy, and multi-database routing.
