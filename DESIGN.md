---
version: alpha
name: PR Review Assistant
description: AI 驱动的 GitHub PR 评审助手 —— 克制、工具化的浅色开发者工具界面
colors:
  primary: "#3B82F6"
  primary-strong: "#2563EB"
  primary-weak: "#EFF6FF"
  surface: "#FFFFFF"
  surface-subtle: "#F8FAFC"
  ink: "#0F172A"
  ink-secondary: "#475569"
  ink-muted: "#94A3B8"
  line: "#E2E8F0"
  line-strong: "#CBD5E1"
  success: "#16A34A"
  warning: "#D97706"
  error: "#DC2626"
  info: "#2563EB"
  severity-critical: "#DC2626"
  severity-major: "#EA580C"
  severity-minor: "#CA8A04"
  severity-nit: "#64748B"
typography:
  display:
    fontFamily: "Inter, system-ui, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 30px
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: -0.02em
  title:
    fontFamily: "Inter, system-ui, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Inter, system-ui, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  caption:
    fontFamily: "Inter, system-ui, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.5
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
spacing:
  "1": 4px
  "2": 8px
  "3": 12px
  "4": 16px
  "5": 20px
  "6": 24px
  "8": 32px
  "10": 40px
  "12": 48px
  "16": 64px
rounded:
  sm: 4px
  md: 8px
  lg: 12px
  full: 9999px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.line-strong}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  input-focus:
    borderColor: "{colors.primary}"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    rounded: "{rounded.lg}"
    padding: "24px"
  badge-severity:
    rounded: "{rounded.full}"
    padding: "2px 8px"
  progress-track:
    backgroundColor: "{colors.line}"
    rounded: "{rounded.full}"
  progress-fill:
    backgroundColor: "{colors.primary}"
    rounded: "{rounded.full}"
---

# PR Review Assistant — 设计契约（DESIGN.md）

> 本文件是仓库内所有视觉与交互决策的单一事实来源，遵循 Open Design 的 `DESIGN.md` 约定（design.md 开放格式：YAML frontmatter 承载机器可读 token，正文承载使用指南）。前端实现必须按本契约落地：机器可读 token 落在 `frontend/src/styles/theme.css`，Tailwind 通过 `frontend/tailwind.config.js` 消费。
>
> **铁律：修改任何视觉 token 时，必须先同步更新本文件与 `theme.css`，再考虑组件。**

## 1. Overview（品牌与气质）

PR Review Assistant 是一款面向工程师的 AI 评审工具：用户粘贴 PR 链接，系统抓取变更、并行分析、产出定位到文件行的风险发现，并以 SSE 实时推送进度。界面必须服务于这个任务——**克制、工具化、可信**：

- **克制**：默认浅色，中性灰蓝基底 + 单一品牌蓝；装饰性元素必须为信息让路。
- **工具化**：主内容是 diff、findings、任务状态；左对齐、密度适中、可扫读。
- **可信**：错误与严重度有明确语义色；状态变化即时反馈；不夸大、不炫技。

## 2. Colors（色彩）

### 2.1 调色板

以 slate 系中性色为基底，蓝色为唯一品牌色，语义色只表达状态。

| Token（CSS 变量） | 值 | 用途 |
| --- | --- | --- |
| `--color-primary` | `#3B82F6` | 品牌主色：主操作按钮、进度条、链接 |
| `--color-primary-strong` | `#2563EB` | primary 的 hover/按下态 |
| `--color-primary-weak` | `#EFF6FF` | 选中/激活底色、弱强调背景 |
| `--color-surface` | `#FFFFFF` | 卡片、输入框、页面容器 |
| `--color-surface-subtle` | `#F8FAFC` | 页面背景、分区背景 |
| `--color-ink` | `#0F172A` | 主文本 |
| `--color-ink-secondary` | `#475569` | 次要文本、说明 |
| `--color-ink-muted` | `#94A3B8` | 占位符、元数据（仅次要信息） |
| `--color-line` | `#E2E8F0` | 默认描边/分隔线 |
| `--color-line-strong` | `#CBD5E1` | 强调描边（如 secondary 按钮） |
| `--color-success` | `#16A34A` | 成功状态 |
| `--color-warning` | `#D97706` | 警告状态 |
| `--color-error` | `#DC2626` | 错误状态、破坏性操作 |
| `--color-info` | `#2563EB` | 信息提示 |

### 2.2 Finding 严重度映射

findings 的严重度固定为 `critical / major / minor / nit`，颜色映射如下：

| 严重度 | Token | 值 | 语义 |
| --- | --- | --- | --- |
| critical | `--color-severity-critical` | `#DC2626` | 阻断性缺陷/安全问题 |
| major | `--color-severity-major` | `#EA580C` | 主要问题 |
| minor | `--color-severity-minor` | `#CA8A04` | 次要问题 |
| nit | `--color-severity-nit` | `#64748B` | 风格/可读性小问题 |

严重度徽章统一使用「语义色 10% 透明背景 + 语义色文字」；diff 高亮行使用严重度色 10% 背景。

### 2.3 色彩规则

- 正文对背景对比度 ≥ 4.5:1（WCAG AA）；`ink-muted` 仅用于非关键信息。
- 每个屏幕最多一个 primary 操作按钮；错误色只表达错误，不用作装饰。
- 颜色必须来自 token；禁止在组件里硬编码色值。

## 3. Typography（字体）

- **sans**：`Inter`（拉丁）→ 系统中文字体（PingFang SC / Microsoft YaHei）→ `system-ui` 兜底。用于全部界面文本。
- **mono**：`ui-monospace` 栈（SFMono / Menlo / Consolas）。用于 diff、代码、URL、哈希、数字 ID 等需要对齐的技术内容。

