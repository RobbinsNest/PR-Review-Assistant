# SPEC_PROCESS — 规约与计划过程记录

> 记录与 Superpowers 协作生成 spec 与 plan 的过程：brainstorming 关键节点、至少 3 轮关键迭代节选与决策、AI 建议的采纳/推翻、反思。

## 1. brainstorming 关键节点（Q&A 摘要）

| # | 问题 | 用户决策 | 影响 |
|---|---|---|---|
| Q1 | 使用形态：单租户自托管 vs 多租户公开服务 | 服务端统一 LLM 配置；公网用户可自填 GitHub token 访问私有仓库 | 无用户体系；token 按会话处理 |
| Q2 | GitHub token 生命周期 / 是否写回 / 公开仓库 | A 会话级（不落库/不写日志）；只读分析；公开仓库免 token | 安全边界清晰，无写权限复杂度 |
| Q3 | 分析深度与误报控制 | B 两阶段"生成-校验"；固定类别枚举；定位到 diff | 管线核心：验证阶段控误报 |
| Q4 | 上下文获取方式 | B diff + 函数/类上下文窗口；接受按文件 map-reduce | 平衡 token 成本与准确性 |
| Q5 | 技术栈与分发 | A Python FastAPI + React + Docker；平台未定取通用一键部署；双 CI（GitHub Actions + .gitlab-ci.yml） | 单体可移植部署 |
| Q6 | Web 交互范围 | C（示例 PR / 历史 / 导出）；SSE 进度必要 | 体验完整度 |

**架构方案选择**：提出 3 个方案（单体 FastAPI + 进程内 asyncio / FastAPI+Celery+Redis / 前后端分离部署），用户采纳**方案 1**——理由：工程深度优先于基础设施堆叠，单体更利于把分析引擎精度与凭据安全做扎实。

**人工修正**：用户将 Python 3.12 改为 **3.11**（技术选型节）。

## 2. 关键迭代节选（3 轮）

### 迭代 1：凭据模型（Q1-Q2）
- 我最初设想"部署者配置 LLM key + 用户绑定自己的 key（加密存储）"；用户明确"服务端统一 LLM 配置、用户只填 GitHub token"。这简化了凭据面：LLM key 是唯一的服务端机密，GitHub token 走会话级。
- **决策**：token 仅内存、请求转发后即弃；公开仓库免 token（未认证 60/h 限额写入 README）。

### 迭代 2：分析管线（Q3-Q4）
- 我提出"单次结构化分析 / 两阶段生成-校验 / 多视角并行"三档；用户选**两阶段**，并要求固定类别枚举 + 定位 diff。
- 用户接受 map-reduce 分片汇总，解决了超大 PR 上下文窗口限制。
- **采纳的 AI 建议**：校验阶段做"三问"（是否本次变更引入 / 是否在变更行内 / 与上下文是否矛盾）+ 置信度修订，作为误报控制的核心机制。

### 迭代 3：架构方案（方案 1-3）
- 用户确认单体 FastAPI + 进程内 asyncio 任务管理器；SSE 推送进度。
- 我把"超大 PR 拒绝/降级"、函数边界启发式 fallback、SSE 反代缓冲列为风险，写入 SPEC §10。

## 3. 冷启动验证记录（§4.5）

- **agent**：fresh-session subagent，模型 deepseek-v4-flash（与主开发 agent 不同），`fork_context=false`，无任何先前会话/memory；仅提供 `SPEC.md` + `PLAN.md`，指定实现 T1、T2，并明确"遇不确定即暂停报告，不凭猜测继续"。
- **结果**：T1、T2 均按 TDD 完成（红→绿→提交），5 个测试全绿；提交 `c77bf00`、`1c253fc`（**产物按要求丢弃，仅保留经验教训**）。

### 暴露的 spec/plan 缺陷与修订（before → after）

| 缺陷 | 冷启动 agent 的处理 | 修订（after） |
|---|---|---|
| `ERROR_HTTP` 映射表只在 T12 定义，T1 却要求实现 | 自行按 T12 表补全，未阻塞 | T1 Produces 一次性写全完整映射表 + 完整错误码枚举（含 not_found/rate_limited），供后续任务直接引用 |
| T1 Step2 期望红态原因描述与实际不符（conftest 在 Step3 才建） | 仍得到真红态，未阻塞 | 期望改为"红态即可（fixture 或 ModuleNotFound）"，明确不要继续实现直到看到失败 |
| pytest 默认临时目录在系统 TEMP，被沙箱拒绝（WinError 5） | 在 worktree 建 `.tmp` 并设 TEMP/TMP 环境变量解决 | PLAN 全局约束补充：测试前建 `.tmp` 并设 `$env:TEMP/$env:TMP`（或 `--basetemp`） |
| `asyncio_mode` 未在 T1 说明，但 T3 起需要 | 主动在 pyproject 加 `asyncio_mode = "auto"` | 已写入 T1 pyproject 描述 |
| `Makefile` test 命令未给出 | 按 T17 的直觉命令实现 | T1 明确三个 make 目标的具体命令 |
| `python-multipart` 标注"（如需）" | 判定不需要，未声明 | 从依赖列表移除，避免与安装环境不一致 |

### 解读一致性
- 冷启动 agent 的解读与原意**一致**：模块边界、TDD 顺序、commit message 均与 PLAN 吻合；无"读错 spec"的情况。
- 产出与预期差距：**小**（仅 5 个测试的脚手架+模型层，符合任务范围）；其主动补充（asyncio_mode、ERROR_HTTP 补全）均属合理工程判断，已吸收进 PLAN。

## 4. 待补记录
- [ ] 各 task 实现过程的 subagent 记录与人工干预（随实现推进持续更新）。
