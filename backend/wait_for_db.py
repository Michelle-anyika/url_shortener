import time
import sys
import psycopg2
from urllib.parse import urlparse
from decouple import config

def main():
    # Fetch DATABASE_URL from settings configuration
    db_url = config('DATABASE_URL', default='')
    if not db_url:
        print("DATABASE_URL not configured. Skipping database check.")
        sys.exit(0)

    url = urlparse(db_url)
    # Check if we are running in a PostgreSQL setup
    if url.scheme != 'postgres' and url.scheme != 'postgresql':
        print(f"Skipping wait for non-postgres database: {url.scheme}")
        sys.exit(0)

    host = url.hostname
    port = url.port or 5432
    dbname = url.path[1:]
    user = url.username
    password = url.password

    print(f"Waiting for Postgres to be available on {host}:{port} (database: {dbname})...")
    
    retries = 30
    for i in range(retries):
        try:
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                connect_timeout=2
            )
            conn.close()
            print("Postgres is up and running!")
            sys.exit(0)
        except psycopg2.OperationalError as e:
            print(f"Postgres not ready yet ({i + 1}/{retries}). Error: {e}")
            time.sleep(2)
            
    print("Postgres connection timeout. Exiting.")
    sys.exit(1)

if __name__ == '__main__':
    main()
