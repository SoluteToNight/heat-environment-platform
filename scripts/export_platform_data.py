"""
Export platform database and spatial datasets for migration to other devices.
Generates:
  1. data_package/01_platform_seed.sql (platform schema + tables + seed data)
  2. data_package/02_public_admin_boundary.sql (base_admin_boundary full 17 districts)
  3. data_package/03_public_spatial_core_sample.sql (core urban area OSM sample: buildings, roads, water, green, poi)
  4. Optional --full: dumps full database to data_package/gis_thermal_shanghai_full.sql.gz
"""
import os
import sys
import gzip
import argparse
from pathlib import Path
import psycopg2
from psycopg2 import sql

def load_db_url():
    env_file = Path(__file__).resolve().parent.parent / "backend" / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/gis_thermal_shanghai")

def export_table_data(cur, schema, table_name, where_clause="", geom_cols=None):
    if geom_cols is None:
        geom_cols = []
    
    # Get columns
    cur.execute("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns 
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
    """, (schema, table_name))
    cols_info = cur.fetchall()
    col_names = [c[0] for c in cols_info]
    
    select_items = []
    for col, dtype, udt in cols_info:
        if udt == 'geometry' or col in geom_cols:
            select_items.append(f'ST_AsEWKT("{col}") AS "{col}"')
        else:
            select_items.append(f'"{col}"')
            
    query = f'SELECT {", ".join(select_items)} FROM "{schema}"."{table_name}"'
    if where_clause:
        query += f' WHERE {where_clause}'
        
    cur.execute(query)
    rows = cur.fetchall()
    return col_names, rows

def format_sql_value(val, col_name, geom_cols):
    if val is None:
        return "NULL"
    if col_name in geom_cols or (isinstance(val, str) and (val.startswith("SRID=") or val.startswith("POINT") or val.startswith("POLYGON") or val.startswith("MULTIPOLYGON") or val.startswith("LINESTRING") or val.startswith("MULTILINESTRING"))):
        val_str = str(val).replace("'", "''")
        return f"ST_GeomFromEWKT('{val_str}')"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (dict, list)):
        import json
        json_str = json.dumps(val, ensure_ascii=False).replace("'", "''")
        return f"'{json_str}'::jsonb"
    # string / datetime
    val_str = str(val).replace("'", "''")
    return f"'{val_str}'"

def main():
    parser = argparse.ArgumentParser(description="Export platform database data package")
    parser.add_argument("--db-url", default=None, help="Database connection URL")
    parser.add_argument("--full", action="store_true", help="Also export full citywide database")
    args = parser.parse_args()

    db_url = args.db_url or load_db_url()
    package_dir = Path(__file__).resolve().parent.parent / "data_package"
    package_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[1/4] Connecting to database...")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # 1. Platform schema seed
    print(f"[2/4] Exporting platform schema seed (01_platform_seed.sql)...")
    out_platform = package_dir / "01_platform_seed.sql"
    with open(out_platform, "w", encoding="utf-8") as f:
        f.write("-- ==============================================================\n")
        f.write("-- 01. Platform Schema, Tables and Seed Data\n")
        f.write("-- ==============================================================\n\n")
        f.write("CREATE EXTENSION IF NOT EXISTS postgis;\n")
        f.write("CREATE SCHEMA IF NOT EXISTS platform;\n\n")
        
        # Tables to export in platform
        platform_tables = [
            ("users", ["geom_exact", "geom_coarse"]),
            ("user_sessions", []),
            ("scenes", []),
            ("env_releases", []),
            ("weather_records", []),
            ("env_views", []),
            ("ugc_check_ins", ["geom_exact", "geom_coarse"]),
            ("ugc_reports", []),
            ("system_tasks", []),
            ("export_records", [])
        ]
        
        for tbl, geoms in platform_tables:
            # Generate DDL
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'platform' AND table_name = %s;
            """, (tbl,))
            if not cur.fetchone():
                continue
                
            col_names, rows = export_table_data(cur, "platform", tbl, geom_cols=geoms)
            if not rows:
                continue
                
            f.write(f"-- Data for platform.{tbl} ({len(rows)} rows)\n")
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            
            # Batch inserts
            batch_size = 50
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, geoms) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO platform."{tbl}" ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT DO NOTHING;\n")
            f.write("\n")
            print(f"   Exported platform.{tbl}: {len(rows)} rows")

    # 2. Base Admin Boundary
    print(f"[3/4] Exporting admin boundary (02_public_admin_boundary.sql)...")
    out_admin = package_dir / "02_public_admin_boundary.sql"
    with open(out_admin, "w", encoding="utf-8") as f:
        f.write("-- ==============================================================\n")
        f.write("-- 02. Administrative Boundaries (Shanghai City & 16 Districts)\n")
        f.write("-- ==============================================================\n\n")
        f.write("""
CREATE TABLE IF NOT EXISTS public.base_admin_boundary (
    admin_id VARCHAR(64) PRIMARY KEY,
    osm_type VARCHAR(16),
    osm_id VARCHAR(32),
    name VARCHAR(128) NOT NULL,
    name_en VARCHAR(128),
    admin_level SMALLINT NOT NULL,
    boundary VARCHAR(32) DEFAULT 'administrative',
    area_km2 DOUBLE PRECISION,
    perimeter_km DOUBLE PRECISION,
    is_core_district BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_base_admin_boundary_geom ON public.base_admin_boundary USING GIST (geom);
\n""")
        col_names, rows = export_table_data(cur, "public", "base_admin_boundary", geom_cols=["geom"])
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write("TRUNCATE TABLE public.base_admin_boundary CASCADE;\n")
            for i in range(0, len(rows), 10):
                batch = rows[i:i+10]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.base_admin_boundary ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(";\n")
            print(f"   Exported public.base_admin_boundary: {len(rows)} rows")

    # 3. Core Spatial Sample
    print(f"[4/4] Exporting core urban area spatial sample (03_public_spatial_core_sample.sql)...")
    out_sample = package_dir / "03_public_spatial_core_sample.sql"
    with open(out_sample, "w", encoding="utf-8") as f:
        f.write("-- ==============================================================\n")
        f.write("-- 03. Core Urban Area Spatial Sample (Huangpu / Jing'an / Lujiazui)\n")
        f.write("-- Contains 3D buildings, roads, water, green, and POIs\n")
        f.write("-- BBOX: [121.44, 31.20, 121.53, 31.26]\n")
        f.write("-- ==============================================================\n\n")
        
        # DDLs for the 5 spatial tables
        f.write("""
CREATE TABLE IF NOT EXISTS public.osm_buildings (
    building_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(16) DEFAULT 'way',
    osm_id VARCHAR(32),
    name VARCHAR(256),
    building VARCHAR(64) DEFAULT 'yes',
    height DOUBLE PRECISION,
    levels INTEGER,
    min_level INTEGER,
    amenity VARCHAR(64),
    tourism VARCHAR(64),
    addr_city VARCHAR(64),
    addr_district VARCHAR(64),
    addr_street VARCHAR(128),
    addr_housenumber VARCHAR(64),
    area_m2 DOUBLE PRECISION,
    perimeter_m DOUBLE PRECISION,
    height_m DOUBLE PRECISION,
    height_source VARCHAR(64),
    volume_m3 DOUBLE PRECISION,
    elevation_m DOUBLE PRECISION,
    geom GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_buildings_geom ON public.osm_buildings USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_buildings_building_id ON public.osm_buildings (building_id);

CREATE TABLE IF NOT EXISTS public.osm_roads (
    road_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(16) DEFAULT 'way',
    osm_id VARCHAR(32),
    name VARCHAR(256),
    name_en VARCHAR(256),
    highway VARCHAR(64),
    surface VARCHAR(64),
    maxspeed VARCHAR(32),
    oneway VARCHAR(16),
    length_m DOUBLE PRECISION,
    geom GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_roads_geom ON public.osm_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_roads_road_id ON public.osm_roads (road_id);

CREATE TABLE IF NOT EXISTS public.osm_water (
    water_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(16) DEFAULT 'way',
    osm_id VARCHAR(32),
    name VARCHAR(256),
    name_en VARCHAR(256),
    water_type VARCHAR(64),
    natural_type VARCHAR(64),
    waterway VARCHAR(64),
    area_m2 DOUBLE PRECISION,
    length_m DOUBLE PRECISION,
    geom GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_water_geom ON public.osm_water USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_water_water_id ON public.osm_water (water_id);

CREATE TABLE IF NOT EXISTS public.osm_green (
    green_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(16) DEFAULT 'way',
    osm_id VARCHAR(32),
    name VARCHAR(256),
    name_en VARCHAR(256),
    leisure VARCHAR(64),
    landuse VARCHAR(64),
    area_m2 DOUBLE PRECISION,
    perimeter_m DOUBLE PRECISION,
    geom GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_green_geom ON public.osm_green USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_green_green_id ON public.osm_green (green_id);

CREATE TABLE IF NOT EXISTS public.osm_poi (
    poi_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(16) DEFAULT 'node',
    osm_id VARCHAR(32),
    name VARCHAR(256),
    name_en VARCHAR(256),
    amenity VARCHAR(64),
    shop VARCHAR(64),
    tourism VARCHAR(64),
    geom GEOMETRY(Geometry, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_osm_poi_geom ON public.osm_poi USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_poi_poi_id ON public.osm_poi (poi_id);
\n""")
        
        # We take core area: 121.44 to 121.53, 31.20 to 31.26
        # To keep file size very fast and reasonable, limit buildings to top 8000 (especially with height), roads to 5000, all water and green in bbox
        bbox_where = "geom && ST_MakeEnvelope(121.44, 31.20, 121.53, 31.26, 4326)"
        
        # 3.1 Buildings
        col_names, rows = export_table_data(
            cur, "public", "osm_buildings", 
            where_clause=f"{bbox_where} ORDER BY (height IS NOT NULL) DESC, area_m2 DESC NULLS LAST LIMIT 8000",
            geom_cols=["geom"]
        )
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write(f"-- Sample Buildings ({len(rows)} rows)\n")
            for i in range(0, len(rows), 100):
                batch = rows[i:i+100]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.osm_buildings ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT (building_id) DO NOTHING;\n")
            print(f"   Exported core osm_buildings: {len(rows)} rows")
            
        # 3.2 Roads
        col_names, rows = export_table_data(
            cur, "public", "osm_roads",
            where_clause=f"{bbox_where} LIMIT 5000",
            geom_cols=["geom"]
        )
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write(f"\n-- Sample Roads ({len(rows)} rows)\n")
            for i in range(0, len(rows), 100):
                batch = rows[i:i+100]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.osm_roads ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT (road_id) DO NOTHING;\n")
            print(f"   Exported core osm_roads: {len(rows)} rows")

        # 3.3 Water
        col_names, rows = export_table_data(
            cur, "public", "osm_water",
            where_clause=f"{bbox_where}",
            geom_cols=["geom"]
        )
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write(f"\n-- Sample Water ({len(rows)} rows)\n")
            for i in range(0, len(rows), 100):
                batch = rows[i:i+100]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.osm_water ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT (water_id) DO NOTHING;\n")
            print(f"   Exported core osm_water: {len(rows)} rows")

        # 3.4 Green
        col_names, rows = export_table_data(
            cur, "public", "osm_green",
            where_clause=f"{bbox_where}",
            geom_cols=["geom"]
        )
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write(f"\n-- Sample Green ({len(rows)} rows)\n")
            for i in range(0, len(rows), 100):
                batch = rows[i:i+100]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.osm_green ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT (green_id) DO NOTHING;\n")
            print(f"   Exported core osm_green: {len(rows)} rows")

        # 3.5 POI
        col_names, rows = export_table_data(
            cur, "public", "osm_poi",
            where_clause=f"{bbox_where} LIMIT 3000",
            geom_cols=["geom"]
        )
        if rows:
            cols_joined = ", ".join([f'"{c}"' for c in col_names])
            f.write(f"\n-- Sample POI ({len(rows)} rows)\n")
            for i in range(0, len(rows), 100):
                batch = rows[i:i+100]
                values_list = []
                for row in batch:
                    vals = [format_sql_value(val, col, ["geom"]) for val, col in zip(row, col_names)]
                    values_list.append(f"({', '.join(vals)})")
                f.write(f'INSERT INTO public.osm_poi ({cols_joined}) VALUES\n')
                f.write(",\n".join(values_list))
                f.write(" ON CONFLICT (poi_id) DO NOTHING;\n")
            print(f"   Exported core osm_poi: {len(rows)} rows")

    cur.close()
    conn.close()
    print("\nData package successfully created in data_package/")

if __name__ == "__main__":
    main()
