# AI PR 评审助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个以 AI 辅助分析为核心的 GitHub PR 评审工具：用户输入 PR 链接，系统自动获取变更与上下文，产出变更总结、定位到文件行的风险发现（两阶段生成-校验 + 置信度）与 Review 建议，并通过 Web 端（SSE 实时进度 + diff 高亮 + 历史 + 导出）交付，Docker 一键部署。

**Architecture:** 单体 FastAPI（Python 3.11）后端 + React(Vite+TS) 前端 SPA。分析在进程内 asyncio 任务中运行：GitHub 数据获取 → 上下文构建（hunk→函数/类窗口，超大 PR 按文件 map-reduce）→ 文件级并行 LLM 生成候选发现 → 校验（keep/drop/downgrade + 置信度修订）→ 汇总层合并为 PR 级结果。任务状态经 SSE 推送。SQLite 存历史；LLM key 存 keyring（兜底 .env），GitHub token 仅会话内存。

**Tech Stack:** Python 3.11 · FastAPI · httpx · pydantic v2 · aiosqlite · uvicorn · pytest/pytest-asyncio · React 18 + TypeScript + Vite + Tailwind · Docker 多阶段 · GitHub Actions + .gitlab-ci.yml

---

## Global Constraints

- 后端目标 **Python 3.11**：Docker/CI 固定 `python:3.11-slim`；本地开发兼容 3.11+（本机为 3.14），但禁止 3.12+ 专有语法，`pyproject.toml` 用 `requires-python = ">=3.11"`。
- LLM 走 **OpenAI 兼容协议**，`base_url`/`model`/`api_key` 可配；默认 `base_url=https://api.deepseek.com`、`model=deepseek-v4-flash`。LLM 客户端必须封装：超时（默认 60s）、重试（1 次）、JSON 输出经 pydantic 校验、解析失败追加修复提示重试 1 次。
- **凭据铁律**：key/token 绝不硬编码、绝不提交进 git、绝不写日志/终端 history。LLM key 首选 OS keyring（`keyring` 库），`.env`（gitignored）兜底；Web/CLI 只显示掩码（`sk-****1234`）。GitHub token 仅会话内存、请求转发后即弃、不落库。
- 固定枚举：`category ∈ {bug, security, performance, maintainability, style}`；`severity ∈ {critical, major, minor, nit}`；`confidence ∈ [0,1]`。所有 finding 的 `line_start/line_end` 必须落在变更行范围内（校验阶段强制）。
- 分析管线顺序：`fetching → building → analyzing → verifying → aggregating → succeeded/failed/cancelled`；SSE 事件须覆盖这些阶段并带进度（如 3/8 文件）。
- 每文件 token 预算默认 in ~8000 / out ~4000；文件级并行默认并发 **3-5**（信号量）。
- 超大 PR 上限：>50 文件 或 diff 总量 >2MB → 拒绝并给出明确错误（可配）。
- 数据存储：SQLite（`aiosqlite`），表 `analyses` 字段见 SPEC §6；findings 内嵌 JSON，不单独建表；任何表不存 token/key。
- 测试：pytest + pytest-asyncio；**LLM 与 GitHub 全部 mock/stub，确定性**；一键命令 `make test`（Windows 上另提供 `make.bat` 或 pytest 直接可用）。
- CI：GitHub Actions（每次 push 跑测试；含构建镜像 job）+ `.gitlab-ci.yml`（必须含名为 `unit-test` 的 job）。
- 前端：React 18 + TypeScript + Vite + Tailwind；diff 高亮基于 findings 行定位；SSE 用原生 EventSource（断线重连）。
- Open Design：仓库根维护 `DESIGN.md`（design tokens/组件规范），前端按其落地；不引入 Open Design 桌面运行时。
- 示例 PR：实现时钉选一个稳定公开样例（owner/repo/pull 号写入配置），并为测试录制其 GitHub fixture。
- 日志与错误信息不包含任何凭据；`/healthz` 健康检查。
- 端口：后端 8000；Docker 暴露 8000。
- **本机环境（Windows + 沙箱）**：pytest 的 `tmp_path` 默认写系统 TEMP 会被沙箱拒绝；运行测试前在 worktree 内建 `.tmp` 目录并设 `$env:TEMP=$env:TMP=<worktree>\.tmp`（或 pytest `--basetemp`），确保测试临时文件落在工作区内。

---

## Worktree / PR 映射（每个大模块一个 worktree = 一个 PR）

| Worktree | 分支 | PR | 内容（任务） | 依赖 |
|---|---|---|---|---|
| WT-1 | `feat/backend-core` | #1 | T1-T5：脚手架/模型/数据获取/上下文/LLM 客户端 | main |
| WT-2 | `feat/analysis-engine` | #2 | T6-T9：分析引擎/任务管理/analyze+tasks API | #1 |
| WT-3 | `feat/history-settings` | #3 | T10-T13：历史存储/凭据设置/限流/history+settings API | #1 |
| WT-4 | `feat/frontend` | #4 | T14-T16：SPA 全部页面 | #1-#3（API 契约） |
| WT-5 | `feat/deploy-ci` | #5 | T17：Docker/CI/README/.env.example/DESIGN.md/示例 PR 钉选 | #1-#4 |

合并顺序：#1 →（#2 与 #3 可并行）→ #4 → #5。文档类交付物（SPEC.md/PLAN.md/SPEC_PROCESS.md/AGENT_LOG.md/README/REFLECTION）在 main 上持续维护，不进 worktree。

---

## 文件结构（目标）

```
backend/
  app/
    main.py                 # FastAPI 入口：注册路由、CORS、异常处理
    api/
      analyze.py            # POST /api/analyze、GET /api/tasks/{id}、GET /api/tasks/{id}/events(SSE)
      history.py            # GET/POST/DELETE /api/history、GET /api/history/{id}/export
      settings.py           # GET/PUT/DELETE /api/settings/llm、POST /api/settings/llm/test
      health.py             # GET /healthz
    core/
      config.py             # pydantic-settings：base_url/model/并发/预算/上限/示例PR
      logging.py            # 结构化日志（脱敏）
      rate_limit.py         # 内存令牌桶
      errors.py             # 错误枚举 + HTTPException 映射
    models/
      pr.py                 # PRInfo/ChangedFile/PRContext
      finding.py            # Finding/FindingCandidate/Category/Severity
      analysis.py           # AnalysisResult/AnalysisSummary/StageMeta
    services/
      github_fetcher.py     # URL 解析 + GitHub REST 客户端
      context_builder.py    # hunk→函数/类上下文窗口 + 分片
      llm_client.py         # OpenAI 兼容客户端
      analysis_engine.py    # generate/verify/aggregate 编排
      task_manager.py       # asyncio 任务注册表 + 状态机 + SSE
      history_store.py      # SQLite CRUD + Markdown 导出
      credentials.py        # keyring/.env 存取 + 掩码
    cli.py                  # key set/status/clear
  tests/
    conftest.py             # fixtures：mock httpx、假 LLM 响应
    test_pr_parser.py
    test_github_fetcher.py
    test_context_builder.py
    test_llm_client.py
    test_analysis_engine.py
    test_task_manager.py
    test_history_store.py
    test_credentials.py
    test_api.py             # 端到端（LLM/GitHub mock）
  pyproject.toml / requirements.txt / Dockerfile
frontend/
  src/
    api/client.ts, sse.ts
    pages/HomePage.tsx, ProgressPage.tsx, ResultPage.tsx, HistoryPage.tsx, SettingsPage.tsx
    components/FindingsList.tsx, DiffViewer.tsx, SummaryCard.tsx, ...
    app/App.tsx, router.tsx
  package.json, vite.config.ts, tailwind.config.js, index.html
.github/workflows/ci.yml
.gitlab-ci.yml
docker-compose.yml
.env.example
DESIGN.md
Makefile
```

