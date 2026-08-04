# SPEC — AI PR 评审助手（正式交付物）

> 本文件为正式交付物；来源：docs/superpowers/specs/2026-08-04-ai-pr-review-tool-design.md（brainstorming 存档）。

# AI PR 评审助手 · 设计文档（SPEC 底稿）

> 日期：2026-08-04
> 状态：已通过 brainstorming 逐节确认，待用户复核后进入 writing-plans
> 项目方向：AI4SE 期末项目 · B · 非 harness 应用类项目
> 完整要求 = 《AI4SE_Final_Project_通用要求.md》+《AI4SE_Final_Project_B_应用类项目.md》

---

## 1. 问题陈述

### 1.1 要解决的问题
PR（Pull Request）评审是研发流程中最耗时、质量波动最大的环节之一：

- 评审者需要在有限时间内通读 diff，容易漏检由上下文引入的缺陷（边界条件、空值、安全、并发等）；
- 评审标准因人而异，小 PR 常被拖沓、大 PR 常被草草放行；
- 每个 PR 都要重复"理解变更意图 → 找问题 → 写建议"的流程，机械化劳动占比高。

### 1.2 本工具做什么
以 **AI 辅助分析为核心**：用户指定一个 GitHub PR，系统自动获取代码变更与必要上下文，智能分析并产出：

1. **PR 变更总结**（这段改动做了什么、影响面、风险要点）；
2. **风险代码识别**（定位到文件 + 行号，固定类别枚举：bug / security / performance / maintainability / style，带严重度与置信度）；
3. **Review 建议生成**（每条发现附证据与可操作建议，供评审者直接采纳或讨论）。

### 1.3 目标用户
- 在 GitHub 上进行团队协作的**开发者 / 评审者 / 技术负责人**；
- 希望快速理解 PR、把精力集中在高价值判断（设计、取舍、业务语义）而非机械找茬的人。

### 1.4 为什么值得做（30 秒自述）
> "把 PR 链接粘进来，几秒钟后拿到一份定位到行的 AI 评审：改了什么、哪里可能出 bug、哪里该优化——每条都标了置信度，误报能过滤，还能导出报告分享。"

### 1.5 关键设计思路（题目要求说明的三大点）
- **模型选择思路**：通过 OpenAI 兼容协议抽象 LLM 供应商与模型（`base_url`/`model`/`api_key` 可配置，默认 `https://api.deepseek.com` + `deepseek-v4-flash`）。选择逻辑：默认模型在"速度 / 成本 / 中文与代码理解"上均衡，适合作为默认档；两阶段管线中**校验阶段**对严谨性要求更高，预留"校验模型可单独配置"的扩展位，未来可切更强的模型做校验、更快更省的模型做生成。详见 §8.3。
- **上下文获取方式**：diff + 变更文件上下文（按 hunk 提取所在函数/类作为上下文窗口），超大 PR 按文件 map-reduce 并行分析再汇总。平衡 token 成本、准确性与延迟。详见 §5 与 §8.4。
- **未来扩展方向**：GitHub App/Webhook 自动评审、评论回写、tree-sitter 精确上下文、结果缓存与增量分析、规则引擎 + LLM 混合、团队规范定制、多供应商路由。详见 §10。

---

## 2. 用户故事（7 个，INVEST）

| ID | 角色 | 故事 | 验收要点 |
|---|---|---|---|
| US-1 | 开发者 | 输入公开 GitHub PR 链接并点击分析，即可获得变更总结与风险列表，无需通读整个 diff | 公开 PR 返回结构化总结，典型 ≤90s |
| US-2 | 评审者 | 按风险类别/严重度过滤、排序并定位到文件行号的问题列表，聚焦高优先级项 | 列表可过滤/排序，每项含 file/line，diff 高亮 |
| US-3 | 团队负责人 | 分析私有仓库 PR 时填入自己的 GitHub token（仅本次会话有效），不把团队凭据交给服务端保存 | 私有仓库 + 会话 token 可用；token 不持久化、不落日志 |
| US-4 | 开发者 | 查看每条发现的证据与置信度，过滤误报 | 校验阶段丢弃/降级逻辑有单测；UI 展示置信度 |
| US-5 | 用户 | 实时看到分析各阶段进度（拉取→分片→分析→校验→汇总） | SSE 事件覆盖全阶段，前端逐阶段推进 |
| US-6 | 新用户 | 一键体验示例 PR，零配置了解工具价值 | 示例按钮出结果（真实公开样例） |
| US-7 | 用户 | 查看历史分析记录并导出 Markdown 报告 | 历史列表/详情/导出可用，重启后仍在 |
| US-8 | 部署者 | 安全录入/更新/清除服务端 LLM key，统一管理模型调用 | 首次 setup 引导；CLI 隐藏录入；掩码状态/更新/清除可用；源码与 git 历史无 key |

