---
version: alpha
name: PR Review Assistant
description: AI 驱动的 GitHub PR 评审助手 —— 赛博朋克夜城风（暗色工具界面 + 克制霓虹青/品红）
colors:
  primary: "#22D3EE"
  primary-strong: "#06B6D4"
  primary-weak: "#103A4E"
  accent: "#F472B6"
  accent-strong: "#EC4899"
  surface: "#121A2B"
  surface-subtle: "#0A0E1A"
  ink: "#E6EDF7"
  ink-secondary: "#9FB0C9"
  ink-muted: "#64748B"
  line: "#1F2A44"
  line-strong: "#33415E"
  success: "#34D399"
  warning: "#FBBF24"
  error: "#F87171"
  info: "#22D3EE"
  severity-critical: "#F87171"
  severity-major: "#FB923C"
  severity-minor: "#FBBF24"
  severity-nit: "#94A3B8"
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
    letterSpacing: 0.01em
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
    textColor: "#0A0E1A"
    rounded: "{rounded.md}"
    padding: "8px 16px"
    glow: "glow-cyan"
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
    textColor: "#0A0E1A"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
  input-focus:
    borderColor: "{colors.primary}"
    glow: "glow-cyan"
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
    glow: "glow-cyan"
  nav-active:
    backgroundColor: "{colors.primary-weak}"
    textColor: "{colors.primary}"
    glow: "glow-magenta"
---

# PR Review Assistant — 设计契约（DESIGN.md）

> 本文件是仓库内所有视觉与交互决策的单一事实来源，遵循 Open Design 的 `DESIGN.md` 约定（design.md 开放格式：YAML frontmatter 承载机器可读 token，正文承载使用指南）。前端实现必须按本契约落地：机器可读 token 落在 `frontend/src/styles/theme.css`，Tailwind 通过 `frontend/tailwind.config.js` 消费。
>
> **铁律：修改任何视觉 token 时，必须先同步更新本文件与 `theme.css`，再考虑组件。**

## 1. Overview（品牌与气质）

PR Review Assistant 是一款面向工程师的 AI 评审工具：用户粘贴 PR 链接，系统抓取变更、并行分析、产出定位到文件行的风险发现，并以 SSE 实时推送进度。当前主题为**经典霓虹夜城（赛博朋克）**——近黑蓝的暗色基底上，以霓虹青为主操作、霓虹品红为点缀，霓虹只做**克制强调**：

- **克制**：暗色工具界面，霓虹仅限交互强调（主按钮、进度条、活动导航、focus）；装饰元素必须为信息让路。
- **工具化**：主内容是 diff、findings、任务状态；左对齐、密度适中、可扫读；正文对比度优先。
- **可信**：错误与严重度有明确语义色（暗底上整体提亮）；状态变化即时反馈；不炫技、不闪烁。

## 2. Colors（色彩）

### 2.1 调色板

以近黑蓝中性色为基底，霓虹青为唯一品牌主色，霓虹品红为点缀色，语义色只表达状态（暗底亮化保证对比度）。

| Token（CSS 变量） | 值 | 用途 |
| --- | --- | --- |
| `--color-primary` | `#22D3EE` | 品牌主色（霓虹青）：主操作按钮、进度条、链接、focus |
| `--color-primary-strong` | `#06B6D4` | primary 的 hover/按下态 |
| `--color-primary-weak` | `#103A4E` | 选中/激活底色、弱强调背景（暗青） |
| `--color-accent` | `#F472B6` | 点缀色（霓虹品红）：活动导航、选中态、risk_highlights |
| `--color-accent-strong` | `#EC4899` | accent 的 hover/按下态 |
| `--color-surface` | `#121A2B` | 卡片、输入框、页面容器（暗蓝面板） |
| `--color-surface-subtle` | `#0A0E1A` | 页面背景（近黑蓝，带顶部极淡青色氛围光） |
| `--color-ink` | `#E6EDF7` | 主文本（亮蓝白） |
| `--color-ink-secondary` | `#9FB0C9` | 次要文本、说明 |
| `--color-ink-muted` | `#64748B` | 占位符、元数据（仅次要信息） |
| `--color-line` | `#1F2A44` | 默认描边/分隔线（带蓝调） |
| `--color-line-strong` | `#33415E` | 强调描边（如 secondary 按钮） |
| `--color-success` | `#34D399` | 成功状态 |
| `--color-warning` | `#FBBF24` | 警告状态 |
| `--color-error` | `#F87171` | 错误状态、破坏性操作 |
| `--color-info` | `#22D3EE` | 信息提示（与 primary 同源） |