---

---

### Task T1: 后端脚手架 + 配置 + 健康检查

> ✅ **完成** — commit d46a065（2026-08-04，implementer: Parfit；review: Erdos ✅ spec compliant，0 Critical/Important）

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`, `backend/app/main.py`
- Create: `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/app/core/errors.py`
- Create: `backend/app/api/__init__.py`, `backend/app/api/health.py`
- Create: `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`
- Create: `Makefile`（根目录）：`test` 目标 = `cd backend && pytest tests/ -v`；`build` = `docker build -t pr-review-assistant .`；`run` = `docker run -p 8000:8000 --env-file .env -v prra-data:/app/data pr-review-assistant`（本机无 make 时可直接用 pytest 验证）

**Interfaces:**
- Consumes: 无（首个任务）
- Produces:
  - `app.core.config.Settings`（pydantic-settings）：字段 `llm_base_url: str = "https://api.deepseek.com"`、`llm_model: str = "deepseek-v4-flash"`、`llm_api_key_env: str = "LLM_API_KEY"`、`analysis_concurrency: int = 4`、`max_files: int = 50`、`max_diff_bytes: int = 2 * 1024 * 1024`、`file_token_budget_in: int = 8000`、`file_token_budget_out: int = 4000`、`llm_timeout_sec: float = 60.0`、`example_pr: str = "owner/repo/pull/1"`、`database_path: str = "data/analyses.db"`、`rate_limit_per_min: int = 10`；方法 `api_key()`（从 keyring 或 env 读取，见 T11，本任务先返回 env 值）。
  - `app.core.errors.AppError`（异常，含 `code: str`）与 `ERROR_HTTP` 映射（**本任务一次性写全**，供后续所有任务引用）：默认 400；`repo_not_found/pull_not_found`→404；`github_rate_limited`→429；`analysis_too_large`→413；`llm_timeout`→504；`not_found`→404；`rate_limited`→429。错误码枚举一次性包含：`invalid_url/repo_not_found/pull_not_found/private_repo_requires_token/github_rate_limited/llm_timeout/llm_json_parse_failed/task_cancelled/analysis_too_large/not_found/rate_limited`。`app.api.health.router`。

- [ ] **Step 1: 写失败测试 `test_health.py`**

```python
from fastapi.testclient import TestClient

def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 2: 运行确认失败** — `pytest backend/tests/test_health.py -v` 期望：红态即可（`fixture 'client' not found` 或 `ModuleNotFoundError`，取决于 conftest 是否已建）；不要继续实现直到看到失败。
- [ ] **Step 3: 实现脚手架**
  - `pyproject.toml`：`requires-python = ">=3.11"`（Docker/CI 用 3.11 镜像）；依赖 `fastapi`、`uvicorn[standard]`、`httpx`、`pydantic>=2`、`pydantic-settings`、`aiosqlite`、`keyring`；dev 依赖 `pytest`、`pytest-asyncio`、`respx`（不声明 `python-multipart`，本项目无表单上传）。加 `[tool.pytest.ini_options] asyncio_mode = "auto"`（pytest-asyncio 1.x 需要，T3 起大量裸 async 测试）。
  - `core/config.py`：如上 Settings；`get_settings()` 懒加载单例。
  - `core/logging.py`：`logging.basicConfig` 结构化格式（JSON 可选，至少含时间/级别/消息），并加 `redact()` 帮助函数。
  - `core/errors.py`：`AppError` + 错误码枚举（`invalid_url/repo_not_found/pull_not_found/private_repo_requires_token/github_rate_limited/llm_timeout/llm_json_parse_failed/task_cancelled/analysis_too_large`）。
  - `main.py`：创建 `FastAPI(title="PR Review Assistant")`，注册 health router，加 `HTTPException`/`AppError` 异常处理器。
  - `conftest.py`：`TestClient` fixture；`tmp_path` 指向临时数据库；设置环境变量确保测试不碰真实 keyring。
- [ ] **Step 4: 运行确认通过** — `pytest backend/tests/ -v` 期望 PASS。
- [ ] **Step 5: 提交** — `git add backend Makefile && git commit -m "feat(backend): scaffold FastAPI app with config, logging, health check"`

---

### Task T2: 核心数据模型（pydantic schemas）

> ✅ **完成** — commit e303357（2026-08-04，implementer: Sagan；review: Peirce ✅ spec compliant，0 Critical/Important；M5 settings-cache fixture 已顺手合入）

**Files:**
- Create: `backend/app/models/__init__.py`, `backend/app/models/pr.py`, `backend/app/models/finding.py`, `backend/app/models/analysis.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces（后续所有任务依赖的精确类型）：
  - `app.models.pr.PRInfo`：`owner: str, repo: str, number: int, title: str, html_url: str, base_sha: str, head_sha: str`
  - `app.models.pr.ChangedFile`：`path: str, status: str, additions: int, deletions: int, diff: str, head_content: str | None = None, base_content: str | None = None`
  - `app.models.pr.PRContext`：`info: PRInfo, files: list[ChangedFile]`
  - `app.models.finding.Category(str, Enum)`：`bug/security/performance/maintainability/style`
  - `app.models.finding.Severity(str, Enum)`：`critical/major/minor/nit`
  - `app.models.finding.FindingCandidate`：`file_path: str, line_start: int, line_end: int, category: Category, severity: Severity, confidence: float, title: str, description: str, evidence: str, suggestion: str`
  - `app.models.finding.Finding`：继承 candidate 并加 `id: str`（uuid4）、`verified: bool = True`
  - `app.models.analysis.AnalysisSummary`：`title: str, overview: str, key_points: list[str], risk_highlights: list[str]`
  - `app.models.analysis.AnalysisResult`：`summary: AnalysisSummary, findings: list[Finding], meta: dict`

- [ ] **Step 1: 写失败测试 `test_models.py`**

```python
import pytest
from pydantic import ValidationError
from app.models.finding import Category, Severity, FindingCandidate
from app.models.analysis import AnalysisResult

def test_category_enum_values():
    assert {c.value for c in Category} == {"bug", "security", "performance", "maintainability", "style"}

def test_severity_enum_values():
    assert {c.value for c in Severity} == {"critical", "major", "minor", "nit"}

def test_finding_confidence_range():
    with pytest.raises(ValidationError):
        FindingCandidate(file_path="a.py", line_start=1, line_end=2, category="bug",
                         severity="major", confidence=1.5, title="t", description="d",
                         evidence="e", suggestion="s")

