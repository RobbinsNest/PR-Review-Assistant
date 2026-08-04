"""Tests for T4 context builder: hunk range parsing, enclosing function windows, and unit building."""
from app.models.pr import ChangedFile
from app.services.context_builder import (
    build_analysis_unit,
    estimate_tokens,
    extract_hunk_ranges,
    find_enclosing_function,
)


def test_extract_hunk_ranges():
    diff = "@@ -1,5 +1,6 @@\n a\n-b\n+c\n d\n@@ -20,3 +20,4 @@\n x\n+y\n"
    assert extract_hunk_ranges(diff) == [(1, 6), (20, 23)]


def test_extract_hunk_ranges_single_line_hunk():
    # No count field on the new side means a single changed line.
    assert extract_hunk_ranges("@@ -5 +7 @@\n-x\n+y\n") == [(7, 7)]


def test_extract_hunk_ranges_pure_deletion_anchors_first_line():
    # A pure-deletion hunk has no new-file lines; the range anchors at line 1.
    assert extract_hunk_ranges("@@ -1,3 +0,0 @@\n-x\n-y\n-z\n") == [(1, 1)]


PY = "def foo():\n    x = 1\n    if x:\n        return 2\n    return 3\n\ndef bar():\n    return 4\n"


def test_find_enclosing_function():
    start, end = find_enclosing_function(PY, 3, "python")
    assert start == 1 and end == 5


def test_find_enclosing_function_fallback():
    assert find_enclosing_function("no function here\n", 1, "python") == (1, 1)


def test_find_enclosing_function_unknown_language_fallback_window():
    content = "\n".join(f"line{i}" for i in range(1, 101))
    start, end = find_enclosing_function(content, 50, "unknown")
    assert start == 30 and end == 70


def test_find_enclosing_function_brace_language():
    js = (
        "function foo() {\n"
        "  const x = 1;\n"
        "  if (x) {\n"
        "    return 2;\n"
        "  }\n"
        "  return 3;\n"
        "}\n"
        "\n"
        "function bar() {\n"
        "  return 4;\n"
        "}\n"
    )
    start, end = find_enclosing_function(js, 4, "javascript")
    assert start == 1 and end == 7


def test_find_enclosing_function_go_func():
    go = (
        "package main\n"
        "\n"
        "func foo(a int) int {\n"
        "    x := a + 1\n"
        "    return x\n"
        "}\n"
        "\n"
        "func bar() int {\n"
        "    return 2\n"
        "}\n"
    )
    start, end = find_enclosing_function(go, 5, "go")
    assert start == 3 and end == 6


def test_find_enclosing_function_rust_fn():
    rust = (
        "fn foo(a: i32) -> i32 {\n"
        "    let x = a + 1;\n"
        "    x\n"
        "}\n"
        "\n"
        "fn bar() -> i32 {\n"
        "    2\n"
        "}\n"
    )
    start, end = find_enclosing_function(rust, 3, "rust")
    assert start == 1 and end == 4


def test_find_enclosing_function_multiline_signature():
    content = "def foo(\n    a,\n    b\n):\n    return a + b\n"
    start, end = find_enclosing_function(content, 5, "python")
    assert start == 1 and end == 5


def test_find_enclosing_function_multiline_signature_stops_before_next():
    content = (
        "def foo(\n"
        "    a,\n"
        "    b\n"
        "):\n"
        "    x = a + b\n"
        "    return x\n"
        "\n"
        "def bar():\n"
        "    return 1\n"
    )
    start, end = find_enclosing_function(content, 6, "python")
    assert start == 1 and end == 6


def test_find_enclosing_function_single_line_suite_does_not_swallow_next():
    # `def foo(): return 1` is a single-line suite: the header ends at the def
    # line, so the enclosing window must NOT extend into the next def.
    content = "def foo(): return 1\n\ndef bar():\n    return 2\n"
    start, end = find_enclosing_function(content, 1, "python")
    assert start == 1 and end == 1


def test_find_enclosing_function_single_line_suite_next_def_still_found():
    content = "def foo(): return 1\n\ndef bar():\n    return 2\n"
    start, end = find_enclosing_function(content, 3, "python")
    assert start == 3 and end == 4


def test_find_enclosing_function_class_single_line_suite():
    content = "class A: pass\n\nclass B:\n    pass\n"
    start, end = find_enclosing_function(content, 1, "python")
    assert start == 1 and end == 1


def test_estimate_tokens():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0


def test_build_analysis_unit_includes_context():
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff="@@ -1,3 +1,3 @@\n def foo():\n-    x = 1\n+    x = 2", head_content=PY)
    unit = build_analysis_unit(f)[0]
    assert "def foo" in unit["context"]
    assert unit["file_path"] == "a.py"


def test_build_analysis_unit_single_within_budget():
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff="@@ -1,3 +1,3 @@\n def foo():\n-    x = 1\n+    x = 2", head_content=PY)
    units = build_analysis_unit(f, budget_in=8000)
    assert len(units) == 1
    assert units[0]["truncated"] is False
    assert units[0]["diff"].startswith("@@")


def test_build_analysis_unit_deleted_file_no_crash():
    f = ChangedFile(path="old.py", status="deleted", additions=0, deletions=3,
                    diff="--- a/old.py\n+++ b/old.py\n@@ -1,3 +0,0 @@\n-x\n-y\n-z\n",
                    head_content=None)
    units = build_analysis_unit(f)
    assert len(units) == 1
    assert units[0]["context"] == ""
    assert units[0]["truncated"] is False


def test_build_analysis_unit_splits_when_over_budget():
    # Four 3-line functions back to back: f1=1-3, f2=4-6, f3=7-9, f4=10-12.
    content = "".join(
        f"def f{i}():\n    a = {i}\n    return {i}\n" for i in range(1, 5)
    )
    diff = "\n".join(
        f"@@ -{start},3 +{start},3 @@\n def f{i}():\n-    a = {i}\n+    a = {i}0\n"
        for i, start in zip(range(1, 5), range(1, 13, 3))
    )
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff=diff, head_content=content)
    units = build_analysis_unit(f, budget_in=10)
    assert len(units) > 1
    assert all(u["truncated"] for u in units)
    assert all(set(u) == {"file_path", "diff", "context", "truncated"} for u in units)
    # The union of all chunk contexts still covers every changed function.
    combined_context = "\n".join(u["context"] for u in units)
    for i in range(1, 5):
        assert f"def f{i}" in combined_context


def test_build_analysis_unit_trims_oversized_function_window():
    # A small hunk deep inside a 10k-line function must not emit the entire
    # function window (which would blow the token budget). The window is
    # trimmed to the function signature plus the hunk neighborhood so every
    # returned unit stays within budget_in.
    lines = ["def huge():"] + [f"    x = {i}" for i in range(1, 10000)]
    content = "\n".join(lines)
    diff = (
        "@@ -4999,3 +5000,3 @@\n"
        "     x = 4999\n"
        "-    x = 5000\n"
        "+    x = 5000\n"
    )
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff=diff, head_content=content)
    budget_in = 2000
    units = build_analysis_unit(f, budget_in=budget_in)
    assert len(units) == 1
    unit = units[0]
    assert unit["truncated"] is True
    assert estimate_tokens(unit["context"]) <= budget_in
    assert estimate_tokens(unit["context"]) + estimate_tokens(unit["diff"]) <= budget_in
    # The signature and the hunk neighborhood survive the trim.
    assert "def huge" in unit["context"]
    assert "5000:" in unit["context"]
    assert "9999:" not in unit["context"]
