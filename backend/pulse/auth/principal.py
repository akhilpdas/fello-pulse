"""Who is making this request. Built only from a verified session -- never from anything the caller asserts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str  # "csm" | "operator"

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"