def test_analysis_result_accepts_empty_findings():
    r = AnalysisResult(summary={"title": "t", "overview": "o", "key_points": [], "risk_highlights": []},
                       findings=[], meta={})
    assert r.findings == []
```

- [ ] **Step 2: 运行确认失败** — 期望 `ModuleNotFoundError: app.models`。
- [ ] **Step 3: 实现模型** — 按上述 Produces 定义；`confidence: float = Field(ge=0.0, le=1.0)`；`FindingCandidate` 增加 `@field_validator("line_end")` 保证 `>= line_start`；`Finding.id` 默认 `uuid4()`。
- [ ] **Step 4: 运行确认通过** — `pytest backend/tests/test_models.py -v` PASS。
- [ ] **Step 5: 提交** — `git add backend/app/models backend/tests/test_models.py && git commit -m "feat(models): core pydantic schemas for PR, findings, analysis result"`

---

### Task T3: GitHub 数据获取（URL 解析 + REST 客户端）

> ✅ **完成** — commit `76f07d4`（2026-08-04，implementer: Galileo；review: Dewey ✅ Approved；404→repo_not_found 裁决为 plan 既定，pull_not_found 保留备用）

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/github_fetcher.py`
- Test: `backend/tests/test_pr_parser.py`, `backend/tests/test_github_fetcher.py`
- Modify: `backend/app/core/errors.py`（补充 `github_api_error` 等错误码，如已存在则忽略）

**Interfaces:**
- Consumes: `PRInfo/ChangedFile/PRContext`（T2）、`AppError`（T1）
- Produces:
  - `parse_pr_url(url: str) -> tuple[str, str, int]`（owner, repo, number；支持 `https://github.com/o/r/pull/N` 与 `o/r/pull/N`；非法抛 `AppError("invalid_url")`）
  - `class GitHubFetcher:` 
    - `__init__(self, token: str | None = None, timeout: float = 15.0)`
    - `async def fetch_pr(self, owner: str, repo: str, number: int) -> PRInfo`
    - `async def fetch_changed_files(self, owner: str, repo: str, number: int) -> list[ChangedFile]`（分页 `per_page=100` 拉 `pulls/{n}/files`；并为每个文件拉 head 内容：优先 `contents` API，二进制/超 1MB 时置 `None`）
    - `async def fetch_context(self, owner: str, repo: str, number: int) -> PRContext`（组合以上；若 `len(files) > max_files` 或 diff 总字节 > `max_diff_bytes` 抛 `AppError("analysis_too_large")`）
  - 头部：`Accept: application/vnd.github+json`；有 token 加 `Authorization: Bearer <token>`；未认证 403/429 区分提示。

- [ ] **Step 1: 写失败测试 `test_pr_parser.py`**

```python
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
```

- [ ] **Step 2: 写失败测试 `test_github_fetcher.py`**（用 `respx` mock httpx；fixture 里关闭真实网络）

```python
import respx
import httpx
import pytest
from app.services.github_fetcher import GitHubFetcher
from app.core.errors import AppError

@respx.mock
async def test_fetch_pr_metadata():
    route = respx.get("https://api.github.com/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json={
            "number": 1, "title": "Fix bug", "html_url": "https://github.com/o/r/pull/1",
            "base": {"sha": "abc"}, "head": {"sha": "def"}}))
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
```

- [ ] **Step 3: 实现 `github_fetcher.py`** — `parse_pr_url` 用正则；`GitHubFetcher` 用 `httpx.AsyncClient`，404→`repo_not_found`（私有仓库无 token 也表现为 404，文档注明），403 且 message 含 rate limit→`github_rate_limited`，超时重试 2 次指数退避（0.5s/1s）；`fetch_changed_files` 分页拼接，`diff` 字段直接取 GitHub 返回的 `patch`（可能为 null 时置空串）；head 内容按 `contents` API 取 base64 解码，超 1MB 或非文本则 `None`。
- [ ] **Step 4: 运行确认通过** — `pytest backend/tests/test_pr_parser.py backend/tests/test_github_fetcher.py -v` PASS。
- [ ] **Step 5: 提交** — `git add backend/app/services backend/tests && git commit -m "feat(github): PR url parser and REST fetcher with pagination, retry, rate-limit errors"`

---

### Task T4: 上下文构建（hunk → 函数/类上下文窗口 + 分片）

**Files:**
- Create: `backend/app/services/context_builder.py`
- Test: `backend/tests/test_context_builder.py`

**Interfaces:**
- Consumes: `ChangedFile`（T2）
- Produces:
  - `extract_hunk_ranges(diff: str) -> list[tuple[int, int]]`：解析 unified diff 中每个 hunk 的新文件行区间（`@@ -a,b +c,d @@` → `(c, c+d-1)`；无上下文行时按首行）。
  - `find_enclosing_function(content: str, line: int, language: str = "python") -> tuple[int, int]`：返回含 `line`（1-based）的最小函数/类定义区间 `(start, end)`。策略（**裁决明确，T4 评审修正**）：从 `line` 向上找函数/类定义行，关键字覆盖 `def|class|function|func|fn`（python/go/rust/js/ts 均支持）；向下找结束——**python 用缩进法**，`{`/`}` 语言（js/ts/go/rust 等）用**括号配对**，未知语言 fallback ±20 行；找不到返回 `(line, line)`。注意 python 多行签名（`def foo(\n a,\n b\n):`）须把签名延续行视为头部，直到 `:` 结尾行后再判断函数体缩进。
  - `build_analysis_unit(file: ChangedFile, budget_in: int = 8000) -> list[AnalysisUnit]`：返回 unit **列表**（`AnalysisUnit = TypedDict { file_path, diff, context: str, truncated: bool }`；签名修正，T4 评审裁决）；上下文 = 所有 hunk 所在函数的并集文本（带行号前缀），超 budget 时按 hunk 分片返回多个 unit（每片 ≤ budget，`truncated=True` 表示文件超预算）。
  - `estimate_tokens(text: str) -> int`：粗略估算（`len(text) // 4`）。

- [ ] **Step 1: 写失败测试 `test_context_builder.py`**

```python
from app.models.pr import ChangedFile
from app.services.context_builder import extract_hunk_ranges, find_enclosing_function, build_analysis_unit

def test_extract_hunk_ranges():
    diff = "@@ -1,5 +1,6 @@\n a\n-b\n+c\n d\n@@ -20,3 +20,4 @@\n x\n+y\n"
    assert extract_hunk_ranges(diff) == [(1, 6), (20, 23)]

PY = "def foo():\n    x = 1\n    if x:\n        return 2\n    return 3\n\ndef bar():\n    return 4\n"

def test_find_enclosing_function():
    start, end = find_enclosing_function(PY, 3, "python")
    assert start == 1 and end == 5

def test_find_enclosing_function_fallback():
    assert find_enclosing_function("no function here\n", 1, "python") == (1, 1)

def test_build_analysis_unit_includes_context():
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff="@@ -1,3 +1,3 @@\n def foo():\n-    x = 1\n+    x = 2", head_content=PY)
    unit = build_analysis_unit(f)[0]
    assert "def foo" in unit["context"]
    assert unit["file_path"] == "a.py"
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 `context_builder.py`** — `extract_hunk_ranges` 正则 `@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@`；`find_enclosing_function`：对 python/js/ts/go/rust 用缩进法，`{`/`}` 语言用括号配对，未知语言 fallback ±20 行；`build_analysis_unit`：取所有 hunk 区间覆盖的函数并集文本作为 `context`（含行号前缀），`truncated` 标记超预算；超预算分片（每片覆盖连续 hunk 子集）。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(context): hunk range parsing and enclosing function/class context windows"`

