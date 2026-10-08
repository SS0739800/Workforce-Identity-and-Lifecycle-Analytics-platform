from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AIInsightRun(Base):
    """Log of AI requests. Stores sanitized summaries only, never raw prompts with personal data.

    The table is created now so the schema is complete; it is first written to in the AI phase.
    """

    __tablename__ = "ai_insight_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    insight_type: Mapped[str] = mapped_column(String(50))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
