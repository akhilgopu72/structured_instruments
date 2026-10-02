from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.user import User


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    x_user_id: Annotated[int | None, Header()] = None,
    session: Session = Depends(get_db),
) -> User:
    if x_user_id is None:
        raise HTTPException(status_code=400, detail="X-User-Id header is required")
    user = session.execute(
        select(User).where(User.id == x_user_id)
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail=f"User with id {x_user_id} not found")
    return user


def get_account_filter(
    x_account_ids: Annotated[str | None, Header()] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[int]:
    """Parse X-Account-Ids header and return validated account IDs for the current user."""
    # Get all account IDs belonging to this user
    user_account_ids = {
        row[0]
        for row in session.execute(
            select(Account.id).where(Account.user_id == user.id)
        ).all()
    }

    if x_account_ids is None:
        # No header sent — return all user's accounts
        return list(user_account_ids)

    if not x_account_ids.strip():
        # Header sent but empty — explicitly no accounts selected
        return []

    # Parse comma-separated IDs
    try:
        requested_ids = [int(x.strip()) for x in x_account_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Account-Ids must be comma-separated integers")

    # Validate all requested IDs belong to the user
    invalid = set(requested_ids) - user_account_ids
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Account IDs {sorted(invalid)} do not belong to the current user",
        )

    return requested_ids