---

### Task T5: LLM 客户端（OpenAI 兼容 + JSON schema 校验 + 重试）

**Files:**
- Create: `backend/app/services/llm_client.py`
- Test: `backend/tests/test_llm_client.py`

**Interfaces:**
- Consumes: `Settings`（T1）、`AppError`（T1）
- Produces:
  - `class LLMClient:` 
    - `__init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0)`
    - `async def chat_json(self, messages: list[dict], response_schema: type[pydantic.BaseModel], temperature: float = 0.2) -> pydantic.BaseModel`
      - POST `{base_url}/chat/completions`，body `{model, messages, temperature, response_format: {"type": "json_object"}, stream: false}`，header `Authorization: Bearer <key>`；
      - 解析 `choices[0].message.content` 为 JSON → `response_schema.model_validate_json`；
      - 解析/校验失败：追加一条 system 消息"你的输出必须是合法 JSON 且符合给定 schema，请修正"重试 1 次；仍失败抛 `AppError("llm_json_parse_failed")`；
      - 超时/连接错误重试 1 次后抛 `AppError("llm_timeout")`。

- [ ] **Step 1: 写失败测试 `test_llm_client.py`**

```python
import respx, httpx, pytest
from pydantic import BaseModel
from app.services.llm_client import LLMClient
from app.core.errors import AppError

class Out(BaseModel):
    ok: bool

@respx.mock
async def test_chat_json_ok():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    out = await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert out.ok is True

@respx.mock
async def test_chat_json_repair_retry():
    route = respx.post("https://api.deepseek.com/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": false}'}}]}),
    ]
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    out = await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert out.ok is False
    assert len(route.calls) == 2

@respx.mock
async def test_chat_json_fails_after_retries():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]}))
    client = LLMClient("https://api.deepseek.com", "k", "deepseek-v4-flash")
    with pytest.raises(AppError) as ei:
        await client.chat_json([{"role": "user", "content": "hi"}], Out)
    assert ei.value.code == "llm_json_parse_failed"
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现 `llm_client.py`** — 用 `httpx.AsyncClient`；关键点：`response_format` 兼容不同供应商（DeepSeek 支持 json_object）；修复重试的消息追加；错误码统一 `AppError`；**日志只记录状态码/耗时，绝不记录 content 与 key**。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(llm): OpenAI-compatible chat client with JSON schema validation and repair retry"`

---

---

### Task T6: 分析引擎 Stage 1 生成（文件级并行候选发现）

**Files:**
- Create: `backend/app/services/analysis_engine.py`
- Test: `backend/tests/test_analysis_engine.py`

**Interfaces:**
- Consumes: `AnalysisUnit`（T4）、`LLMClient.chat_json`（T5）、`FindingCandidate`（T2）
- Produces:
  - `GENERATE_SCHEMA`：pydantic model `GenerateOutput(BaseModel)`：`findings: list[FindingCandidate]`（字段与 T2 一致；`confidence: float = Field(ge=0, le=1)`）。
  - `build_generate_messages(unit: AnalysisUnit, instructions: str) -> list[dict]`：system 指令（固定枚举、行号必须落在变更行、只报告由本次变更引入的问题、输出 JSON）+ user（diff 片段 + 上下文）。
  - `async def generate_for_unit(client: LLMClient, unit: AnalysisUnit) -> list[FindingCandidate]`：调 `chat_json`，把 `line_start/line_end` 校准到 hunk 变更行范围内（越界的截断/丢弃并置 `valid=False` 交给校验阶段）。
  - `class AnalysisEngine:` 
    - `__init__(self, llm: LLMClient, concurrency: int = 4)`
    - `async def stage1_generate(self, units: list[AnalysisUnit], progress: Callable[[str, int, int], None] | None = None) -> list[tuple[AnalysisUnit, list[FindingCandidate]]]`：`asyncio.Semaphore` 限流 + `asyncio.gather` 并行；单 unit 失败（重试后）→ 记录 skipped 并继续；progress 回调 `(阶段, 完成数, 总数)`。

- [ ] **Step 1: 写失败测试 `test_analysis_engine.py`（stage1）**

```python
import pytest
from app.services.llm_client import LLMClient
from app.services.analysis_engine import AnalysisEngine, build_generate_messages

class FakeLLM:
    def __init__(self, out): self.out = out; self.calls = 0
    async def chat_json(self, messages, schema, temperature=0.2):
        self.calls += 1
        return schema.model_validate(self.out)

def unit():
    return {"file_path": "a.py", "diff": "@@ -1,2 +1,2 @@", "context": "def f():\n    pass", "truncated": False}

async def test_build_generate_messages_contains_enum_hint():
    msgs = build_generate_messages(unit(), "instructions")
    assert any("bug" in m["content"] for m in msgs)

async def test_stage1_parallel_and_collect():
    llm = FakeLLM({"findings": [{"file_path": "a.py", "line_start": 1, "line_end": 2,
        "category": "bug", "severity": "major", "confidence": 0.8, "title": "t",
        "description": "d", "evidence": "e", "suggestion": "s"}]})
    engine = AnalysisEngine(llm, concurrency=2)
    results = await engine.stage1_generate([unit(), unit()])
    assert len(results) == 2 and llm.calls == 2

async def test_stage1_skips_failed_unit():
    class FlakyLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            raise RuntimeError("boom")
    engine = AnalysisEngine(FlakyLLM())
    results = await engine.stage1_generate([unit()])
    assert results == []
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — `build_generate_messages` 指令模板写入常量（含：只报告**本次变更引入**的问题；category 固定枚举；severity 枚举；confidence 0-1；line 必须落在变更行；输出纯 JSON）。`generate_for_unit` 调用后校准行号：解析 hunk 变更行集合，candidate 区间与变更行无交集 → 直接丢弃（并计入 `dropped_by_scope` 统计）。`stage1_generate` 捕获每个 unit 的异常（含 `AppError`），记录 skipped，不中断整体。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(engine): stage1 candidate generation with per-file parallel execution and scope calibration"`

---

### Task T7: 分析引擎 Stage 2 校验（keep/drop/downgrade + 置信度修订）

**Files:**
- Modify: `backend/app/services/analysis_engine.py`
- Test: `backend/tests/test_analysis_engine.py`（追加）