### 2.2 严重度（finding severity）

| Token（CSS 变量） | 值 | 用途 |
| --- | --- | --- |
| `--color-severity-critical` | `#F87171` | critical（红） |
| `--color-severity-major` | `#FB923C` | major（橙） |
| `--color-severity-minor` | `#FBBF24` | minor（琥珀黄） |
| `--color-severity-nit` | `#94A3B8` | nit（灰蓝） |

### 2.3 使用规则

- 霓虹青/品红只用于**交互强调**，正文与大面积背景不使用高饱和霓虹；
- 语义色在暗底上提亮（400 级），保证与 `--color-ink` 的对比度 ≥ 4.5:1；
- 状态/严重度色只表达状态，不得挪作品牌装饰。

## 3. Typography（字体）

- **sans**：Inter → system-ui → 系统中文字体（PingFang SC / Microsoft YaHei）→ `system-ui` 兜底。用于全部界面文本。
- **mono**：`ui-monospace` 栈（SFMono / Menlo / Consolas）。用于 diff、代码、URL、哈希、数字 ID 等需要对齐的技术内容。

| 层级 | 字号 | 字重 | 行高 | 用途 |
| --- | --- | --- | --- | --- |
| display | 30px | 600 | 1.25 | 页面主标题（首页），`letter-spacing: -0.02em` |
| title | 20px | 600 | 1.4 | 区块/卡片标题，`letter-spacing: 0.01em`（轻微数字感） |
| body | 14px | 400 | 1.6 | 正文、列表 |
| caption | 12px | 500 | 1.5 | 标签、时间、元数据 |
| mono | 13px | 400 | 1.5 | diff/代码/URL/哈希 |

规则：一个界面最多两种字族、三种字重；正文不细于 400；中文文本避免斜体。不引入外部 Web 字体（保持自包含/离线可用）。

## 4. Layout & Spacing（布局与间距）

- **4px 基准刻度**：`--space-1`（4px）→ `--space-16`（64px）。间距一律取自刻度，禁止随手写。
- **页面容器**：内容最大宽度 1120px，左右留白 24px（`--space-6`）。
- **对齐**：工具类界面默认左对齐；大段文本避免通栏居中。
- **卡片**：内边距 24px（`--space-6`），卡片间距 16px（`--space-4`）。
- **表单**：输入框纵向堆叠，间距 12px（`--space-3`）。

## 5. Elevation & Depth（层级与阴影）

保持扁平：层级主要靠「背景色差 + 描边」表达。**霓虹辉光是本主题允许的层级工具，但仅限交互强调**：

