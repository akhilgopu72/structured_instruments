"""Accounts API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_current_user
from structured_instruments.models.account import Account
from structured_instruments.models.user import User
from structured_instruments.schemas.account import AccountCreate, AccountInfo

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("/", response_model=list[AccountInfo])
def list_accounts(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[AccountInfo]:
    """List accounts for the current user."""
    stmt = (
        select(Account)
        .where(Account.user_id == user.id)
        .order_by(Account.id)
    )
    accounts = list(session.execute(stmt).scalars().all())
    return [
        AccountInfo(id=a.id, name=a.name, account_type=a.account_type)
        for a in accounts
    ]


@router.post("/", response_model=AccountInfo, status_code=201)
def create_account(
    body: AccountCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> AccountInfo:
    """Create a new account for the current user."""
    # Check uniqueness
    existing = session.execute(
        select(Account).where(
            Account.user_id == user.id,
            Account.name == body.name,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Account '{body.name}' already exists for this user",
        )

    account = Account(
        user_id=user.id,
        name=body.name,
        account_type=body.account_type.value,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return AccountInfo(id=account.id, name=account.name, account_type=account.account_type)