**Interfaces:**
- Consumes: `GenerateOutput`（T6）、`AnalysisUnit`（T4）
- Produces:
  - `VERIFY_SCHEMA`：`VerifyOutput(BaseModel)`：`results: list[VerifyItem]`；`VerifyItem(BaseModel)`：`index: int, verdict: Literal["keep", "drop", "downgrade"], confidence: float = Field(ge=0, le=1), reason: str`。
  - `build_verify_messages(unit: AnalysisUnit, candidates: list[FindingCandidate]) -> list[dict]`：system 指令（逐条判定三问：是否由本次变更引入 / 是否在变更行范围内 / 与上下文是否矛盾）+ user（diff/上下文/候选 JSON）。
  - `async def verify_candidates(self, unit: AnalysisUnit, candidates: list[FindingCandidate]) -> list[tuple[FindingCandidate, str]]`：返回 `(candidate, verdict)` 元组列表；`drop` 的移除、`downgrade` 的 severity 降一级（critical→major→minor→nit）、`keep` 保留；置信度取校验输出值。
  - `async def stage2_verify(self, pairs: list[tuple[AnalysisUnit, list[FindingCandidate]]], progress=None) -> list[Finding]`：并行校验，产出最终 `Finding` 列表（含 id/verified）。

- [ ] **Step 1: 写失败测试（追加到 test_analysis_engine.py）**

```python
from app.services.analysis_engine import AnalysisEngine
from app.models.finding import FindingCandidate

def cand(line_start=1, line_end=2, severity="major", confidence=0.9):
    return FindingCandidate(file_path="a.py", line_start=line_start, line_end=line_end,
        category="bug", severity=severity, confidence=confidence, title="t",
        description="d", evidence="e", suggestion="s")

async def test_stage2_verdicts_applied():
    class FakeVerifyLLM:
        async def chat_json(self, messages, schema, temperature=0.2):
            return schema.model_validate({"results": [
                {"index": 0, "verdict": "keep", "confidence": 0.7, "reason": "ok"},
                {"index": 1, "verdict": "drop", "confidence": 0.1, "reason": "pre-existing"},
                {"index": 2, "verdict": "downgrade", "confidence": 0.5, "reason": "low impact"},
            ]})
    engine = AnalysisEngine(FakeVerifyLLM())
    unit = {"file_path": "a.py", "diff": "@@ -1,2 +1,2 @@", "context": "", "truncated": False}
    findings = await engine.stage2_verify([(unit, [cand(), cand(severity="critical"), cand()])])
    assert len(findings) == 2                      # drop 移除
    assert findings[0].verified is True and findings[0].confidence == 0.7
    assert findings[1].severity == "major"         # critical downgraded to major
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — 校验调用按 unit 批量；verdict 应用到 candidates；置信度用校验值替换；`downgrade` 映射表 `{critical: major, major: minor, minor: nit, nit: nit}`；校验阶段的 prompt 强调"宁可漏报（drop）也不误报（keep）"以控制误报。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(engine): stage2 verification with keep/drop/downgrade and confidence revision"`

---

### Task T8: 分析引擎 Stage 3 汇总 + 编排器（全流程）

**Files:**
- Modify: `backend/app/services/analysis_engine.py`
- Test: `backend/tests/test_analysis_engine.py`（追加）

**Interfaces:**
- Consumes: `PRContext`（T2）、`AnalysisResult/AnalysisSummary`（T2）、stage1/stage2（T6/T7）、`GitHubFetcher`（T3）、`build_analysis_unit`（T4）、`LLMClient`（T5）
- Produces:
  - `AGGREGATE_SCHEMA`：`AggregateOutput(BaseModel)`：`summary: AnalysisSummary`。
  - `build_aggregate_messages(pr_info, per_file: list[tuple[str, list[Finding]]]) -> list[dict]`。
  - `async def aggregate(self, pr_info, findings: list[Finding]) -> AnalysisSummary`。
  - `async def run_analysis(self, ctx: PRContext, progress: Callable[[str, int, int], None] | None = None) -> AnalysisResult`：
    1. `building`：对所有文件 `build_analysis_unit`（返回 `(file_path, list[unit])`），超限文件记录 skipped；
    2. `analyzing`：stage1（progress 事件 `analyzing`）；
    3. `verifying`：stage2（progress 事件 `verifying`）；
    4. `aggregating`：stage3（progress 事件 `aggregating`）；
    5. 汇总 `meta`：`{"stage_durations": {...}, "token_estimate": {...}, "skipped_files": [...]}`。
  - 部分失败语义：某文件 fetch/analyze 失败 → skipped；只要至少 1 个文件成功即返回结果并在 meta 标注部分成功。

- [ ] **Step 1: 写失败测试（追加）**

```python
from app.models.pr import PRInfo, ChangedFile, PRContext
from app.services.analysis_engine import AnalysisEngine

async def test_run_analysis_full_pipeline():
    llm = FakeLLM({"findings": []})  # 复用 T6 的 FakeLLM：chat_json 按 schema 返回
    engine = AnalysisEngine(llm)
    info = PRInfo(owner="o", repo="r", number=1, title="t", html_url="u", base_sha="a", head_sha="b")
    f = ChangedFile(path="a.py", status="modified", additions=1, deletions=1,
                    diff="@@ -1,2 +1,2 @@\n-x\n+y", head_content="def f():\n    x = 1\n    y = 2\n")
    ctx = PRContext(info=info, files=[f])
    events = []
    result = await engine.run_analysis(ctx, progress=lambda stage, done, total: events.append((stage, done, total)))
    assert result.summary.title == "" or isinstance(result.summary, object)  # 结构可解析
    assert result.findings == []
    assert "skipped_files" in result.meta
    stages = {e[0] for e in events}
    assert {"building", "analyzing", "verifying", "aggregating"} <= stages
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — 按 Produces 顺序实现；`run_analysis` 把进度事件规范化为 `(stage, done, total)`；FakeLLM 在测试中按 schema 返回空 findings/空 summary，真实调用按 T6-T7 语义。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(engine): stage3 aggregation and full pipeline orchestrator with partial-failure semantics"`

---

### Task T9: 任务管理器 + analyze/tasks API（含 SSE）

**Files:**
- Create: `backend/app/services/task_manager.py`
- Create: `backend/app/api/analyze.py`
- Modify: `backend/app/main.py`（注册 analyze router）
- Test: `backend/tests/test_task_manager.py`, `backend/tests/test_api_analyze.py`

**Interfaces:**
- Consumes: `AnalysisEngine.run_analysis`（T8）、`GitHubFetcher`（T3）、`parse_pr_url`（T3）、`Settings`（T1）
- Produces:
  - `class TaskManager:`（单例）
    - `create(self, pr_url: str, token: str | None, engine: AnalysisEngine, fetcher: GitHubFetcher) -> str`（返回 task_id=uuid4；立即 `asyncio.create_task(self._run(...))`）
    - `get(self, task_id: str) -> TaskState | None`；`TaskState = TypedDict { id, status, stage, progress_done, progress_total, result: AnalysisResult | None, error: str | None, created_at, updated_at }`
    - `subscribe(self, task_id: str) -> asyncio.Queue`（SSE 事件队列）；`cancel(self, task_id: str)`
    - `_run`：状态机推进；每阶段 `put` 事件到订阅队列；结束时 `put` 终止事件。
  - 事件负载：`{"type": "stage", "stage": "...", "done": n, "total": m}` / `{"type": "done", "result": {...}}` / `{"type": "error", "code": "...", "message": "..."}`。
  - API（`app/api/analyze.py`）：
    - `POST /api/analyze` body `{pr_url: str, github_token: str | None = None}` → `202 {task_id}`；`github_token` 只在本请求→任务内存中使用，绝不落库/写日志。
    - `GET /api/tasks/{task_id}` → 状态 JSON。
    - `GET /api/tasks/{task_id}/events` → SSE（`text/event-stream`，`X-Accel-Buffering: no`，心跳注释每 15s；断线由前端 EventSource 重连，task 状态幂等可查询）。