---

## 3. 功能规约（按模块）

每个模块描述：输入 / 行为 / 输出 / 边界 / 错误处理。

### M1 · GitHub 数据获取 `github_fetcher`
- **输入**：PR URL（`https://github.com/{owner}/{repo}/pull/{number}` 或 `{owner}/{repo}/pull/{n}`）、可选会话级 GitHub token、GitHub API 参数（超时/重试）。
- **行为**：解析 URL → 校验 repo/PR 存在 → 解析 base/head ref → 拉取 PR 元数据（标题/描述/作者/状态）→ 分页拉取变更文件列表与每文件 unified diff → 拉取变更文件在 head（及 base，供上下文对照）下的内容。
- **输出**：规范化 `PRContext`（owner/repo/number/title/base_sha/head_sha/变更文件[]，每文件含 path/status/diff/head_content/base_content）。
- **边界**：
  - 公开仓库免 token；私有仓库无 token → 明确错误 `private_repo_requires_token`；
  - 超大 PR（>50 文件或 diff 总大小 >2MB，可配）→ 拒绝并提示；
  - 单文件超大（>1MB）→ 截断并标注。
- **错误处理**：404（repo/PR 不存在）、403/429（区分未认证限额与 token 权限不足）、网络超时指数退避重试（2 次）。

### M2 · 上下文构建 `context_builder`
- **输入**：单文件 diff + head 文件内容（+ base 内容可选）。
- **行为**：按 hunk 定位变更行 → 用启发式（缩进/花括号配对，按语言 fallback）提取所在**函数/类上下文窗口**（签名 + 函数体，或 ±N 行）→ 拼接为「diff 片段 + 上下文 + 分析指令」输入单元。
- **输出**：每文件（或每 chunk）一个分析输入单元（含 token 预算估算）。
- **边界**：上下文提取失败 → 退化为纯 diff 分析；超大函数截断并标注"上下文已截断"。
- **错误处理**：提取过程不抛致命错，任何失败降级为 diff-only。

### M3 · LLM 分析引擎 `analysis_engine`（两阶段 + 汇总，核心模块）
- **Stage 1 生成（generate）**：每个分析输入单元一次 LLM 调用，强制 JSON 输出候选发现：
  - `category ∈ {bug, security, performance, maintainability, style}`（固定枚举）；
  - `severity ∈ {critical, major, minor, nit}`；
  - `confidence ∈ [0,1]`；`file_path / line_start / line_end`（必须落在变更行范围内）；
  - `title / description / evidence / suggestion`。
- **Stage 2 校验（verify）**：对候选逐条（批量）二次调用，判定三件事：
  1. 是否**由本次变更引入**（而非存量代码/无关代码）；
  2. 是否在**变更行范围**内（防"老代码问题"刷屏）；
  3. 与提供的上下文是否**矛盾**（防幻觉）。
  输出 `keep / drop / downgrade` + 修订置信度。
- **Stage 3 汇总（aggregate）**：一次调用合并各文件结果 → PR 级变更总结 + 按严重度排序的发现清单 + 评审建议（可按类别聚合）。
  `说明：「两阶段」指发现的生成-校验；汇总层是独立的合并步骤，不算发现生成阶段。`
- **并行与限流**：文件级 `asyncio.gather` + 信号量（默认并发 3-5，可配）；每文件 token 预算上限（默认 in ~8k / out ~4k，可配）。
- **输出**：`AnalysisResult { summary, findings[], meta { stage_durations, token_estimate } }`。
- **错误处理**：单文件失败（重试后）→ 标记该文件 skipped，任务继续，汇总标注"部分成功"；LLM 超时重试 1 次；JSON 解析失败 → 追加修复提示重试 1 次；仍失败 → `llm_json_parse_failed`。

