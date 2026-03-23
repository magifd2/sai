"""Memory data models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MemoryState(str, Enum):
    HOT    = "hot"    # < 24h: full original content
    WARM   = "warm"   # 1-7 days: LLM-summarized
    COLD   = "cold"   # > 7 days: pending archive
    PINNED = "pinned" # reaction-triggered: never aged or archived


class MemoryRecord(BaseModel):
    id: str
    user_id: str
    user_name: str
    channel_id: str
    channel_name: Optional[str] = None
    ts: str                           # Slack message timestamp string
    created_at: datetime
    content: str
    state: MemoryState
    is_summary: bool = False
    summary_of: list[str] = Field(default_factory=list)  # source record IDs
    pinned_at: Optional[datetime] = None
    pinned_by: Optional[str] = None   # user_id who added the reaction
    pin_reaction: Optional[str] = None  # reaction name that triggered pinning
    nonce: Optional[str] = None
    embedding_id: Optional[str] = None


class MemoryArchiveRecord(BaseModel):
    id: str
    user_id: str
    user_name: str
    channel_id: str
    channel_name: Optional[str] = None
    ts: str
    created_at: datetime
    archived_at: datetime
    content: str
    is_summary: bool = False