- [ ] **Step 1: 写失败测试 `test_task_manager.py`**

```python
import asyncio
import pytest
from app.services.task_manager import TaskManager

async def test_task_state_machine():
    tm = TaskManager()
    engine = FakeEngine()          # 见下
    fetcher = FakeFetcher()        # 返回最小 PRContext
    tid = tm.create("o/r/pull/1", None, engine, fetcher)
    for _ in range(50):
        st = tm.get(tid)
        if st and st["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.01)
    st = tm.get(tid)
    assert st["status"] == "succeeded"
    assert st["result"] is not None

async def test_task_events_emitted():
    tm = TaskManager()
    engine = FakeEngine(); fetcher = FakeFetcher()
    tid = tm.create("o/r/pull/1", None, engine, fetcher)
    q = tm.subscribe(tid)
    events = []
    while True:
        try:
            ev = await asyncio.wait_for(q.get(), timeout=2)
        except asyncio.TimeoutError:
            break
        events.append(ev["type"])
        if ev["type"] in ("done", "error"):
            break
    assert "stage" in events and events[-1] == "done"
```

- [ ] **Step 2: 写失败测试 `test_api_analyze.py`**（用 TestClient + 注入 FakeEngine/FakeFetcher 到 app.state；断言 `POST /api/analyze` 返回 202、`GET /api/tasks/{id}` 最终 succeeded、SSE endpoint 返回 `text/event-stream`）。
- [ ] **Step 3: 实现** — TaskManager 用 dict 注册表 + asyncio 事件；`cancel` 用 `task.cancel()`；SSE endpoint 用 `StreamingResponse`，循环 `await queue.get()`，心跳用 `asyncio.wait_for(..., timeout=15)` + 注释行。Token 仅存于 `TaskState`（运行期内存），`_run` 结束即从 dict 移除 token 字段。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(api): async task manager with SSE progress and analyze/tasks endpoints"`

---

---

### Task T10: 历史存储（SQLite CRUD + Markdown 导出）

**Files:**
- Create: `backend/app/services/history_store.py`
- Test: `backend/tests/test_history_store.py`

**Interfaces:**
- Consumes: `AnalysisResult`（T2）、`PRInfo`（T2）、`Settings.database_path`（T1）
- Produces:
  - `class HistoryStore:`
    - `__init__(self, db_path: str)`
    - `async def init(self)`（建表 `analyses`，字段见 SPEC §6；`CREATE TABLE IF NOT EXISTS`）
    - `async def save(self, pr: PRInfo, result: AnalysisResult, config_snapshot: dict, duration_ms: int) -> str`（返回 id）
    - `async def list(self, limit: int = 50, offset: int = 0) -> list[dict]`（按 created_at desc）
    - `async def get(self, id: str) -> dict | None`
    - `async def delete(self, id: str) -> bool`
    - `async def export_markdown(self, id: str) -> str`（变更总结 + findings 表格 + 建议；找不到抛 `AppError("not_found")`）
  - `_serialize_result(result) -> dict`（summary/findings 转 JSON-safe dict）。

- [ ] **Step 1: 写失败测试 `test_history_store.py`**

```python
import pytest
from app.services.history_store import HistoryStore
from app.models.analysis import AnalysisSummary, AnalysisResult
from app.models.pr import PRInfo
from app.core.errors import AppError

@pytest.mark.asyncio
async def test_save_list_get_delete(tmp_path):
    store = HistoryStore(str(tmp_path / "a.db"))
    await store.init()
    pr = PRInfo(owner="o", repo="r", number=1, title="t", html_url="u", base_sha="a", head_sha="b")
    res = AnalysisResult(summary=AnalysisSummary(title="t", overview="o", key_points=[], risk_highlights=[]), findings=[], meta={})
    aid = await store.save(pr, res, {"model": "m"}, 100)
    rows = await store.list()
    assert len(rows) == 1 and rows[0]["id"] == aid
    got = await store.get(aid)
    assert got["pr_number"] == 1
    assert await store.delete(aid) is True
    assert await store.get(aid) is None

@pytest.mark.asyncio
async def test_export_markdown(tmp_path):
    store = HistoryStore(str(tmp_path / "a.db"))
    await store.init()
    pr = PRInfo(owner="o", repo="r", number=1, title="Fix", html_url="u", base_sha="a", head_sha="b")
    res = AnalysisResult(summary=AnalysisSummary(title="Fix", overview="ov", key_points=["k"], risk_highlights=["r"]), findings=[], meta={})
    aid = await store.save(pr, res, {}, 1)
    md = await store.export_markdown(aid)
    assert "# PR 评审报告" in md and "Fix" in md
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — `aiosqlite`；`save` 把 summary/findings 用 `json.dumps` 存 TEXT；`export_markdown` 模板含 `# PR 评审报告`、`## 变更总结`、`## 风险发现`（Markdown 表格：类别/严重度/置信度/文件:行/标题/建议）、`## 评审建议`；`not_found` 抛 `AppError("not_found")`（在 errors.py 补充该码）。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(history): sqlite analyses store with list/get/delete and markdown export"`

---

### Task T11: 凭据与设置（keyring + .env + CLI + settings API）

**Files:**
- Create: `backend/app/services/credentials.py`, `backend/app/cli.py`
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/main.py`（注册 settings router）
- Test: `backend/tests/test_credentials.py`, `backend/tests/test_api_settings.py`

**Interfaces:**
- Consumes: `Settings`（T1）、`AppError`（T1）、`LLMClient`（T5）
- Produces:
  - `class CredentialStore:`
    - `get_llm_api_key() -> str | None`（先 keyring，后 env `LLM_API_KEY`，后 `.env` 文件解析）
    - `set_llm_api_key(key: str) -> None`（keyring 优先；不可用时写入 `.env` 并提示）
    - `clear_llm_api_key() -> None`
    - `mask(key: str) -> str`（`sk-****1234`，≤4 字符显示 `****`）
  - CLI（`python -m app.cli`，用 argparse）：
    - `key set`：`getpass.getpass("Enter LLM API key: ")` 隐藏输入 → 存 keyring → 打印 `已保存（掩码：sk-****1234）`；
    - `key status`：打印 已配置/未配置 + 掩码；
    - `key clear`：清除。
  - API（`app/api/settings.py`，所有响应掩码）：
    - `GET /api/settings/llm` → `{base_url, model, api_key_configured: bool, api_key_masked: str | None}`
    - `PUT /api/settings/llm` body `{base_url?, model?, api_key?}`（api_key 为空串表示不更新）→ 更新后掩码状态
    - `DELETE /api/settings/llm` → 清除 key
    - `POST /api/settings/llm/test` → 用当前配置发起最小 chat 请求，返回 `{ok: bool, latency_ms: int, error: str | None}`（**不记录 key**）

- [ ] **Step 1: 写失败测试 `test_credentials.py`**

```python
from app.services.credentials import CredentialStore, mask

