"""Tests for ACL enforcement."""

import pytest
from sai.security.acl import ACLDecision, ACLManager
from sai.db.repositories.acl import ACLRepository


@pytest.fixture
def acl(acl_repo):
    return ACLManager(acl_repo, whitelist_mode=False)


@pytest.fixture
def acl_whitelist_mode(acl_repo):
    return ACLManager(acl_repo, whitelist_mode=True)


@pytest.mark.asyncio
async def test_open_mode_allows_unknown_user(acl):
    result = await acl.check("U_UNKNOWN")
    assert result.allowed


@pytest.mark.asyncio
async def test_blacklisted_user_denied(acl):
    await acl.add_to_blacklist("U_BAD")
    result = await acl.check("U_BAD")
    assert not result.allowed
    assert result.decision == ACLDecision.DENY_BLACKLIST


@pytest.mark.asyncio
async def test_whitelist_mode_denies_unknown(acl_whitelist_mode):
    result = await acl_whitelist_mode.check("U_UNKNOWN")
    assert not result.allowed
    assert result.decision == ACLDecision.DENY_NOT_WHITELISTED


@pytest.mark.asyncio
async def test_whitelist_mode_allows_whitelisted(acl_whitelist_mode):
    await acl_whitelist_mode.add_to_whitelist("U_GOOD")
    result = await acl_whitelist_mode.check("U_GOOD")
    assert result.allowed


@pytest.mark.asyncio
async def test_bot_denied_by_default(acl):
    result = await acl.check("B_BOT123", is_bot=True)
    assert not result.allowed
    assert result.decision == ACLDecision.DENY_BOT


@pytest.mark.asyncio
async def test_bot_allowed_when_whitelisted(acl):
    await acl.add_to_whitelist("B_BOT123")
    result = await acl.check("B_BOT123", is_bot=True)
    assert result.allowed


@pytest.mark.asyncio
async def test_seed_from_config(acl):
    await acl.seed_from_config(
        whitelist=["U_ALICE", "U_BOB"],
        blacklist=["U_EVIL"],
    )
    # Seeded entries should be respected (open mode: whitelist just adds entries)
    bad = await acl.check("U_EVIL")
    assert not bad.allowed


@pytest.mark.asyncio
async def test_blacklist_overrides_whitelist(acl):
    """Blacklist takes precedence even if user is also whitelisted."""
    await acl.add_to_whitelist("U_BOTH")
    await acl.add_to_blacklist("U_BOTH")
    result = await acl.check("U_BOTH")
    assert not result.allowed
    assert result.decision == ACLDecision.DENY_BLACKLIST
