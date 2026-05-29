from typing import Any, Literal

from pydantic import BaseModel, Field


class ShareCreate(BaseModel):
    target_user_id: int
    permission: Literal["view", "edit"]


class SectionPatch(BaseModel):
    content: Any


class AIRewriteRequest(BaseModel):
    instruction: str = Field(min_length=1)

