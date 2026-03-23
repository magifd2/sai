"""Access Control List enforcement.

Decision order (strict):
  1. Bot check — bots always denied unless explicitly whitelisted
  2. Blacklist — deny immediately, no further processing
  3. Whitelist mode — if enabled, deny anyone not in whitelist
  4. Open mode — allow if not blacklisted
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..db.repositories.acl import ACLRepository
from ..utils.logging import get_logger

logger = get_logger(__name__)


class ACLDecision(str, Enum):
    ALLOW = "allow"
    DENY_BLACKLIST = "deny_blacklist"
    DENY_NOT_WHITELISTED = "deny_not_whitelisted"
    DENY_BOT = "deny_bot"


@dataclass
class ACLResult:
    decision: ACLDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == ACLDecision.ALLOW


class ACLManager:
    def __init__(self, repo: ACLRepository, whitelist_mode: bool = False) -> None:
        self._repo = repo
        self._whitelist_mode = whitelist_mode

    async def check(self, user_id: str, is_bot: bool = False) -> ACLResult:
        """Evaluate ACL rules and return an allow/deny decision."""

        # 1. Bot check
        if is_bot:
            in_whitelist = await self._repo.is_in_list(user_id, "whitelist")
            if not in_whitelist:
                logger.info("acl.deny_bot", user_id=user_id)
                return ACLResult(ACLDecision.DENY_BOT, "bot not whitelisted")

        # 2. Blacklist
        if await self._repo.is_in_list(user_id, "blacklist"):
            logger.info("acl.deny_blacklist", user_id=user_id)
            return ACLResult(ACLDecision.DENY_BLACKLIST, "user is blacklisted")

        # 3. Whitelist mode
        if self._whitelist_mode:
            if not await self._repo.is_in_list(user_id, "whitelist"):
                logger.info("acl.deny_not_whitelisted", user_id=user_id)
                return ACLResult(ACLDecision.DENY_NOT_WHITELISTED, "whitelist mode: user not in whitelist")

        logger.debug("acl.allow", user_id=user_id)
        return ACLResult(ACLDecision.ALLOW, "allowed")

    async def add_to_whitelist(
        self, user_id: str, added_by: Optional[str] = None, reason: Optional[str] = None
    ) -> None:
        await self._repo.add(user_id, "whitelist", added_by=added_by, reason=reason)
        logger.info("acl.whitelist_add", user_id=user_id, added_by=added_by)

    async def add_to_blacklist(
        self, user_id: str, added_by: Optional[str] = None, reason: Optional[str] = None
    ) -> None:
        await self._repo.add(user_id, "blacklist", added_by=added_by, reason=reason)
        logger.info("acl.blacklist_add", user_id=user_id, added_by=added_by)

    async def remove_from_whitelist(self, user_id: str) -> None:
        await self._repo.remove(user_id, "whitelist")

    async def remove_from_blacklist(self, user_id: str) -> None:
        await self._repo.remove(user_id, "blacklist")

    async def seed_from_config(
        self, whitelist: list[str], blacklist: list[str]
    ) -> None:
        """Populate initial ACL entries from config (skips existing entries)."""
        await self._repo.seed(whitelist, "whitelist")
        await self._repo.seed(blacklist, "blacklist")
        logger.info(
            "acl.seeded",
            whitelist_count=len(whitelist),
            blacklist_count=len(blacklist),
        )