def test_mask():
    assert mask("sk-abcdef1234") == "sk-****1234"
    assert mask("abc") == "****"

def test_get_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert CredentialStore.get_llm_api_key() is None
```

- [ ] **Step 2: 写失败测试 `test_api_settings.py`**：GET 返回 `api_key_configured` 布尔与掩码；PUT 后 GET 显示掩码变化；DELETE 后 `api_key_configured=False`（测试中 monkeypatch keyring 为内存 stub，避免触碰真实钥匙串）。
- [ ] **Step 3: 实现** — `credentials.py`：`keyring.get_password("pr-review-assistant", "llm_api_key")`；env 读取用 `os.environ.get("LLM_API_KEY")`；`.env` 解析仅当 keyring 与 env 都没有时读 `backend/.env`（简单 key=value 解析，不引第三方 dotenv 亦可）。`cli.py` 用 argparse + getpass。`settings.py`：PUT 仅更新提供的字段；`test` 用 `LLMClient` 发 `{"messages":[{"role":"user","content":"ping"}], "max_tokens": 8}` 短请求测连通。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(credentials): keyring-backed llm key store with masked status, cli and settings api"`

---

### Task T12: 限流 + 错误映射 + 全后端装配

**Files:**
- Create: `backend/app/core/rate_limit.py`
- Modify: `backend/app/main.py`、`backend/app/api/analyze.py`
- Test: `backend/tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `Settings.rate_limit_per_min`（T1）
- Produces:
  - `class RateLimiter:` `__init__(self, limit: int, window_sec: int = 60)`；`async def allow(self, key: str) -> bool`（滑动窗口/令牌桶，内存实现）
  - FastAPI 依赖 `rate_limit_dependency(request: Request) -> None`（按 client IP 计数，超限抛 429 + `AppError("rate_limited")`）；挂到 `/api/analyze` 与 `/api/settings/llm/test`。
  - `main.py`：注册全部 routers（health/analyze/history/settings）；统一异常处理器：`AppError` → HTTP 状态映射表（见 `core/errors.py`，默认 400，`repo_not_found/pull_not_found`→404，`github_rate_limited`→429，`analysis_too_large`→413，`llm_timeout`→504，`not_found`→404，`rate_limited`→429）；启动时 `HistoryStore.init()` 与 `TaskManager` 单例初始化；CORS（默认允许同源，可用 `CORS_ORIGINS` 环境变量覆盖）。

- [ ] **Step 1: 写失败测试 `test_rate_limit.py`**

```python
import pytest
from app.core.rate_limit import RateLimiter

@pytest.mark.asyncio
async def test_allow_within_limit():
    rl = RateLimiter(limit=2)
    assert await rl.allow("ip1") is True
    assert await rl.allow("ip1") is True
    assert await rl.allow("ip1") is False
    assert await rl.allow("ip2") is True
