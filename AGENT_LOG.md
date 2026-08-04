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

### T4 完成（WT-1 backend-core）
- **技能**：subagent-driven-development（2 轮 fix round + 2 轮 scoped re-review）。
- **实现**：context_builder（hunk 区间/函数窗口/分片）；commits `ab8081c`+`83fa9ab`+`0bccdc5`（implementer: Mendel，fix2: Curie）。
- **评审**：reviewer Ptolemy → 2 Important（Go/Rust func/fn 窗口缺失、Python 多行签名窗口丢失）→ 修复；re-review Wegener 发现 1 个新回归（单行套件吞掉下一函数）→ fix2；Goodall 复核通过。
- **裁决**：plan 修正——语言策略（python 缩进、{} 括号配对、未知±20）、build_analysis_unit 返回 list、truncated 语义。
- **教训**：启发式函数边界是易错区，两次评审共抓出 3 个真实缺陷；tree-sitter 精确解析列为扩展方向的理由更充分了。

### T5 完成 + WT-1 全部完成（backend-core）
- **技能**：subagent-driven-development。
- **实现**：LLMClient（OpenAI 兼容 + JSON schema 校验 + 修复重试 + 传输重试 + 日志脱敏）；commit `77f57fc`（implementer: Jason）。
- **评审**：reviewer Nash → ✅ Approved；minor 入 ledger。
- **WT-1 状态**：T1-T5 全部通过（58 tests green），进入最终全分支评审。

### WT-1 完成并合并（PR #1 backend-core）
- **技能**：subagent-driven-development + finishing-a-development-branch（用户已定每 worktree→PR，故走 Option 2：push + PR）。
- **结果**：T1-T5 全部通过（66 tests），最终评审 clean；分支 `feat/backend-core` @ 15dcb66 已 push，PR #1 已创建。
- **人工裁决汇总**：Python 3.11 目标、404→repo_not_found、T4 语言策略/返回 list/truncated 语义、最终评审 3 Important 修复。

### T6/T10 完成（WT-2/WT-3 并行）
- **技能**：subagent-driven-development（两个 worktree 并行）。
- **实现**：T6 stage1 候选生成 commit d625291（Einstein）；T10 SQLite 历史存储 commit 01a3d7d（Popper）。
- **评审**：T6 → Banach ✅ Approved（minor：真实变更行判定/文件名校验/病态行号收敛 → 已折入 T7 指令）；T10 → Confucius ✅ Approved（T13 需 mkdir data 目录 + 关闭连接）。
- **环境修复**：共享 venv 基线解析到沙箱禁用的 AppData Python 3.11 → 重建 `.venv-shared2`（基线 C:\Python314，沙箱可执行）。

### T7/T11 完成（WT-2/WT-3 并行）
- **技能**：subagent-driven-development。
- **实现**：T7 stage2 校验 commit 6857781（Newton，含 T6 review 折入：真实变更行判定/文件名校验/病态行号收敛；修正 brief 草案测试顺序矛盾）；T11 凭据+设置 commit c375174（Euclid）。
- **评审**：T11 → Mill ✅ Approved（T12 需加 test_cli.py）；T7 评审进行中。

### T7 完成（WT-2）
- **技能**：subagent-driven-development。
- **实现**：stage2 校验 commit 6857781（Newton）；折入 T6 评审项（真实变更行判定/文件名校验/病态行号收敛）；修正 brief 草案测试顺序矛盾（已记录）。
- **评审**：Copernicus ✅ Approved（minor：verify 消息缺 truncated 注记、true_changed_lines 多 hunk 测试 → 折入 T8）。

