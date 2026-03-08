from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    skills_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hobbies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_tuning_mode: Mapped[str] = mapped_column(String(20), default="balanced", nullable=False)
    last_rescored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resume_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
