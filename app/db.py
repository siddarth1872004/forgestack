"""Database setup: Supabase PostgreSQL in production, SQLite for local development."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

raw_url = os.getenv("DATABASE_URL", "").strip()
if raw_url:
    DATABASE_URL = raw_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_PATH = Path(__file__).resolve().parent.parent / "inventory.db"
    DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite:") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=1 if os.getenv("VERCEL") else 5,
    max_overflow=0 if os.getenv("VERCEL") else 10,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
