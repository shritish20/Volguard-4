from app.database import SessionLocal
from sqlalchemy.orm import Session

def get_db():
    """Dependency to get a SQLAlchemy database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
