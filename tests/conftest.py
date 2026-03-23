"""Shared fixtures for all tests."""

import pytest
import duckdb

from sai.db.connection import connection_manager
from sai.db.schema import init_schema
from sai.db.repositories import (
    MemoryRepository, EmbeddingRepository,
    UserRepository, ChannelRepository,
    ACLRepository, RateLimitRepository, CommandLogRepository,
)


@pytest.fixture(autouse=True)
def reset_db():
    """
    Before each test: create a fresh in-memory DuckDB connection.
    After each test: close it so the next test starts clean.
    """
    # Override the singleton with an in-memory connection
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL vss;")
    conn.execute("LOAD vss;")
    connection_manager._conn = conn
    init_schema()
    yield
    conn.close()
    connection_manager._conn = None


@pytest.fixture
def memory_repo():
    return MemoryRepository()


@pytest.fixture
def embedding_repo():
    return EmbeddingRepository()


@pytest.fixture
def user_repo():
    return UserRepository()


@pytest.fixture
def channel_repo():
    return ChannelRepository()


@pytest.fixture
def acl_repo():
    return ACLRepository()


@pytest.fixture
def rate_limit_repo():
    return RateLimitRepository()


@pytest.fixture
def cmd_log_repo():
    return CommandLogRepository()