```

- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — 令牌桶（asyncio.Lock + deque 时间戳）；`rate_limit_dependency` 用 `request.client.host`。
- [ ] **Step 4: 运行确认通过**（含全量 `pytest backend/tests/` 回归）。
- [ ] **Step 5: 提交** — `git commit -m "feat(core): rate limiting and unified error mapping, wire all backend routers"`

---

### Task T13: history/settings API 路由（供前端使用）

**Files:**
- Create: `backend/app/api/history.py`
- Modify: `backend/app/main.py`（注册 history router）
- Test: `backend/tests/test_api_history.py`

**Interfaces:**
- Consumes: `HistoryStore`（T10）、`CredentialStore`（T11）
- Produces:
  - `GET /api/history?limit=50&offset=0` → `{items: [...], total: int}`
  - `GET /api/history/{id}` → 单条详情（含 summary/findings 解析后的 dict）
  - `DELETE /api/history/{id}` → 204
  - `GET /api/history/{id}/export` → `text/markdown` 附件下载

- [ ] **Step 1: 写失败测试 `test_api_history.py`**：POST `/api/analyze`（FakeEngine）→ 等 succeeded → GET 列表含该条 → GET 详情 → GET export 返回 `text/markdown` → DELETE 后列表为空。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — 依赖注入 `request.app.state.history`；`export` 用 `Response(content=md, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="report.md"'})`。
- [ ] **Step 4: 运行确认通过**。
- [ ] **Step 5: 提交** — `git commit -m "feat(api): history list/detail/delete/export endpoints"`

---

### Task T14: 前端脚手架（Vite + React + TS + Tailwind + 设计契约）

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/app/App.tsx`, `frontend/src/app/router.tsx`, `frontend/src/api/client.ts`, `frontend/src/api/sse.ts`, `frontend/src/styles/theme.css`
- Create: `frontend/src/pages/HomePage.tsx`（骨架）
- Create: `DESIGN.md`（根目录，Open Design 设计契约：色彩/字体/间距/组件规范；基于 Open Design 的 web 设计系统约定）

**Interfaces:**
- Consumes: 后端 API 契约（`POST /api/analyze`、`GET /api/tasks/{id}`、`GET /api/tasks/{id}/events`、history/settings 路由）
- Produces:
  - `api/client.ts`：`analyze(prUrl, githubToken?) -> Promise<{task_id}>`；`getTask(taskId) -> Promise<TaskState>`；`getHistory/deleteHistory/exportUrl(id)`；`getSettings/updateSettings/clearSettings/testSettings`
  - `api/sse.ts`：`subscribeTask(taskId, handlers: {onStage, onDone, onError}) -> () => void`（EventSource + 重连：`onerror` 触发时若 task 状态已 succeeded/failed 则停止，否则 1s 后重连）

- [ ] **Step 1: 创建脚手架** — 用 `npm create vite@latest frontend -- --template react-ts`（或手写等价配置）；安装 `react-router-dom`、`tailwindcss`；`vite.config.ts` 设置 `server.proxy`：`/api` → `http://localhost:8000`（开发期），`build.outDir` 默认 dist。
- [ ] **Step 2: 写失败测试（前端 smoke）** — 前端测试用 Vitest + Testing Library：
  `frontend/src/__tests__/client.test.ts`：mock `fetch`，断言 `analyze()` 调 `POST /api/analyze` 并带 `github_token`（若提供）。
- [ ] **Step 3: 实现 client/sse + 主题** — 按 Produces 实现；`theme.css` 定义 CSS 变量（主色/语义色/间距/圆角），Tailwind 引用（`tailwind.config.js` 的 `theme.extend.colors` 指向 CSS 变量）。
- [ ] **Step 4: 运行确认** — `cd frontend && npm run build` 通过；`npm test` 通过。
- [ ] **Step 5: 提交** — `git commit -m "feat(frontend): vite react-ts scaffold with api client, sse, theme tokens"`

---

### Task T15: 首页 + 进度页（SSE）

**Files:**
- Create: `frontend/src/pages/HomePage.tsx`（完整）、`frontend/src/pages/ProgressPage.tsx`
- Create: `frontend/src/components/ProgressBar.tsx`, `frontend/src/components/StageBadge.tsx`
- Test: `frontend/src/__tests__/HomePage.test.tsx`

**Interfaces:**
- Consumes: `api/client.ts`, `api/sse.ts`（T14）
- Produces:
  - HomePage：表单（PR URL 输入、可选 GitHub token `type=password`、**示例 PR 一键体验**按钮（填充 `example_pr` 并直接提交）、提交按钮）；提交后 `navigate(/progress/{taskId})`；错误提示（401/404/413/429/504 映射文案）。
  - ProgressPage：`useEffect` 订阅 SSE；显示阶段徽章（fetching/building/analyzing/verifying/aggregating）+ 进度条（done/total）+ 耗时；收到 done → `navigate(/result/{taskId})`；error → 展示错误 + 重试链接。

- [ ] **Step 1: 写失败测试 `HomePage.test.tsx`**：渲染表单；输入 PR URL 后点提交 → mock `analyze` 被调用且带该 URL；点击"示例 PR"按钮 → `analyze` 收到示例 URL。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现页面** — 表单受控组件；token 输入 `autocomplete="off"`；提交后禁用按钮防重复；SSE 订阅清理 `return () => unsubscribe()`。
- [ ] **Step 4: 运行确认通过** — `npm test` + `npm run build`。
- [ ] **Step 5: 提交** — `git commit -m "feat(frontend): home page with PR form, example PR, and SSE progress page"`

---

### Task T16: 结果看板 + 历史页 + 设置页

**Files:**
- Create: `frontend/src/pages/ResultPage.tsx`, `frontend/src/pages/HistoryPage.tsx`, `frontend/src/pages/SettingsPage.tsx`
- Create: `frontend/src/components/SummaryCard.tsx`, `frontend/src/components/FindingsList.tsx`, `frontend/src/components/DiffViewer.tsx`, `frontend/src/components/ExportButton.tsx`
- Test: `frontend/src/__tests__/FindingsList.test.tsx`, `frontend/src/__tests__/DiffViewer.test.tsx`

**Interfaces:**
- Consumes: T14 client/sse、T15 导航
- Produces:
  - ResultPage：从 `/result/{taskId}` 用 `getTask` 拉结果（task 完成则直接渲染，否则跳进度页）；渲染 `SummaryCard`（变更总结/要点/风险高亮）、`FindingsList`（按 severity 排序，可按 category/severity 过滤；每项显示 类别徽章/严重度/置信度/文件:行/标题/描述/证据/建议）、`DiffViewer`（每文件 diff 渲染 + findings 行高亮，点击 finding 滚动到对应行）、`ExportButton`（`window.open(exportUrl)`）。
  - HistoryPage：列表（PR 标题/仓库/时间/状态）+ 详情跳转 + 删除 + 导出。
  - SettingsPage：显示 `base_url/model/api_key_configured/api_key_masked`；更新 base_url/model/key；清除 key；`测试连通性`按钮（显示延迟/错误）。

- [ ] **Step 1: 写失败测试**：`FindingsList` 按 severity 排序断言；`DiffViewer` 给定 diff 与 finding 行号，断言高亮行 class 包含 `highlight`。
- [ ] **Step 2: 运行确认失败**。
- [ ] **Step 3: 实现** — DiffViewer 用 `diff` 包解析 unified diff 为行数组（`parseDiff` + 行号映射）；高亮用 `line_start..line_end` 匹配；FindingsList 过滤状态用 useMemo。
- [ ] **Step 4: 运行确认通过** — `npm test` + `npm run build`。
- [ ] **Step 5: 提交** — `git commit -m "feat(frontend): result dashboard with diff highlight, history and settings pages"`

---

### Task T17: 分发、CI、文档与示例 PR 钉选（最后集成）

**Files:**
- Create: `backend/Dockerfile`（多阶段：`node:20-alpine` 构建前端 → `python:3.11-slim` 运行时，复制 dist 到 `backend/static`；`CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`；FastAPI `StaticFiles` 挂载 `/` 服务前端）
- Modify: `backend/app/main.py`（挂载静态资源 + SPA fallback）
- Create: `.github/workflows/ci.yml`（jobs：`unit-test`（pytest + 前端 npm test/build）、`docker-build`）
- Create: `.gitlab-ci.yml`（`unit-test` job 等价；`image: python:3.11`；`pytest backend/tests`）
- Create: `docker-compose.yml`、`.env.example`（`LLM_API_KEY=`、`LLM_BASE_URL=`、`LLM_MODEL=`、`EXAMPLE_PR=`）、`Makefile`（`test`/`build`/`run` 目标）
- Modify: `backend/app/core/config.py`（`example_pr` 从 env 读；`static_dir` 配置）
- Create: `README.md`（§：项目简介/架构/快速开始/API/安全边界/分发与部署/已知限制/目录结构/致谢与许可）
- Test: `backend/tests/test_example_pr.py`（断言 `config.example_pr` 是合法的 `owner/repo/pull/N` 格式）
- 文档任务（在 main 上，不进 worktree）：根 `SPEC.md`（从 design doc 生成正式版）、`PLAN.md`（本文件正式版）、`SPEC_PROCESS.md`、`AGENT_LOG.md`、`REFLECTION.md`（学生本人撰写，不 AI 代写）。

- [ ] **Step 1: 实现 Dockerfile/CI/文档** — 按上；`Makefile`：`test` 目标 `cd backend && pytest tests/`；`build` 目标 `docker build -t pr-review-assistant .`；`run` 目标 `docker run -p 8000:8000 --env-file .env -v prra-data:/app/data pr-review-assistant`。
- [ ] **Step 2: 写失败测试 `test_example_pr.py`**（格式断言）→ 运行确认。
- [ ] **Step 3: 钉选示例 PR** — 用 GitHub API 选一个稳定公开小 PR（如知名仓库的小改动），把 `owner/repo/pull` 写入 `.env.example` 默认值并录制其 GitHub fixture 到 `backend/tests/fixtures/`（供集成测试用）。
- [ ] **Step 4: 本地验证** — `make test` 全绿；`docker build` 成功；`docker run` 后 `curl localhost:8000/healthz` 返回 ok；前端 `npm run build` 通过。
- [ ] **Step 5: 提交** — `git commit -m "chore(deploy): docker multi-stage, CI (gh-actions + gitlab), README, env example, example PR pinning"`

---

## Self-Review 记录（实现前必读）

- **SPEC 覆盖**：M1↔T3/T4；M2↔T4；M3↔T6/T7/T8；M4↔T9；M5↔T10/T13；M6↔T11/T12；M7↔T14/T15/T16；凭据/分发↔T11/T17；CI↔T17；SSE↔T9/T15；示例 PR↔T15/T17；安全（掩码/脱敏/不落库）↔T3/T9/T11/T12 内约束。
- **类型一致性**：`AnalysisUnit`（T4 定义，T6/T7 消费）；`FindingCandidate→Finding`（T2→T6→T7）；`TaskState` 字段（T9 定义，前端 T14 消费）；`AnalysisResult`（T2→T8→T10）。所有 schema 名以各 Task 的 Produces 为准。
- **并行性**：WT-2（T6-T9）与 WT-3（T10-T13）都依赖 WT-1，二者在 WT-1 合并后可并行开发；WT-4 依赖 API 契约（T9/T13 的端点路径与请求/响应形状），可先行实现 UI 骨架。


