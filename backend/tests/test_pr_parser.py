import pytest
from app.services.github_fetcher import parse_pr_url
from app.core.errors import AppError

def test_parse_full_url():
    assert parse_pr_url("https://github.com/o/r/pull/42") == ("o", "r", 42)

def test_parse_short_form():
    assert parse_pr_url("o/r/pull/7") == ("o", "r", 7)

def test_parse_invalid():
    with pytest.raises(AppError):
        parse_pr_url("https://example.com/foo")

@pytest.mark.parametrize("bad", [
    "https://github.com/o/r/issue/1",
    "https://github.com/o/r/pull/abc",
    "o/r/pull/1/extra",
    "github.com/o/r/pull/1",
    "https://github.com/o/r/pull/1?foo=bar",
    "",
])
def test_parse_malformed(bad):
    with pytest.raises(AppError):
        parse_pr_url(bad)