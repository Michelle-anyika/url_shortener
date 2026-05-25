"""
Gunicorn configuration for URL Shortener production deployment.

Start the server:
  gunicorn -c gunicorn.conf.py config.wsgi:application

Tuning rationale
----------------
Workers:
  The standard formula is (2 * CPU cores) + 1.
  Each worker handles one request at a time (sync worker class).
  With 2 CPUs this gives 5 workers; adjust GUNICORN_WORKERS via env.

Threads:
  Using threads (--threads 2) per worker doubles concurrency with less
  memory overhead than adding more workers. Good for I/O-bound views.

Timeouts:
  timeout=30  — kill workers that don't respond within 30 seconds.
                Prevents runaway requests from blocking all workers.
  keepalive=5 — keep HTTP connections alive for 5 seconds to reduce
                TCP handshake overhead on repeat clients.

max_requests:
  Restart workers after N requests to prevent memory leaks from
  slowly-growing Python objects or C extensions.
  max_requests_jitter adds a random delta so all workers don't
  restart simultaneously.

preload_app:
  Load the Django application once in the master process before forking.
  Workers share the loaded code (copy-on-write), reducing memory and
  startup time.

Access log format:
  JSON-structured so log aggregators (Datadog, ELK) can parse fields.
"""

import multiprocessing
import os

# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')

# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
workers = int(os.getenv('GUNICORN_WORKERS', (2 * multiprocessing.cpu_count()) + 1))
threads = int(os.getenv('GUNICORN_THREADS', 2))
worker_class = 'sync'
worker_connections = 1000

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
timeout = 30
keepalive = 5
graceful_timeout = 30

# ---------------------------------------------------------------------------
# Memory leak prevention
# ---------------------------------------------------------------------------
max_requests = 1000
max_requests_jitter = 100

# ---------------------------------------------------------------------------
# Application loading
# ---------------------------------------------------------------------------
preload_app = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
accesslog = '-'   # stdout
errorlog = '-'    # stderr
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# JSON-structured access log so fields are parseable by log aggregators
access_log_format = (
    '{"time":"%(t)s","method":"%(m)s","path":"%(U)s","status":%(s)s,'
    '"response_length":%(b)s,"referer":"%(f)s","user_agent":"%(a)s",'
    '"duration_ms":%(D)s}'
)

# ---------------------------------------------------------------------------
# Process naming
# ---------------------------------------------------------------------------
proc_name = 'url_shortener'
