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
