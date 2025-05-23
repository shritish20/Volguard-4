from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models import Base

# SQLAlchemy Engine
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})

# SessionLocal for database interactions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create database tables if they don't exist
def create_db_and_tables():
    Base.metadata.create_all(bind=engine)