### T8/T12 完成（WT-2/WT-3 并行）
- **技能**：subagent-driven-development。
- **实现**：T8 stage3+编排器 commit 6f9d64c（Godel，100 tests）；T12 限流+装配 commit 9f9386f（Hume，106 tests，含 aclose/close/test_cli/日志 grep-assert）。
- **评审**：T8 → Avicenna ✅；T12 → James ✅（minor 折入 T9/T13）。
- **注意**：WT-2 与 WT-3 都在改 backend/app/main.py —— 已指示 T9/T13 各自只加自己的 router 并标注 seam，合并时人工调和。

### T9/T13 完成 → WT-2/WT-3 全部完成
- **技能**：subagent-driven-development。
- **实现**：T9 任务管理器+SSE+API commit fa20cfc（Poincare，121 tests）；T13 history API commit ad61075 + fix 5a962d9（McClintock/Boyle，115 tests）。
- **评审**：T9 → Carson ✅（minor：BOM 待清理）；T13 → Turing 1 Important（total 真实计数）→ Boyle 修复 → Chandrasekhar 复核 ✅。
- **状态**：WT-2（T6-T9）与 WT-3（T10-T13）全部完成，进入最终全分支评审。
- **教训**：`total` 分页语义是前端契约关键点，评审抓出"页面大小冒充总数"的缺陷——此类跨层契约要在 SPEC/PLAN 里写死。

### WT-2/WT-3 最终全分支评审（PR #2/#3）
- **技能**：subagent-driven-development 最终评审 + fix wave。
- **WT-2**（analysis-engine）reviewer Noether：**With fixes** — 2 Important（共享 stats 并发竞态、registry/队列无界增长）+ minor（BOM、repair 消息编码待验）→ fix wave（Averroes）。
- **WT-3**（history-settings）reviewer Kierkegaard：**With fixes** — 2 Important（凭据未接入 key 解析、base_url 泄露向量）+ minor → fix wave（Kuhn）。
- **教训**：跨 worktree seam（Settings.api_key vs CredentialStore）和未鉴权 settings 端点是真实的安全/契约漏洞，最终评审抓出——正说明"先 spec 合规再代码质量"两阶段评审的价值。

### WT-2/WT-3 合并（PR #2/#3）
- **技能**：subagent-driven-development + finishing（用户既定每 worktree→PR）。
- **结果**：PR #2（analysis-engine，head 0ab4c4c）与 PR #3（history-settings，head 3163f8e）经最终评审 fix wave 后合并；PR #3 因两分支同改 main.py 产生冲突，用 update-branch 流程（merge origin/main + 人工调和 main.py 合并两个 router + 修复 test_api_analyze 的 rate_limiter fixture）解决；合并树 **192 tests pass**。
- **教训**：并行分支改同一文件（main.py）必然冲突；用"先合一个 PR → 另一个 update-branch 调和 → 全量测试 → 再合"可干净解决；两阶段评审 + 最终评审共抓出 8+ 个真实缺陷（含安全/并发/契约类）。

### T14 完成（WT-4 frontend）
- **技能**：subagent-driven-development。
- **实现**：前端脚手架 commit a586173（Plato）——Vite+React18+TS+Tailwind、api client（9 个函数与后端契约逐字段核对）、SSE client、DESIGN.md（Open Design 契约，中文）。
- **评审**：Linnaeus ✅ Approved（minor：ApiError 携带 code、SSE 404 终止 → 折入 T15）。
- **环境**：npm.ps1 被执行策略禁用 → 用 npm.cmd；沙箱 D:\ 写入在 escalation 后受限 → subagent 用 escalation 完成写入/构建。

### T15 完成（WT-4 frontend）
- **技能**：subagent-driven-development。
- **实现**：HomePage + ProgressPage（SSE）commit 69afe4d（Hypatia）；fix 3eb55d9（Dirac）。
- **评审**：Huygens 1 Important（stage 徽章逻辑倒置：完成阶段标 pending、未来标 done）→ 修复 → Maxwell 复核 ✅。
- **教训**：进度页徽章状态是最容易被写反的 UI 逻辑；补组件测试后此类 bug 不会再溜过。
