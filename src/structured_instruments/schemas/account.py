"""Account schemas."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AccountTypeEnum(str, Enum):
    personal = "personal"
    roth_ira = "roth_ira"
    traditional_ira = "traditional_ira"
    four01k = "401k"


class AccountInfo(BaseModel):
    id: int
    name: str
    account_type: str


class AccountCreate(BaseModel):
    name: str
    account_type: AccountTypeEnum
