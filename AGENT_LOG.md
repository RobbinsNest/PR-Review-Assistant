# AGENT_LOG — AI PR 评审助手

> 按时间顺序记录关键节点：时间戳与 task 编号、触发的 Superpowers 技能、关键 prompt/context 配置、subagent 输出关键片段或 commit hash、人工干预、学到的教训。

## 2026-08-04

### T-0 项目初始化（brainstorming 阶段）
- **技能**：superpowers:using-superpowers → superpowers:brainstorming → superpowers:writing-plans
- **动作**：读取两份需求文件（通用要求 + 方向B），检查 GitHub 仓库状态（RobbinsNest/PR-Review-Assistant，public、空、main）；完成 6 轮一对一澄清提问并逐节确认设计；产出设计文档并提交。
- **关键决策**：服务端统一 LLM 配置；公网用户会话级自填 GitHub token（不落库）；两阶段"生成-校验"分析管线 + 固定类别枚举 + 定位到 diff 行；上下文 = diff + 函数/类窗口，大 diff 按文件 map-reduce；Python 3.11 + FastAPI + React(Vite+TS) + Docker；SSE 实时进度 + 示例 PR + 历史 + Markdown 导出。
- **commit**：`31ec557`（init）、`8269bba`（spec）、`445f71d`（spec 自审修正）、`d90ddbb`（plan）。

### T-0 环境适配（人工发现并决策）
- **问题**：本机无法连接 `github.com:443`（curl 返回 000），但 `api.github.com` 可通（200）；无代理配置；`gh` CLI 未安装。
- **决策**：本地 git 仅用于 worktree 隔离与开发；所有远程操作（建分支、镜像 commit、开/合 PR）经 GitHub App 连接器（走 api.github.com）完成。GitHub 仓库仍获得完整 commit + PR 历史。
- **教训**：在受限网络环境中，先验证 push 通路再设计执行流程，避免中途卡壳。

### T-0 环境适配（人工决策：Python 版本）
- **问题**：本机默认 Python 3.14；Python 3.11 安装到用户目录后沙箱拒绝执行（仅可经 escalation 运行），本地 TDD 不便。
- **决策（用户确认"下不下都行"）**：本地开发用 3.14 跑测试（`requires-python = ">=3.11"`）；**Docker 与 CI 固定 `python:3.11-slim`**，发行目标仍为 3.11。SPEC/PLAN 已同步更新。

### T-CS 冷启动验证（§4.5，subagent "Locke"）
- **技能**：无（冷启动 agent 仅凭 SPEC+PLAN 自主实现，未加载本会话上下文）。
- **配置**：模型 deepseek-v4-flash（与主 agent 不同）、fork_context=false；任务=T1+T2；规则=遇不确定即暂停报告。
- **结果**：5 测试全绿；提交 c77bf00、1c253fc。**产物按用户要求丢弃**（worktree reset 到 main）。
- **暴露缺陷**：ERROR_HTTP 表位置（T1 引用了 T12 的内容）→ T1 一次性写全；T1 红态描述与实际不符 → 改"红态即可"；pytest 系统 TEMP 被沙箱拒绝 → 全局约束加 .tmp/TEMP 方案；asyncio_mode 缺失 → 写入 T1；Makefile 命令未定义 → 明确；python-multipart 未用 → 移除。
- **教训**：spec 中"跨任务引用"的常量（错误映射表）应就近定义一次，否则冷启动 agent 会自行猜测补全——它猜对了，但不能依赖运气。

### T-0 环境适配（人工发现：本地代理解锁 git push）
- **问题**：直连 github.com:443 不通；但本机 127.0.0.1:7897 有 HTTP 代理（Clash 类），经其可通 github.com（200）。
- **决策**：`git config --global http.https://github.com.proxy http://127.0.0.1:7897`（仅 github.com 作用域）；git 凭据管理器已有凭据，`git push --force origin main` 成功（d787855→3fb71bd）。
- **影响**：放弃"GitHub MCP 镜像 commit"方案，恢复标准 git push + GitHub App 开/合 PR 工作流；后续所有 worktree 均可正常 push。
- **注意**：worktree 内 subagent 若需 push，须在可联网（代理）的 shell 中执行；沙箱内网络受限时用 escalation。

### T1 完成（WT-1 backend-core）
- **技能**：subagent-driven-development（implementer + task reviewer 两阶段评审）。
- **实现**：backend 脚手架（pyproject/Settings/ErrorCode+ERROR_HTTP/logging/health/main/Makefile），commit `d46a065`（implementer: Parfit）。
- **评审**：reviewer Erdos → ✅ spec compliant，0 Critical/Important；Minor 已裁决入 ledger（M5 settings cache 由 T2 顺手修复，M6 setup_logging 推迟到 T12）。
- **教训**：pytest 在本机沙箱需 `--basetemp` + `-p no:cacheprovider`；fastapi 有无害 StarletteDeprecationWarning。

### T2 完成（WT-1 backend-core）
- **技能**：subagent-driven-development（implementer + reviewer）。
- **实现**：pydantic 核心模型（PR/changed file/context、Category/Severity/Finding/FindingCandidate、AnalysisSummary/AnalysisResult）+ test_models.py + conftest M5 fixture；commit `e303357`（implementer: Sagan）。
- **评审**：reviewer Peirce → ✅ spec compliant，0 Critical/Important；minor 入 ledger。

### T3 完成（WT-1 backend-core）
- **技能**：subagent-driven-development。
- **实现**：parse_pr_url + GitHubFetcher（分页/重试/限流错误分类/head 内容 base64 解码）+ tests（32 passed）；commit `76f07d4`（implementer: Galileo）。
- **评审**：reviewer Dewey → ✅ Approved；1 Important 裁决：404→repo_not_found 为 plan 既定（pull_not_found 保留备用）；minor 入 ledger。
- **教训**：评审清单中我写的"(PR endpoint→pull_not_found)"与 plan 自身测试冲突，属评审指令 artifact；裁决以 plan 文本为准。
