"""Finding data models: enums, candidates, and verified findings."""

import uuid
from enum import Enum

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class Category(str, Enum):
    """Fixed set of review categories."""

    bug = "bug"
    security = "security"
    performance = "performance"
    maintainability = "maintainability"
    style = "style"


class Severity(str, Enum):
    """Fixed set of severity levels."""

    critical = "critical"
    major = "major"
    minor = "minor"
    nit = "nit"


class FindingCandidate(BaseModel):
    """A raw finding produced by the LLM before verification."""

    file_path: str
    line_start: int
    line_end: int
    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    description: str
    evidence: str
    suggestion: str

    @field_validator("line_end")
    @classmethod
    def line_end_must_not_precede_line_start(
        cls, value: int, info: ValidationInfo
    ) -> int:
        """Guarantee the finding range never runs backwards."""
        line_start = info.data.get("line_start")
        if line_start is not None and value < line_start:
            raise ValueError("line_end must be >= line_start")
        return value


class Finding(FindingCandidate):
    """A verified finding with a stable identifier."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    verified: bool = True
