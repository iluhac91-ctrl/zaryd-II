from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent

if Path("/data").exists():
    DB_PATH = Path("/data/station.db")
else:
    DB_PATH = BASE_DIR / "station.db"

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_columns():
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                phone VARCHAR NOT NULL UNIQUE,
                pin_hash VARCHAR NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]

        if "payment_token" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN payment_token TEXT"))
        if "card_last_four" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN card_last_four TEXT"))
        if "card_type" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN card_type TEXT"))
        if "demo_paid" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN demo_paid INTEGER DEFAULT 0"))
