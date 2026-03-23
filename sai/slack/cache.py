"""Two-layer cache for Slack users and channels.

Layer 1: In-memory dict (process lifetime, fast)
Layer 2: DuckDB (persistent across restarts)

Freshness rules:
  - Users:    re-fetch from Slack API if DB record > 1 hour old
  - Channels: re-fetch from Slack API if DB record > 6 hours old
"""

import time
from typing import Optional

from ..db.repositories.channel import ChannelRecord, ChannelRepository
from ..db.repositories.user import UserRecord, UserRepository
from ..utils.logging import get_logger
from .client import SlackClient

logger = get_logger(__name__)

_USER_TTL = 3600       # 1 hour
_CHANNEL_TTL = 21600   # 6 hours


class CacheManager:
    def __init__(
        self,
        slack: SlackClient,
        user_repo: UserRepository,
        channel_repo: ChannelRepository,
    ) -> None:
        self._slack = slack
        self._user_repo = user_repo
        self._channel_repo = channel_repo
        self._users: dict[str, UserRecord] = {}
        self._channels: dict[str, ChannelRecord] = {}

    async def warm_up(self) -> None:
        """Load all users and channels at startup."""
        logger.info("cache.warm_up.start")
        await self._refresh_all_users()
        await self._refresh_all_channels()
        logger.info(
            "cache.warm_up.done",
            users=len(self._users),
            channels=len(self._channels),
        )

    async def get_user(self, user_id: str) -> Optional[UserRecord]:
        # L1: memory
        record = self._users.get(user_id)
        if record and self._fresh(record.fetched_at, _USER_TTL):
            return record

        # L2: DB
        record = await self._user_repo.get(user_id)
        if record and self._fresh(record.fetched_at, _USER_TTL):
            self._users[user_id] = record
            return record

        # Fetch from Slack API
        return await self._fetch_user(user_id)

    async def get_channel(self, channel_id: str) -> Optional[ChannelRecord]:
        # L1: memory
        record = self._channels.get(channel_id)
        if record and self._fresh(record.fetched_at, _CHANNEL_TTL):
            return record

        # L2: DB
        record = await self._channel_repo.get(channel_id)
        if record and self._fresh(record.fetched_at, _CHANNEL_TTL):
            self._channels[channel_id] = record
            return record

        # Fetch from Slack API
        return await self._fetch_channel(channel_id)

    async def _fetch_user(self, user_id: str) -> Optional[UserRecord]:
        info = await self._slack.get_user_info(user_id)
        if not info:
            return None
        profile = info.get("profile", {})
        record = UserRecord(
            user_id=user_id,
            user_name=info.get("name", user_id),
            display_name=profile.get("display_name") or profile.get("real_name"),
            is_bot=info.get("is_bot", False),
            fetched_at=time.time(),
        )
        await self._user_repo.save(record)
        self._users[user_id] = record
        return record

    async def _fetch_channel(self, channel_id: str) -> Optional[ChannelRecord]:
        info = await self._slack.get_conversation_info(channel_id)
        if not info:
            return None
        record = ChannelRecord(
            channel_id=channel_id,
            channel_name=info.get("name", channel_id),
            is_private=info.get("is_private", False),
            fetched_at=time.time(),
        )
        await self._channel_repo.save(record)
        self._channels[channel_id] = record
        return record

    async def _refresh_all_users(self) -> None:
        now = time.time()
        users = await self._slack.list_users()
        records = []
        for u in users:
            profile = u.get("profile", {})
            records.append(UserRecord(
                user_id=u["id"],
                user_name=u.get("name", u["id"]),
                display_name=profile.get("display_name") or profile.get("real_name"),
                is_bot=u.get("is_bot", False),
                fetched_at=now,
            ))
        await self._user_repo.save_many(records)
        self._users = {r.user_id: r for r in records}

    async def _refresh_all_channels(self) -> None:
        now = time.time()
        channels = await self._slack.list_channels()
        records = []
        for c in channels:
            records.append(ChannelRecord(
                channel_id=c["id"],
                channel_name=c.get("name", c["id"]),
                is_private=c.get("is_private", False),
                fetched_at=now,
            ))
        await self._channel_repo.save_many(records)
        self._channels = {r.channel_id: r for r in records}

    @staticmethod
    def _fresh(fetched_at: float, ttl: int) -> bool:
        return (time.time() - fetched_at) < ttl
