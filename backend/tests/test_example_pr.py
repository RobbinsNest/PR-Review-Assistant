"""Tests for the pinned example PR (T17).

The example PR is a stable public fixture (RobbinsNest/PR-Review-Assistant#1)
backing the SPA quick-start button and offline integration tests.  This
module asserts:

- ``config.example_pr`` is a valid ``owner/repo/pull/N`` reference;
- the recorded GitHub fixture for that PR exists and is self-consistent
  (PR metadata, changed files and head contents for every file).
"""

import json
import re
from pathlib import Path

from app.core.config import Settings
from app.services.github_fetcher import parse_pr_url

#: ``owner/repo/pull/N`` - same shape accepted by :func:`parse_pr_url`.
EXAMPLE_PR_FORMAT = re.compile(r"^[^/\s]+/[^/\s]+/pull/[0-9]+$")

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "example_pr.json"


def test_example_pr_format_is_owner_repo_pull_n():
    """config.example_pr must be a legal ``owner/repo/pull/N`` string."""
    assert EXAMPLE_PR_FORMAT.fullmatch(Settings().example_pr)


def test_example_pr_is_parseable_as_pr_url():
    """The example PR reference must parse through the real PR URL parser."""
    owner, repo, number = parse_pr_url(Settings().example_pr)
    assert owner and repo and number > 0


def test_example_pr_fixture_recorded_and_consistent():
    """The recorded GitHub fixture matches the configured example PR.

    Every changed file must either carry recorded head contents (base64) or
    be a deletion (contents endpoint 404 -> null), so the fixture can replay
    the whole fetch pipeline offline.
    """
    owner, repo, number = parse_pr_url(Settings().example_pr)
    assert FIXTURE_PATH.is_file(), f"recorded GitHub fixture missing: {FIXTURE_PATH}"
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    source = fixture["source"]
    assert (source["owner"], source["repo"], source["number"]) == (owner, repo, number)
    assert fixture["pr"]["number"] == number
    assert fixture["pr"]["base"]["sha"] and fixture["pr"]["head"]["sha"]

    files = fixture["files"]
    assert files, "fixture must record at least one changed file"
    for item in files:
        path = item["filename"]
        if item.get("status") == "removed":
            assert fixture["contents"].get(path) is None, f"{path}: deletion must have no contents"
        else:
            entry = fixture["contents"].get(path)
            assert entry and entry.get("encoding") == "base64", f"{path}: head contents missing"
            assert isinstance(entry.get("content"), str)

