"""ID generation utilities."""

import uuid


def new_id() -> str:
    """Generate a new UUID v4 string."""
    return str(uuid.uuid4())
