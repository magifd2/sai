"""Slack event type definitions and parsers."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from ..utils.time import utcnow


class SlackEventType(str, Enum):
    MESSAGE = "message"
    APP_MENTION = "app_mention"
    REACTION_ADDED = "reaction_added"
    REACTION_REMOVED = "reaction_removed"
    MESSAGE_CHANGED = "message_changed"
    MESSAGE_DELETED = "message_deleted"
    UNKNOWN = "unknown"


class SlackEvent(BaseModel):
    event_type: SlackEventType
    user_id: str
    channel_id: str
    text: str
    ts: str
    thread_ts: Optional[str] = None
    received_at: datetime
    # For reaction events
    reaction: Optional[str] = None          # reaction name e.g. "pushpin"
    reaction_target_ts: Optional[str] = None  # ts of the reacted-to message
    reaction_target_channel: Optional[str] = None
    is_bot: bool = False
    # For message_changed / message_deleted: ts of the original message
    original_ts: Optional[str] = None


def parse_event(payload: dict) -> Optional[SlackEvent]:
    """
    Parse a raw Slack event payload into a SlackEvent.
    Returns None for event types we don't handle.
    """
    event = payload.get("event", payload)
    etype = event.get("type", "")
    subtype = event.get("subtype", "")

    # Skip bot messages (other than our own app_mention handling)
    if subtype == "bot_message":
        return None

    now = utcnow()

    if etype == "app_mention":
        return SlackEvent(
            event_type=SlackEventType.APP_MENTION,
            user_id=event.get("user", ""),
            channel_id=event.get("channel", ""),
            text=event.get("text", ""),
            ts=event.get("ts", ""),
            thread_ts=event.get("thread_ts"),
            received_at=now,
            is_bot=bool(event.get("bot_id")),
        )

    if etype == "message" and subtype == "message_changed":
        message = event.get("message", {})
        return SlackEvent(
            event_type=SlackEventType.MESSAGE_CHANGED,
            user_id=message.get("user", ""),
            channel_id=event.get("channel", ""),
            text=message.get("text", ""),
            ts=event.get("event_ts") or event.get("ts", ""),
            thread_ts=message.get("thread_ts"),
            received_at=now,
            is_bot=bool(message.get("bot_id")),
            original_ts=message.get("ts"),
        )

    if etype == "message" and subtype == "message_deleted":
        prev = event.get("previous_message", {})
        return SlackEvent(
            event_type=SlackEventType.MESSAGE_DELETED,
            user_id=prev.get("user", ""),
            channel_id=event.get("channel", ""),
            text="",
            ts=event.get("event_ts") or event.get("ts", ""),
            received_at=now,
            original_ts=event.get("deleted_ts") or prev.get("ts", ""),
        )

    if etype == "message":
        return SlackEvent(
            event_type=SlackEventType.MESSAGE,
            user_id=event.get("user", ""),
            channel_id=event.get("channel", ""),
            text=event.get("text", ""),
            ts=event.get("ts", ""),
            thread_ts=event.get("thread_ts"),
            received_at=now,
            is_bot=bool(event.get("bot_id")),
        )

    if etype == "reaction_added":
        item = event.get("item", {})
        return SlackEvent(
            event_type=SlackEventType.REACTION_ADDED,
            user_id=event.get("user", ""),
            channel_id=item.get("channel", ""),
            text="",
            ts=event.get("event_ts", ""),
            received_at=now,
            reaction=event.get("reaction"),
            reaction_target_ts=item.get("ts"),
            reaction_target_channel=item.get("channel"),
        )

    return None
