"""Application error types and stable HTTP status mapping."""

from enum import Enum


class ErrorCode(str, Enum):
    """Stable machine-readable error codes used across the backend."""

    INVALID_URL = "invalid_url"
    REPO_NOT_FOUND = "repo_not_found"
    PULL_NOT_FOUND = "pull_not_found"
    PRIVATE_REPO_REQUIRES_TOKEN = "private_repo_requires_token"
    GITHUB_RATE_LIMITED = "github_rate_limited"
    GITHUB_API_ERROR = "github_api_error"
    LLM_TIMEOUT = "llm_timeout"
    LLM_JSON_PARSE_FAILED = "llm_json_parse_failed"
    LLM_API_ERROR = "llm_api_error"
    TASK_CANCELLED = "task_cancelled"
    ANALYSIS_TOO_LARGE = "analysis_too_large"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"


#: HTTP status per error code; any unlisted code falls back to 400.
ERROR_HTTP: dict[str, int] = {
    ErrorCode.INVALID_URL.value: 400,
    ErrorCode.REPO_NOT_FOUND.value: 404,
    ErrorCode.PULL_NOT_FOUND.value: 404,
    ErrorCode.PRIVATE_REPO_REQUIRES_TOKEN.value: 400,
    ErrorCode.GITHUB_RATE_LIMITED.value: 429,
    ErrorCode.GITHUB_API_ERROR.value: 502,
    ErrorCode.LLM_TIMEOUT.value: 504,
    ErrorCode.LLM_JSON_PARSE_FAILED.value: 400,
    ErrorCode.LLM_API_ERROR.value: 502,
    ErrorCode.TASK_CANCELLED.value: 400,
    ErrorCode.ANALYSIS_TOO_LARGE.value: 413,
    ErrorCode.NOT_FOUND.value: 404,
    ErrorCode.RATE_LIMITED.value: 429,
}

DEFAULT_ERROR_HTTP = 400


class AppError(Exception):
    """Base application error carrying a machine-readable ``code``."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message or code
        self.status_code = (
            status_code if status_code is not None else ERROR_HTTP.get(code, DEFAULT_ERROR_HTTP)
        )
        super().__init__(self.message)
