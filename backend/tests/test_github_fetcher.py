import base64

import httpx
import pytest
import respx

from app.core.errors import AppError
from app.services.github_fetcher import GitHubFetcher

PR_PAYLOAD = {
    "number": 1,
    "title": "Fix bug",
    "html_url": "https://github.com/o/r/pull/1",
    "base": {"sha": "abc"},
    "head": {"sha": "def"},
}


def _file_item(path, patch="@@ -1 +1 @@\n-x\n+y\n", status="modified",
               additions=1, deletions=1):
    return {
        "filename": path,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "patch": patch,
    }


@respx.mock
async def test_fetch_pr_metadata():
    route = respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    f = GitHubFetcher()
    info = await f.fetch_pr("o", "r", 1)
    assert info.owner == "o" and info.number == 1 and info.base_sha == "abc"


@respx.mock
async def test_fetch_pr_not_found():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    with pytest.raises(AppError):
        await f.fetch_pr("o", "r", 1)


@respx.mock
async def test_private_repo_requires_token():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "repo_not_found"


@respx.mock
async def test_unauth_rate_limit_message():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(403, json={"message": "API rate limit exceeded"}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_rate_limited"


@respx.mock
async def test_fetch_pr_sends_token_and_accept_headers():
    route = respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    f = GitHubFetcher(token="ghp_secret")
    await f.fetch_pr("o", "r", 1)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer ghp_secret"
    assert request.headers["Accept"] == "application/vnd.github+json"


@respx.mock
async def test_rate_limited_429():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(429, json={"message": "API rate limit exceeded"}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_rate_limited"


@respx.mock
async def test_forbidden_without_rate_limit_is_api_error():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(403, json={"message": "Resource not accessible by personal access token"}))
    f = GitHubFetcher(token="ghp_secret")
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_api_error"


@respx.mock
async def test_server_error_is_api_error():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(500, json={}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_api_error"


@respx.mock
async def test_timeout_retries_then_succeeds():
    route = respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        side_effect=[httpx.ReadTimeout("boom"), httpx.Response(200, json=PR_PAYLOAD)])
    f = GitHubFetcher()
    info = await f.fetch_pr("o", "r", 1)
    assert info.number == 1
    assert route.call_count == 2


@respx.mock
async def test_timeout_retries_exhausted_raises_api_error():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        side_effect=httpx.ReadTimeout("boom"))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_api_error"


@respx.mock
async def test_fetch_changed_files_paginates():
    page1 = [_file_item(f"file_{i}.py") for i in range(100)]
    page2 = [_file_item("file_100.py")]
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    route1 = respx.get("https://api.github.com/repos/o/r/pulls/1/files",
                       params={"per_page": 100, "page": 1}).mock(
        return_value=httpx.Response(200, json=page1))
    route2 = respx.get("https://api.github.com/repos/o/r/pulls/1/files",
                       params={"per_page": 100, "page": 2}).mock(
        return_value=httpx.Response(200, json=page2))
    respx.get(url__regex=r"https://api\.github\.com/repos/o/r/contents/.+").mock(
        return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    files = await f.fetch_changed_files("o", "r", 1)
    assert len(files) == 101
    assert files[0].path == "file_0.py" and files[100].path == "file_100.py"
    assert route1.called and route2.called


@respx.mock
async def test_fetch_changed_files_decodes_head_content_and_null_patch():
    payload = "def foo():\n    return 1\n"
    encoded = base64.b64encode(payload.encode()).decode()
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("a.py", patch=None)]))
    respx.get("https://api.github.com/repos/o/r/contents/a.py",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(200, json={
            "type": "file", "encoding": "base64", "size": len(payload),
            "content": encoded}))
    f = GitHubFetcher()
    files = await f.fetch_changed_files("o", "r", 1)
    assert files[0].diff == ""
    assert files[0].head_content == payload


@respx.mock
async def test_head_content_over_1mb_is_none():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("big.bin")]))
    respx.get("https://api.github.com/repos/o/r/contents/big.bin",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(200, json={
            "type": "file", "encoding": "base64",
            "size": 1024 * 1024 + 1,
            "content": base64.b64encode(b"x" * 10).decode()}))
    f = GitHubFetcher()
    files = await f.fetch_changed_files("o", "r", 1)
    assert files[0].head_content is None


@respx.mock
async def test_head_content_binary_is_none():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("blob.dat")]))
    respx.get("https://api.github.com/repos/o/r/contents/blob.dat",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(200, json={
            "type": "file", "encoding": "base64", "size": 6,
            "content": base64.b64encode(b"\xff\xfe\x00binary").decode()}))
    f = GitHubFetcher()
    files = await f.fetch_changed_files("o", "r", 1)
    assert files[0].head_content is None


@respx.mock
async def test_head_content_deleted_file_is_none():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("gone.py")]))
    respx.get("https://api.github.com/repos/o/r/contents/gone.py",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    files = await f.fetch_changed_files("o", "r", 1)
    assert files[0].head_content is None


@respx.mock
async def test_fetch_context_combines_pr_and_files():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("a.py")]))
    respx.get("https://api.github.com/repos/o/r/contents/a.py",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    ctx = await f.fetch_context("o", "r", 1)
    assert ctx.info.number == 1 and ctx.info.head_sha == "def"
    assert ctx.files[0].path == "a.py"


@respx.mock
async def test_fetch_context_too_many_files(monkeypatch):
    monkeypatch.setenv("MAX_FILES", "2")
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item(f"f{i}.py") for i in range(3)]))
    respx.get(url__regex=r"https://api\.github\.com/repos/o/r/contents/.+").mock(
        return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_context("o", "r", 1)
    assert ei.value.code == "analysis_too_large"


@respx.mock
async def test_fetch_context_diff_too_large(monkeypatch):
    monkeypatch.setenv("MAX_DIFF_BYTES", "10")
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json=PR_PAYLOAD))
    respx.get("https://api.github.com/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(200, json=[_file_item("a.py")]))
    respx.get("https://api.github.com/repos/o/r/contents/a.py",
              params={"ref": "def"}).mock(
        return_value=httpx.Response(404, json={}))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_context("o", "r", 1)
    assert ei.value.code == "analysis_too_large"


@respx.mock
async def test_connect_error_retries_then_succeeds():
    route = respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=PR_PAYLOAD)])
    f = GitHubFetcher()
    info = await f.fetch_pr("o", "r", 1)
    assert info.number == 1
    assert route.call_count == 2


@respx.mock
async def test_connect_error_exhausted_raises_api_error():
    respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        side_effect=httpx.ConnectError("boom"))
    f = GitHubFetcher()
    with pytest.raises(AppError) as ei:
        await f.fetch_pr("o", "r", 1)
    assert ei.value.code == "github_api_error"
