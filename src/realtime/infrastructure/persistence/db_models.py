from sqlalchemy import Column, Integer, Text, JSON, DateTime, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class RealtimeSessionItem(Base):
    __tablename__ = "realtime_session_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    connection_key = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)
    org_id = Column(Integer, nullable=True, index=True)
    created_by_id = Column(Integer, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
