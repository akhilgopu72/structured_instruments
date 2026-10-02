"""Users API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db
from structured_instruments.models.user import User

router = APIRouter(prefix="/api/users", tags=["users"])


class UserOut(BaseModel):
    id: int
    name: str


class UserCreate(BaseModel):
    name: str


@router.get("/", response_model=list[UserOut])
def list_users(session: Session = Depends(get_db)) -> list[UserOut]:
    """List all users."""
    stmt = select(User).order_by(User.id)
    users = list(session.execute(stmt).scalars().all())
    return [UserOut(id=u.id, name=u.name) for u in users]


@router.post("/", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, session: Session = Depends(get_db)) -> UserOut:
    """Create a new user."""
    existing = session.execute(
        select(User).where(User.name == body.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"User '{body.name}' already exists")

    user = User(name=body.name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserOut(id=user.id, name=user.name)
