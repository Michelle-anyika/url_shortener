# Stage 1: Builder
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install compilation dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Compile Python dependencies to wheels
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt


# Stage 2: Final Runtime
FROM python:3.11-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies for Postgres
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled wheels from builder and install them
COPY --from=builder /app/wheels /wheels
RUN pip install --upgrade pip && \
    pip install --no-cache /wheels/* && \
    rm -rf /wheels

# Create a system user and group to run Django without root privileges
RUN addgroup --system app && adduser --system --group app

# Copy application files
COPY . /app/

# Grant ownership of the application directory to the non-root user
RUN chown -R app:app /app

# Run container under user space
USER app

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
