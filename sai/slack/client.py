"""Slack WebClient wrapper with async interface."""

import asyncio
from typing import Any, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..utils.logging import get_logger

logger = get_logger(__name__)


class SlackClient:
    """Thin async wrapper around the synchronous Slack WebClient."""

    def __init__(self, bot_token: str) -> None:
        self._client = WebClient(token=bot_token)

    async def _call(self, method_name: str, **kwargs: Any) -> dict:
        """Offload a synchronous Slack API call to a thread."""
        def _sync() -> dict:
            method = getattr(self._client, method_name)
            return method(**kwargs)
        return await asyncio.to_thread(_sync)

    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
    ) -> dict:
        kwargs: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        return await self._call("chat_postMessage", **kwargs)

    async def get_user_info(self, user_id: str) -> Optional[dict]:
        try:
            resp = await self._call("users_info", user=user_id)
            return resp.get("user")
        except SlackApiError as exc:
            logger.warning("slack.get_user_info_failed", user_id=user_id, error=str(exc))
            return None

    async def get_conversation_info(self, channel_id: str) -> Optional[dict]:
        try:
            resp = await self._call("conversations_info", channel=channel_id)
            return resp.get("channel")
        except SlackApiError as exc:
            logger.warning("slack.get_channel_info_failed", channel_id=channel_id, error=str(exc))
            return None

    async def list_users(self, limit: int = 200) -> list[dict]:
        """Fetch all users (paginated). Returns list of user objects."""
        users = []
        cursor = None
        while True:
            kwargs: dict[str, Any] = {"limit": limit}
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = await self._call("users_list", **kwargs)
            except SlackApiError as exc:
                logger.error("slack.list_users_failed", error=str(exc))
                break
            users.extend(resp.get("members", []))
            meta = resp.get("response_metadata", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break
        return users

    async def list_channels(self, limit: int = 200) -> list[dict]:
        """Fetch all public channels (paginated)."""
        channels = []
        cursor = None
        while True:
            kwargs: dict[str, Any] = {
                "limit": limit,
                "types": "public_channel,private_channel",
            }
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = await self._call("conversations_list", **kwargs)
            except SlackApiError as exc:
                logger.error("slack.list_channels_failed", error=str(exc))
                break
            channels.extend(resp.get("channels", []))
            meta = resp.get("response_metadata", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break
        return channels

    async def get_message(self, channel_id: str, ts: str) -> Optional[dict]:
        """Fetch a specific message by channel and timestamp."""
        try:
            resp = await self._call(
                "conversations_history",
                channel=channel_id,
                latest=ts,
                limit=1,
                inclusive=True,
            )
            messages = resp.get("messages", [])
            return messages[0] if messages else None
        except SlackApiError as exc:
            logger.warning(
                "slack.get_message_failed",
                channel_id=channel_id,
                ts=ts,
                error=str(exc),
            )
            return None
