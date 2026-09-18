"""Database schema initialization and pre-seeding script."""
import datetime
import bcrypt
from sqlalchemy import text
from app.config import settings
from app.db.session import engine, SessionLocal, Base
from app.db.models import User, Scene, SCHEMA_NAME


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def init_platform_db():
    """Create schema, tables, and default seed data."""
    # 1. Ensure schema exists
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};"))

    # 2. Create tables
    Base.metadata.create_all(bind=engine)

    # 3. Pre-seed users & initial scene
    db = SessionLocal()
    try:
        # Seed test user
        existing_user = db.query(User).filter(User.username == "user_test").first()
        if not existing_user:
            u1 = User(
                username="user_test",
                password_hash=hash_password("user123456"),
                display_name="热感知测试员",
                role="user",
                is_active=True,
            )
            db.add(u1)

        # Seed admin user
        existing_admin = db.query(User).filter(User.username == "admin_test").first()
        if not existing_admin:
            u2 = User(
                username="admin_test",
                password_hash=hash_password("admin123456"),
                display_name="热环境运营管理员",
                role="admin",
                is_active=True,
            )
            db.add(u2)

        # Seed default scene: scene_shanghai
        existing_scene = db.query(Scene).filter(Scene.id == "scene_shanghai").first()
        if not existing_scene:
            scene = Scene(
                id="scene_shanghai",
                name="上海市全域热暴露场景",
                description="覆盖上海市全域（含中心城区及郊区）的主客观热暴露与环境监测打卡场景",
                center_lon=settings.SHANGHAI_CENTER_LON,
                center_lat=settings.SHANGHAI_CENTER_LAT,
                bbox=settings.SHANGHAI_BBOX,
                status="active",
            )
            db.add(scene)

        db.commit()
        print("Database schema and seed data initialized successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error during db initialization: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_platform_db()
