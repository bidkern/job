from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class JobPacketHistory(Base):
    __tablename__ = "job_packet_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    packet_text: Mapped[str] = mapped_column(Text, nullable=False)
    ats_keywords: Mapped[str] = mapped_column(Text, nullable=False)
    resume_bullet_suggestions: Mapped[str] = mapped_column(Text, nullable=False)
    cover_letter_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    outreach_message_draft: Mapped[str] = mapped_column(Text, nullable=False)
    openai_used: Mapped[bool] = mapped_column(default=False)
    generated_via: Mapped[str] = mapped_column(Text, default="single")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
