"""How an account maps onto the owner id that scopes every owned row."""

import uuid

USER_OWNER_PREFIX = "user:"


def owner_id_for(user_id: uuid.UUID) -> str:
    return f"{USER_OWNER_PREFIX}{user_id}"


def user_id_of(owner_id: str) -> uuid.UUID | None:
    """The account behind an owner id, or None for API-key, provider and development owners."""
    if not owner_id.startswith(USER_OWNER_PREFIX):
        return None
    try:
        return uuid.UUID(owner_id.removeprefix(USER_OWNER_PREFIX))
    except ValueError:
        return None