### M4 · 任务管理 `task_manager`（SSE 进度）
- **输入**：创建任务（PR 参数、可选 token）；订阅事件流。
- **行为**：任务状态机 `pending → fetching → building → analyzing → verifying → aggregating → succeeded / failed / cancelled`；事件含阶段、进度（如 3/8 文件）、耗时；支持取消（asyncio 协作式取消）。
- **输出**：SSE `text/event-stream`（`/api/tasks/{id}/events`）+ 最终结果。
- **边界**：token 只存在于内存中的任务上下文，任务结束即释放。

### M5 · 历史与持久化 `history_store`（SQLite）
- **输入**：分析结果、查询条件（分页/关键字）。
- **行为**：保存 / 列表 / 详情 / 删除；导出 Markdown（变更总结 + 发现表格 + 建议）。
- **输出**：`analyses` 表记录；Markdown 文本。
- **边界**：不含任何 token；删除为硬删；findings 可空数组。

### M6 · 配置与凭据 `settings`
- **行为**：
  - 服务端 LLM 配置管理：`base_url`（默认 `https://api.deepseek.com`）、`model`（默认 `deepseek-v4-flash`）、`api_key`；
  - **首次运行引导**：未配置 key 时 Web 端显示 setup 引导页 + CLI 提供隐藏输入录入；
  - **状态查看**：掩码显示（如 `sk-****1234`）与"已配置/未配置"；
  - **更新 / 清除**：替换或删除 key。
- **边界**：key 绝不回显明文、绝不写日志；GitHub token 仅会话内存。

### M7 · Web 前端（React SPA）
- **页面**：
  1. 首页：PR 输入 + 可选 GitHub token + 「分析」按钮 + 「示例 PR 一键体验」；
  2. 进度页：SSE 各阶段进度条/日志；
  3. 结果看板：变更总结卡片、风险列表（过滤/排序）、diff 视图高亮、评审建议、保存/导出；
  4. 历史页：分析记录列表 + 详情 + 导出；
  5. 设置页：LLM 配置（掩码状态、更新、清除、连通性测试）。
- **行为**：所有敏感数据经后端转发；diff 高亮基于 findings 的行定位；SSE 断线自动重连。

---

## 4. 非功能性需求

### 4.1 性能
- 典型 PR（≤10 文件、≤1000 变更行）：总耗时目标 **≤90s**（取决于 LLM 延迟），SSE 全程可见进度。
- 文件级并行 + 信号量限流（默认并发 3-5）；每文件 token 预算上限；汇总层单次调用。
- 前端首屏静态资源轻量化（Vite 构建 + 按需加载）。

### 4.2 安全（含凭据威胁模型）
**威胁模型与对策矩阵**

| 资产 | 威胁 | 对策 |
|---|---|---|
| LLM key（服务端机密） | 源码/提交历史泄漏、日志/终端 history 泄漏、明文配置文件 | 绝不硬编码/不入库/不写日志；首选 OS keyring（Windows Credential Manager），`.env`（gitignored）为兜底并在 README 说明明文风险；掩码显示；更新/清除；首次 setup 引导 |
| GitHub token（用户会话机密） | 服务端落库、日志泄漏、XSS 窃取 | 仅会话内存、请求转发后即弃、不落库不写日志；仅经 fetch body 传递；前端 CSP；只读用途 |
| 公网滥用 | 恶意/超大请求耗尽配额 | API 轻量限流（内存令牌桶，默认 10 req/min/IP）；单次分析 diff 大小/文件数上限；部署者可选反代认证 |
| PR 数据 | 越权访问他人私有仓库 | token 由用户自持会话级提供；服务端不缓存 token；README 说明部署者责任 |

### 4.3 可用性
- 清晰错误提示（非法 URL / repo 不存在 / 私有仓库需 token / 限流 / LLM 失败）并可重试；
- SSE 断线重连；任务可取消；
- 无 key 时 setup 引导直达设置页。

### 4.4 可观测性
- 结构化日志（脱敏：key/token 绝不入日志；grep 断言测试）；
- `/healthz` 健康检查；任务耗时/阶段/token 估算指标；设置页连通性测试。

---