- 卡片：`surface` 暗蓝底 + 1px `line` 描边；不默认加阴影。
- 悬浮提升：hover 时加深描边或加一层极轻阴影（`0 0 0 1px rgb(var(--color-primary) / 0.35)`）。
- **霓虹辉光**：仅允许以下位置（工具类 `glow-cyan` / `glow-magenta`）：主按钮、进度条填充、活动导航/选中态、focus ring。**禁止**在正文、卡片、非交互元素上使用辉光。
- 禁止大而模糊的弥散阴影、全身发光。

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
| **Button** | primary（霓虹青底 + 近黑文字 + `glow-cyan`）/ secondary（暗蓝底 + `line-strong` 描边）/ ghost（透明）/ danger（`error` 红底 + 近黑文字）。高度 36px（默认）/ 32px（紧凑）；圆角 `md`；hover 加深（primary 用 `primary-strong`）；disabled：50% 不透明度 + `cursor-not-allowed`。 |
| **Input / Textarea** | `surface` 暗蓝底、1px `line` 描边、圆角 `md`、内边距 8px 12px；focus：描边转 `primary` + 2px `primary/30%` ring + `glow-cyan`；错误态：`error` 描边 + 错误文案。密码类输入 `autocomplete="off"`。 |
| **Card** | `surface` 暗蓝底、1px `line` 描边、圆角 `lg`、内边距 24px。 |
| **Badge（severity/stage）** | 语义色 10% 背景 + 语义色文字 + `radius-full` + 内边距 2px 8px；caption 字号。 |
| **ProgressBar** | 轨道 `line` 色、填充 `primary`（霓虹青 + `glow-cyan`），高 8px，圆角 `full`；文案显示 `done/total` 与阶段名。 |
| **NavBar** | 顶部，`surface` 暗蓝底，底部 1px `line` 分割线；左侧品牌名，右侧导航链接；**活动链接：`primary-weak` 底 + `primary` 文字 + `glow-magenta`**。 |
| **DiffViewer** | `mono` 字体；行号 `ink-muted`；新增行 `+`（绿）、删除行 `-`（红）；findings 命中的行以严重度色 10% 背景高亮。 |
| **状态提示** | 错误：`error` 语义色 + 可操作的「重试/重新开始」链接；加载：稳定进度或骨架屏，避免闪烁。 |

## 8. Do's and Don'ts（反 AI 味自查清单）

### Do（应当）

- ✅ 左对齐为主，信息优先、装饰最少
- ✅ 每屏一个 primary 主操作（霓虹青）
- ✅ 颜色有语义，严重度/状态一眼可辨（暗底亮化）
- ✅ 霓虹辉光只用于交互强调（主按钮/进度/活动导航/focus）
- ✅ 间距、圆角、字号一律取自 token 刻度
- ✅ 关键数据用等宽字体（URL、哈希、行号）
- ✅ 错误信息给出原因与可操作的重试路径

### Don't（禁止，即「AI 味」红线）

- ❌ 大面积渐变、彩虹/日落渐变背景（背景只允许顶部极淡青色氛围光）
- ❌ 玻璃拟态、弥散大阴影、正文/卡片霓虹发光
- ❌ 扫描线/故障闪烁等无意义动画、动效炫技
- ❌ 用装饰性 emoji 代替图标（如需图标用语义化 SVG/字符）
- ❌ 大段通栏居中排版、营销腔文案
- ❌ 为填满页面而加的无信息卡片、图表、插画
- ❌ 圆角/阴影/字号随手混用（如卡片 4px、按钮 16px）
- ❌ 默认「现代 SaaS 紫」观感
- ❌ 正文对比度不足（< 4.5:1）
- ❌ 在组件中硬编码颜色/间距（绕过 token）

## 9. 前端落地（Implementation）

- **token 落点**：`frontend/src/styles/theme.css` 定义 CSS 变量（RGB 三元组，便于 Tailwind 透明度修饰符）；`frontend/tailwind.config.js` 的 `theme.extend.colors / spacing / borderRadius` 指向这些变量。
- **辉光工具类**：`theme.css` 的 `@layer utilities` 提供 `glow-cyan` / `glow-magenta`，组件在语义类基础上追加（如 `bg-primary glow-cyan`）。
- **消费方式**：组件优先使用语义化工具类，如 `bg-surface`、`text-ink`、`text-ink-secondary`、`border-line`、`bg-primary`、`text-error`、`bg-severity-critical/10`、`rounded-md`、`p-4`、`gap-3`。
- **新增 token**：先在本文件与 `theme.css` 同步新增，再在 `tailwind.config.js` 暴露，最后才允许在组件中使用。
