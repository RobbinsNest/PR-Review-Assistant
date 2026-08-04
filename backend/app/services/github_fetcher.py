"""GitHub REST client: PR URL parsing and PR context fetching."""

import asyncio
import base64
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.pr import ChangedFile, PRContext, PRInfo

API_BASE = "https://api.github.com"
ACCEPT_HEADER = "application/vnd.github+json"
PER_PAGE = 100
#: Head content larger than this is not embedded (set to None).
MAX_CONTENT_BYTES = 1024 * 1024
#: Exponential backoff (seconds) between timeout retries.
RETRY_BACKOFF = (0.5, 1.0)

#: ``https://github.com/{owner}/{repo}/pull/{number}`` or ``{owner}/{repo}/pull/{number}``.
PR_URL_RE = re.compile(
    r"^(?:https://github\.com/)?(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>[0-9]+)$"
)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse a GitHub PR URL into ``(owner, repo, number)``.

    Accepts ``https://github.com/{owner}/{repo}/pull/{number}`` and the short
    form ``{owner}/{repo}/pull/{number}``.  Anything else raises
    ``AppError("invalid_url")``.
    """
    match = PR_URL_RE.fullmatch(url)
    if match is None:
        raise AppError("invalid_url", message=f"invalid GitHub PR URL: {url!r}")
    return match.group("owner"), match.group("repo"), int(match.group("number"))


class GitHubFetcher:
    """Async GitHub REST client used by the analysis pipeline.

    Public-repo reads work without a token.  A token is kept only in memory
    (never logged or persisted) and adds ``Authorization: Bearer <token>``.
    Requests time out after ``timeout`` seconds and are retried twice with
    exponential backoff (0.5s, then 1.0s) on network timeouts.
    """

    def __init__(self, token: str | None = None, timeout: float = 15.0) -> None:
        headers = {"Accept": ACCEPT_HEADER}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._headers = headers
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def fetch_pr(self, owner: str, repo: str, number: int) -> PRInfo:
        """Fetch PR metadata and return it as ``PRInfo``."""
        url = f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}"
        data = await self._get_json(url)
        return PRInfo(
            owner=owner,
            repo=repo,
            number=number,
            title=data["title"],
            html_url=data["html_url"],
            base_sha=data["base"]["sha"],
            head_sha=data["head"]["sha"],
        )

    async def fetch_changed_files(
        self, owner: str, repo: str, number: int
    ) -> list[ChangedFile]:
        """Fetch all changed files (paginated, ``per_page=100``) with head content.

        Head content is read from the PR head commit via the contents API;
        binary files and files over 1 MiB yield ``head_content=None``.
        """
        # The files endpoint does not carry the head SHA, so it is resolved
        # through the PR metadata first.
        head_sha = (await self.fetch_pr(owner, repo, number)).head_sha
        files: list[ChangedFile] = []
        page = 1
        while True:
            url = (
                f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}/files"
                f"?per_page={PER_PAGE}&page={page}"
            )
            batch = await self._get_json(url)
            if not batch:
                break
            for item in batch:
                files.append(
                    await self._changed_file_from_item(owner, repo, item, head_sha)
                )
            if len(batch) < PER_PAGE:
                break
            page += 1
        return files

    async def fetch_context(
        self, owner: str, repo: str, number: int
    ) -> PRContext:
        """Combine PR metadata and changed files into a ``PRContext``.

        Raises ``AppError("analysis_too_large")`` when the PR exceeds the
        configured ``max_files`` / ``max_diff_bytes`` limits.
        """
        info = await self.fetch_pr(owner, repo, number)
        files = await self.fetch_changed_files(owner, repo, number)
        settings = get_settings()
        total_diff_bytes = sum(len(f.diff.encode("utf-8")) for f in files)
        if len(files) > settings.max_files or total_diff_bytes > settings.max_diff_bytes:
            raise AppError(
                "analysis_too_large",
                message=(
                    f"PR too large: {len(files)} files, {total_diff_bytes} diff bytes "
                    f"(limit {settings.max_files} files / {settings.max_diff_bytes} bytes)"
                ),
            )
        return PRContext(info=info, files=files)

    # -- internals ---------------------------------------------------------

    async def _get_json(self, url: str) -> Any:
        response = await self._get(url)
        self._raise_for_status(response, url)
        return response.json()

    async def _get(self, url: str) -> httpx.Response:
        """GET ``url``; retry twice (0.5s / 1.0s) on network/transport errors.

        Both timeouts (``httpx.TimeoutException``) and other transport errors
        such as ``httpx.ConnectError`` (DNS/network down) are retried, and
        surface as ``AppError("github_api_error")`` once retries are exhausted
        instead of leaking as raw 500s.
        """
        attempts = len(RETRY_BACKOFF) + 1  # initial attempt + 2 retries
        last_error: httpx.TransportError | None = None
        for attempt in range(attempts):
            try:
                return await self._get_client().get(url)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < len(RETRY_BACKOFF):
                    await asyncio.sleep(RETRY_BACKOFF[attempt])
        raise AppError(
            "github_api_error",
            message=(
                f"GitHub API request failed (network error) after "
                f"{attempts} attempts: {url}"
            ),
        ) from last_error

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared ``AsyncClient``, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._headers, timeout=self._timeout
            )
        return self._client

    async def aclose(self) -> None:
        """Close the shared AsyncClient, releasing its connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _raise_for_status(self, response: httpx.Response, url: str) -> None:
        if response.is_success:
            return
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("message") if isinstance(body, dict) else ""
        if status == 404:
            # Private repos also surface as 404 without a token; the fetcher
            # cannot tell the two apart and reports repo_not_found.
            raise AppError("repo_not_found", message=f"GitHub repo/PR not found: {url}")
        if status == 429 or (status == 403 and "rate limit" in str(message).lower()):
            raise AppError(
                "github_rate_limited",
                message=f"GitHub API rate limit exceeded: {url}",
            )
        hint = " (check token permissions)" if status == 403 else ""
        raise AppError(
            "github_api_error",
            message=f"GitHub API error {status}: {url}{hint}",
        )

    async def _changed_file_from_item(
        self, owner: str, repo: str, item: dict, head_sha: str
    ) -> ChangedFile:
        path = item["filename"]
        head_content = await self._fetch_head_content(owner, repo, path, head_sha)
        return ChangedFile(
            path=path,
            status=item.get("status") or "",
            additions=item.get("additions", 0),
            deletions=item.get("deletions", 0),
            diff=item.get("patch") or "",
            head_content=head_content,
        )

    async def _fetch_head_content(
        self, owner: str, repo: str, path: str, ref: str
    ) -> str | None:
        """Return the file text at ``ref``, or ``None`` for missing/binary/1MiB+ files."""
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}?ref={ref}"
        response = await self._get(url)
        if response.status_code == 404:
            # File no longer present at HEAD (e.g. deleted in this PR).
            return None
        self._raise_for_status(response, url)
        data = response.json()
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        size = data.get("size") or 0
        if size > MAX_CONTENT_BYTES:
            return None
        try:
            raw = base64.b64decode(data.get("content") or "")
        except (ValueError, TypeError):
            return None
        if len(raw) > MAX_CONTENT_BYTES:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            # Binary content (images, archives, ...) - no head text to embed.
            return None