## 5. 系统架构

### 5.1 组件图
```
┌────────────────────────── Web 浏览器 ──────────────────────────┐
│  React SPA (Vite + TS)                                          │
│  首页 / 进度页 / 结果看板 / 历史页 / 设置页                       │
└───────────────┬──────────────────────────────┬─────────────────┘
                │ REST (JSON)                  │ SSE
┌───────────────▼──────────────────────────────▼─────────────────┐
│  FastAPI 后端（单进程，Python 3.11）                              │
│  ├─ API 路由层：analyze / tasks / history / settings / health   │
│  ├─ task_manager：asyncio 任务注册表 + 状态机 + SSE 事件          │
│  ├─ analysis_engine：编排（generate → verify → aggregate）        │
│  │    ├─ github_fetcher（GitHub REST，可选会话 token，分页/退避）  │
│  │    ├─ context_builder（hunk→函数/类上下文窗口，分片）           │
│  │    └─ llm_client（OpenAI 兼容，JSON schema 校验/重试/超时）    │
│  ├─ history_store（aiosqlite：analyses 表）                       │
│  └─ credentials（keyring 首选 + .env 兜底，掩码状态）              │
└───────────────┬──────────────────────────────┬─────────────────┘
                │ HTTPS                        │ HTTPS
        ┌───────▼───────┐              ┌───────▼────────┐
        │ GitHub REST API│              │ LLM 供应商     │
        └───────────────┘              │ OpenAI 兼容格式 │
                                       │ 默认 deepseek   │
                                       └────────────────┘
```

### 5.2 数据流（一次分析）
1. 用户提交 PR URL +（可选）token → 后端创建 task，返回 task_id，前端建立 SSE 连接。
2. `github_fetcher`：解析 URL → 校验 → 取 PR 元数据 + base/head ref → 分页拉变更文件 diff → 拉变更文件 head/base 内容。
3. `context_builder`：逐文件把 hunk 映射到函数/类上下文窗口 → 生成分析输入单元（超大文件/超大函数分片）。
4. Stage 1 生成：文件级并行 LLM 调用 → 各文件候选 findings（JSON schema 校验）。
5. Stage 2 校验：并行校验候选 → keep/drop/downgrade + 修订置信度。
6. Stage 3 汇总：一次调用 → PR 级变更总结 + 排序后发现 + 评审建议。
7. 结果写入 SQLite → SSE 推送 `succeeded` → 前端渲染看板。

### 5.3 外部依赖
- **GitHub REST API v3**：`repos/{owner}/{repo}/pulls/{n}`、`pulls/{n}/files`（分页）、`contents` 或 `git/blobs`（文件内容）。
- **LLM 供应商**：OpenAI 兼容格式端点，`base_url`/`model`/`api_key` 可配；默认 `https://api.deepseek.com` + `deepseek-v4-flash`。

---

## 6. 数据模型

### `analyses` 表（SQLite，aiosqlite 访问）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT (uuid) | 主键 |
| owner / repo | TEXT | 仓库标识 |
| pr_number | INT | PR 号 |
| pr_title | TEXT | PR 标题快照 |
| pr_url | TEXT | 原始链接 |
| base_sha / head_sha | TEXT | 分析时 ref 快照 |
| status | TEXT | `succeeded / failed / cancelled` |
| summary | TEXT(JSON) | 变更总结（要点列表等） |
| findings | TEXT(JSON) | 发现数组 |
| error | TEXT | 用户可读失败原因 |
| config_snapshot | TEXT(JSON) | 分析时 model/base_url（审计，不含 key） |
| duration_ms | INT | 总耗时 |
| created_at / updated_at | TEXT | ISO 时间 |

### finding 对象（内嵌于 analyses.findings，不单独建表）
```json
{
  "id": "uuid",
  "file_path": "src/foo.py",
  "line_start": 12,
  "line_end": 14,
  "category": "bug",
  "severity": "major",
  "confidence": 0.87,
  "title": "可能在 None 上调用方法",
  "description": "...",
  "evidence": "变更行 12 调用 x.foo() 而 x 可能为 None",
  "suggestion": "增加空值保护或断言",
  "verified": true
}
```
约束：id 唯一；findings 可空；任何表不存 token/key。

---

## 7. 凭据与分发设计