| 层级 | 字号 | 字重 | 行高 | 用途 |
| --- | --- | --- | --- | --- |
| display | 30px | 600 | 1.25 | 页面主标题（首页） |
| title | 20px | 600 | 1.4 | 区块/卡片标题 |
| body | 14px | 400 | 1.6 | 正文、列表 |
| caption | 12px | 500 | 1.5 | 标签、时间、元数据 |
| mono | 13px | 400 | 1.5 | diff/代码/URL/哈希 |

规则：一个界面最多两种字族、三种字重；正文不细于 400；中文文本避免斜体。

## 4. Layout & Spacing（布局与间距）

- **4px 基准刻度**：`--space-1`（4px）→ `--space-16`（64px）。间距一律取自刻度，禁止随手写。
- **页面容器**：内容最大宽度 1120px，左右留白 24px（`--space-6`）。
- **对齐**：工具类界面默认左对齐；大段文本避免通栏居中。
- **卡片**：内边距 24px（`--space-6`），卡片间距 16px（`--space-4`）。
- **表单**：输入框纵向堆叠，间距 12px（`--space-3`）。

## 5. Elevation & Depth（层级与阴影）

保持扁平：层级主要靠「背景色差 + 描边」表达，阴影克制。

- 卡片：`surface` 白底 + 1px `line` 描边；不默认加阴影。
- 悬浮提升：hover 时加一层极轻阴影（如 `0 1px 2px rgb(0 0 0 / 0.06)`）或加深描边。
- 禁止大而模糊的弥散阴影、霓虹发光。

## 6. Shapes（形状）

| Token | 值 | 用途 |
| --- | --- | --- |
| `--radius-sm` | 4px | 小元素、标签 |
| `--radius-md` | 8px | 按钮、输入框 |
| `--radius-lg` | 12px | 卡片、容器 |
| `--radius-full` | 9999px | 徽章、进度条、胶囊 |

同一视图中不混用锐角与圆角；交互元素至少 `radius-md`。

## 7. Components（组件规范）

| 组件 | 规范 |
| --- | --- |
| **Button** | primary（蓝底白字）/ secondary（白底 + `line-strong` 描边）/ ghost（透明）/ danger（红底白字）。高度 36px（默认）/ 32px（紧凑）；圆角 `md`；hover 加深（primary 用 `primary-strong`）；disabled：50% 不透明度 + `cursor-not-allowed`。 |
| **Input / Textarea** | `surface` 白底、1px `line` 描边、圆角 `md`、内边距 8px 12px；focus：描边转 `primary` + 2px `primary/30%` ring；错误态：`error` 描边 + 错误文案。密码类输入 `autocomplete="off"`。 |
| **Card** | `surface` 白底、1px `line` 描边、圆角 `lg`、内边距 24px。 |
| **Badge（severity/stage）** | 语义色 10% 背景 + 语义色文字 + `radius-full` + 内边距 2px 8px；caption 字号。 |
| **ProgressBar** | 轨道 `line` 色、填充 `primary`，高 8px，圆角 `full`；文案显示 `done/total` 与阶段名。 |
| **NavBar** | 顶部，`surface` 白底，底部 1px `line` 分割线；左侧品牌名，右侧导航链接。 |
| **DiffViewer** | `mono` 字体；行号 `ink-muted`；新增行 `+`（绿）、删除行 `-`（红）；findings 命中的行以严重度色 10% 背景高亮。 |
| **状态提示** | 错误：`error` 语义色 + 可操作的「重试」链接；加载：稳定进度或骨架屏，避免闪烁。 |

## 8. Do's and Don'ts（反 AI 味自查清单）

### Do（应当）

- ✅ 左对齐为主，信息优先、装饰最少
- ✅ 每屏一个 primary 主操作
- ✅ 颜色有语义，严重度/状态一眼可辨
- ✅ 间距、圆角、字号一律取自 token 刻度
- ✅ 关键数据用等宽字体（URL、哈希、行号）
- ✅ 错误信息给出原因与可操作的重试路径

### Don't（禁止，即「AI 味」红线）

- ❌ 紫色→蓝色渐变、彩虹/日落渐变背景，或大面积渐变
- ❌ 玻璃拟态、霓虹发光、弥散大阴影
- ❌ 用装饰性 emoji 代替图标（如需图标用语义化 SVG/字符）
- ❌ 大段通栏居中排版、营销腔文案
- ❌ 为填满页面而加的无信息卡片、图表、插画
- ❌ 圆角/阴影/字号随手混用（如卡片 4px、按钮 16px）
- ❌ 默认「现代 SaaS 紫」观感、无意义动画
- ❌ 正文对比度不足（< 4.5:1）
- ❌ 在组件中硬编码颜色/间距（绕过 token）

## 9. 前端落地（Implementation）

- **token 落点**：`frontend/src/styles/theme.css` 定义 CSS 变量（RGB 三元组，便于 Tailwind 透明度修饰符）；`frontend/tailwind.config.js` 的 `theme.extend.colors / spacing / borderRadius` 指向这些变量。
- **消费方式**：组件优先使用语义化工具类，如 `bg-surface`、`text-ink`、`text-ink-secondary`、`border-line`、`bg-primary`、`text-error`、`bg-severity-critical/10`、`rounded-md`、`p-4`、`gap-3`。
- **新增 token**：先在本文件与 `theme.css` 同步新增，再在 `tailwind.config.js` 暴露，最后才允许在组件中使用。