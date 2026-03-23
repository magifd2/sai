"""Tests for rate limiter."""

import pytest
from sai.security.ddos import RateLimiter


@pytest.fixture
def limiter(rate_limit_repo):
    return RateLimiter(rate_limit_repo, limit_per_minute=3, limit_per_hour=10)


@pytest.mark.asyncio
async def test_allows_within_limit(limiter):
    for _ in range(3):
        result = await limiter.check_and_increment("U123")
        assert result.allowed


@pytest.mark.asyncio
async def test_blocks_over_minute_limit(limiter):
    for _ in range(3):
        await limiter.check_and_increment("U123")
    result = await limiter.check_and_increment("U123")
    assert not result.allowed


@pytest.mark.asyncio
async def test_different_users_independent(limiter):
    for _ in range(3):
        await limiter.check_and_increment("U_ALICE")
    # Bob should still be allowed
    result = await limiter.check_and_increment("U_BOB")
    assert result.allowed