### 7.1 凭据存储方案
- **LLM key**：首选 OS keyring（Windows Credential Manager，`keyring` 库）；`.env`（gitignored，经启动加载而非命令行 export）为兜底；README 明示 `.env` 为明文、进程环境可见的风险。
- **GitHub token**：仅会话内存（服务端每任务上下文持有），请求转发后释放；不落库、不写日志；刷新/会话结束即弃。

### 7.2 录入 / 更新 / 清除流程
- **首次运行**：未检测到 key → Web 端 setup 引导 + `python -m app.cli key set`（getpass 隐藏输入）。
- **查看状态**：掩码显示（`sk-****1234`）+ 已配置/未配置；不提供明文回显。
- **更新 / 清除**：Web 设置页或 CLI 均可；清除后任务请求返回"未配置 LLM"错误。

### 7.3 分发形态
- **容器镜像（Docker，多阶段）**：Stage 1 Node 构建前端 → Stage 2 Python 3.11 运行时 + 前端静态产物。
- `docker build -t pr-review-assistant .` + `docker run -p 8000:8000 pr-review-assistant` 一条命令启动。
- SQLite 数据卷持久化（`-v prra-data:/app/data`）；LLM 配置经环境变量或启动后 Web/CLI。
- 平台无关，适配 Render / Railway / Fly.io / 云服务器；README 写明：获取方式、运行命令、**key 在目标机安全配置**、已知限制（单进程、SQLite 单机、未认证 GitHub 限额 60/h）。

---

## 8. 技术选型与理由

### 8.1 后端
**Python 3.11 + FastAPI + httpx + pydantic v2 + aiosqlite + uvicorn**
- 异步原生，适合并发调度 LLM/GitHub 调用；
- pydantic v2 直接承担 LLM JSON 输出的 schema 校验（两阶段管线的地基）；
- aiosqlite 轻量持久化，免去外部数据库依赖；
- 测试：pytest + pytest-asyncio（LLM/GitHub 全部 mock/stub，确定性）。

### 8.2 前端
**React 18 + TypeScript + Vite + Tailwind CSS**
- diff 高亮：`diff` 库 + 自定义 hunk 渲染（按 findings 行定位高亮）；
- SSE：原生 `EventSource` 经后端 `/api/tasks/{id}/events`；
- 组件化页面：首页 / 进度 / 看板 / 历史 / 设置。

### 8.3 模型选择思路（题目要求）
- **抽象层**：LLM 客户端为 OpenAI 兼容协议封装（`base_url`/`model`/`api_key` 可配），不绑定单一供应商；默认 `https://api.deepseek.com` + `deepseek-v4-flash`。
- **选择逻辑**：
  - 默认档 `deepseek-v4-flash`：速度与成本优先，中文与代码能力均衡，适合"生成"阶段的高并发调用；
  - 预留 `verify_model` 独立配置：校验阶段对严谨性要求更高，可切更强模型（如更大的 deepseek / GPT / Claude 系列）；
  - README/设置页给出"按需升级模型"的指引，并在 `config_snapshot` 记录分析时的模型便于审计复现。
- **权衡**：速度优先（默认档）vs 精度优先（可升级校验模型）——两阶段架构使"便宜生成 + 更贵校验"成为可能，是控制成本与质量的核心设计。

### 8.4 上下文获取方式思路（题目要求）
- **为什么不是纯 diff**：纯 diff 缺失函数/类上下文，漏报高（边界条件、空值、语义错误依赖周围代码）；
- **为什么不是全文件**：全文件 token 成本高、大仓库超窗；
- **本方案**：diff + 按 hunk 提取所在函数/类上下文窗口（启发式定位，失败退化为 ±N 行 / diff-only），超大 PR 按文件 map-reduce 并行、汇总层合并；
- **token 预算护栏**：每文件 in/out 上限可配，超限分片。

### 8.5 Open Design 设计系统说明（§3.6 要求）
- 采用 **Open Design 的 DESIGN.md 设计契约**（design tokens / 组件规范 / 反 AI 泛滥清单）作为界面设计基线，仓库内维护 `DESIGN.md`（字体/色彩/间距/组件规范）；
- 前端以 React + Tailwind 落地该规范；
- **不引入** Open Design 桌面运行时与 CLI（本项目为 Web SPA，直接实现其规范），此取舍在 README 说明。

