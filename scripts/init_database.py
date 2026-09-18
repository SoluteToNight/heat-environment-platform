"""
Database initialization and data restoration script for Heat Environment Platform.
Usage:
    python scripts/init_database.py [--db-url postgresql://...] [--drop-first]
"""
import os
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def load_db_url():
    env_file = Path(__file__).resolve().parent.parent / "backend" / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/gis_thermal_shanghai")

def ensure_database_exists(db_url):
    parsed = urlparse(db_url)
    target_db = parsed.path.lstrip("/") or "gis_thermal_shanghai"
    
    # Connect to default 'postgres' database to check/create target database
    admin_url = db_url.replace(f"/{target_db}", "/postgres")
    try:
        conn = psycopg2.connect(admin_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
        exists = cur.fetchone()
        if not exists:
            print(f"Creating database '{target_db}'...")
            cur.execute(f'CREATE DATABASE "{target_db}" WITH ENCODING "UTF8";')
            print(f"Database '{target_db}' created.")
        else:
            print(f"Database '{target_db}' already exists.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Notice during database check: {e}")

def execute_sql_file(conn, file_path):
    print(f"Executing {file_path.name}...")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()
    with conn.cursor() as cur:
        cur.execute(sql_content)
    conn.commit()
    print(f"Finished {file_path.name}.")

def main():
    parser = argparse.ArgumentParser(description="Initialize database and import packaged data")
    parser.add_argument("--db-url", default=None, help="Database connection URL")
    args = parser.parse_args()

    db_url = args.db_url or load_db_url()
    ensure_database_exists(db_url)
    
    package_dir = Path(__file__).resolve().parent.parent / "data_package"
    
    print(f"\nConnecting to target database: {db_url.split('@')[-1]}...")
    conn = psycopg2.connect(db_url)
    
    # 1. Platform seed
    f_seed = package_dir / "01_platform_seed.sql"
    if f_seed.exists():
        execute_sql_file(conn, f_seed)
        
    # 2. Admin boundary
    f_admin = package_dir / "02_public_admin_boundary.sql"
    if f_admin.exists():
        execute_sql_file(conn, f_admin)
        
    # 3. Core spatial sample
    f_sample = package_dir / "03_public_spatial_core_sample.sql"
    if f_sample.exists():
        execute_sql_file(conn, f_sample)

    # 4. Verify results
    print("\nVerifying imported table row counts:")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables 
            WHERE table_schema IN ('platform', 'public') AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name;
        """)
        tables = cur.fetchall()
        for s, t in tables:
            cur.execute(f'SELECT count(*) FROM "{s}"."{t}"')
            cnt = cur.fetchone()[0]
            print(f"  [{s}] {t}: {cnt} rows")

    conn.close()
    print("\nPlatform database initialization & data import completed successfully!")

if __name__ == "__main__":
    main()
