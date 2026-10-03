"""Bounded requests for explicit speech connection changes."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConnectionDefaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    expected_default_revision: int = Field(ge=0, strict=True)


class ConnectionDeletionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["replace", "detach"]
    replacement_ref: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def explicit_choice(self):
        if (self.action == "replace") != bool(self.replacement_ref):
            raise ValueError("replace requires replacement_ref; detach must not include it")
        return self