---

## 9. 验收标准（客观判定）

| 功能 | 验收标准 |
|---|---|
| US-1 分析 | 公开 PR URL 提交后返回结构化总结，典型 ≤90s，看板渲染通过 |
| US-2 定位 | 发现列表可按 category/severity 过滤排序；每项含 file/line；diff 视图高亮对应行 |
| US-3 私有 | 私有仓库 + 会话 token 分析成功；token 不持久化：重启服务后不可复用、刷新后新分析需重填（进行中的任务不受影响）；日志 grep 无 token |
| US-4 误报控制 | 校验阶段对 fixture 中"非本次变更引入/越界/矛盾"候选做 keep/drop/downgrade，单测断言；UI 展示置信度 |
| US-5 进度 | SSE 事件序列覆盖全阶段，前端逐阶段推进 |
| US-6 示例 | 示例 PR 按钮零配置出结果；实现时选定一个稳定的公开样例（owner/repo/pull 号写入配置），并为测试录制该 PR 的 GitHub fixture |
| US-7 历史 | 历史列表/详情/Markdown 导出可用；重启后仍在（SQLite） |
| US-8 凭据 | 首次 setup 引导；CLI 隐藏录入；掩码状态/更新/清除可用；源码与 git 历史 grep 无 key |
| 工程 | `make test` 全绿；GitHub Actions pass；新机器 `docker build && docker run` 跑通出结果 |

---

## 10. 风险与未决问题

| # | 风险 | 缓解 |
|---|---|---|
| 1 | LLM JSON 稳定性（response_format 兼容性因供应商而异） | pydantic schema 校验 + 修复提示重试 + 兜底解析 |
| 2 | 超大 PR 超预算 | 超过上限拒绝并明确提示（可配） |
| 3 | GitHub 未认证限额 60/h | README 说明；建议高频填 token；缓存列为扩展 |
| 4 | 函数边界启发式不精确 | 退化 fallback；tree-sitter 精确解析列为扩展 |
| 5 | SSE 经反向代理被缓冲 | README 部署注意（关 buffering / heartbeat） |
| 6 | 公网滥用 | 限流 + diff 上限 + 可选反代认证 |

### 未决问题（实现前需定，均已有默认值）
- 汇总层 LLM 调用使用与生成同款默认模型（默认：是，可配）；
- 历史记录是否需要用户维度隔离（默认：单租户，不做用户体系）；
- 分析结果是否缓存同 PR 同 ref（默认：不缓存，列为扩展）。

---

## 11. 项目目录结构（目标）

```
PR-Review-Assistant/
├── SPEC.md / PLAN.md / SPEC_PROCESS.md / AGENT_LOG.md / README.md / REFLECTION.md
├── DESIGN.md                          # Open Design 设计契约
├── docs/superpowers/specs/2026-08-04-ai-pr-review-tool-design.md   # 本设计底稿
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口 + 路由注册
│   │   ├── api/                       # routers: analyze/tasks/history/settings/health
│   │   ├── core/                      # config/logging/security/rate_limit
│   │   ├── models/                    # pydantic schemas
│   │   ├── services/
│   │   │   ├── github_fetcher.py
│   │   │   ├── context_builder.py
│   │   │   ├── llm_client.py
│   │   │   ├── analysis_engine.py
│   │   │   ├── task_manager.py
│   │   │   ├── history_store.py
│   │   │   └── credentials.py
│   │   └── cli.py                     # key set/status/clear
│   ├── tests/
│   ├── pyproject.toml / requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/ (pages/components/api/sse)
│   ├── package.json / vite.config.ts / tailwind
├── .github/workflows/ci.yml
├── .gitlab-ci.yml
├── docker-compose.yml                 # 便利启动（可选）
├── .env.example
└── .gitignore
```

---

## 12. 范围外（明确不做，防止 subagent 跑偏）
- 不实现用户注册/登录/多租户隔离（单租户部署）；
- 不向 GitHub 回写评论（只读分析）；
- 不做实时 Webhook 自动评审（列为扩展）；
- 不引入任务队列/Redis（进程内 asyncio 任务管理器）；
- 不做 diff 缓存与增量分析（列为扩展）。

