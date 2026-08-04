"""PR-related data models: repository info, changed files, and review context."""

from pydantic import BaseModel


class PRInfo(BaseModel):
    """Static metadata about the pull request under review."""

    owner: str
    repo: str
    number: int
    title: str
    html_url: str
    base_sha: str
    head_sha: str


class ChangedFile(BaseModel):
    """A single file changed by the pull request."""

    path: str
    status: str
    additions: int
    deletions: int
    diff: str
    head_content: str | None = None
    base_content: str | None = None


class PRContext(BaseModel):
    """The full context handed to the analysis pipeline."""

    info: PRInfo
    files: list[ChangedFile]
