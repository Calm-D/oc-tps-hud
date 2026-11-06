# oc-tps-hud

在 OpenCode 桌面版窗口角落显示**实时输出速度（tokens/s）**的小浮层。背景透明、只有文字，贴在客户端右下角，跟着窗口走。

![screenshot](docs/screenshot-bar.png)

两种布局，配置项 `layout` 切换：

| `bar`（默认，一行细长条） | `block`（四行方块） |
|---|---|
| ![bar](docs/screenshot-bar.png) | ![block](docs/screenshot.png) |

> **非官方项目。** 与 OpenCode 的作者无关，不使用其商标作为产品名。

## 它是什么

- 一个**独立小程序**，不是 OpenCode 插件，不改它的代码、不注入它的进程。
- **只读**它自己的本地 SQLite（`opencode.db`），不写库、不联网、无遥测。
- 数据来源是 OpenCode 自己记录的 token 数与时间戳，不是估算 token；只有流式过程中的瞬时值才是估算。

## 当前支持范围

| 项 | 状态 |
|---|---|
| 操作系统 | **仅 Windows**（窗口跟随、色键透明、取色都依赖 Win32） |
| 客户端 | OpenCode **桌面版**（靠窗口定位，CLI 不适用） |
| 数据库结构 | 需要 `session` / `message` / `part` 三张表（见 [docs/DATA-MODEL.md](docs/DATA-MODEL.md)） |
| 已验证版本 | OpenCode 桌面版 1.19.0（2026-10） |
| Python | 3.9+，且带 `tkinter`（python.org 官方安装包自带；Microsoft Store 版没有） |

结构不匹配时不会静默显示 0，而是直接提示“数据库结构不支持”，并在 `error.log` 记下缺了哪张表。

## 怎么算的

OpenCode 把一次模型调用拆成若干 part：

```
message(assistant) = 一步
  ├─ step-start        起点时间
  ├─ reasoning / text  流式文本
  └─ step-finish       tokens.output + tokens.reasoning + 结束时间
```

- **精确值**（一步结束后）：`(output + reasoning) / (finish - start)`，含首字延迟，不含工具执行时间。
- **实时值**（生成过程中）：`Δ加权字符 × 校准系数 / Δt`。
  - 加权字符：CJK 记 1，其它记 0.25；
  - 4 秒滑窗 + 指数平滑（0.55/0.45），静默时按 0.75 衰减；
  - 校准系数按模型在线学习（`calibration.json`），两三个步骤后即贴近真实值。
- **第二行显示的“近 8 步中位”**：单步速度的中位数，比加权平均更抗“某一步卡在工具上”的拖累。

只统计输出侧，不含输入 token，也不等于花费。

## 安装与运行

需要带 tkinter 的 Python。

```bash
git clone <this repo>
cd oc-tps-hud
python oc-tps-hud.pyw          # 无控制台窗口
# 或
python -m venv .venv && .venv/Scripts/pip install -e .
oc-tps-hud
```

数据库默认自动探测，顺序为：

1. `--db` 参数
2. 环境变量 `OPENCODE_DB`
3. `$XDG_DATA_HOME/opencode/opencode.db`
4. `~/.local/share/opencode/opencode.db`
5. Windows 额外尝试 `%LOCALAPPDATA%\opencode\opencode.db`
6. macOS 额外尝试 `~/Library/Application Support/opencode/opencode.db`

## 窗口层级

默认把浮层登记为 OpenCode 窗口的**附属窗口**（owned window），行为是：

- 永远压在 OpenCode 之上（客户端在动，它就跟着浮在上面）；
- 你切到浏览器、游戏、别的程序时，它**跟着 OpenCode 一起退到后面**，不会盖住别人；
- OpenCode 最小化时它一起隐藏，还原时再出现。

位置默认贴在**输入框上方那条空隙里**（距窗口底边 12 + `bottom_offset` 像素），不会压住发送按钮等控件。
条形自带一层与背景同色的底板（颜色实时取自窗口底下的像素），所以即使正文滚到它下面，
也不会出现两层文字糊在一起的情况。
觉得高了或低了：右键菜单「整体上移 / 下移 20px」，调完自动记住。

如果确实希望它在任何程序之上，右键勾选「始终置顶（会盖住其他程序）」，等价于配置 `topmost: true`。

## 退出与重启

- **退出**：右键点在文字上 → 退出。进程结束，OpenCode 不受任何影响。
- **重启**：退出后再双击入口（桌面图标或 `oc-tps-hud.pyw`）。
- **取消开机自启**：删掉启动文件夹里的 `OpenCode-TPS.pyw`；不影响程序本体。

## 配置

首次运行会在下列位置创建配置目录，可手改 `config.json`（改完重启生效）：

- Windows：`%APPDATA%\oc-tps-hud\`
- 其它：`$XDG_CONFIG_HOME/oc-tps-hud/` 或 `~/.config/oc-tps-hud/`

| 键 | 默认 | 说明 |
|---|---|---|
| `layout` | `"bar"` | `bar` 一行细长条（居中）/ `block` 四行方块 |
| `follow` | `"br"` | `br` 右下 / `bl` 左下 / `custom` 自定义位置（仍跟随）/ `free` 不跟随 |
| `theme` | `"auto"` | `auto` 按窗口底下亮度切换 / `light` / `dark` |
| `alpha` | `0.95` | 0.5 ~ 1.0 |
| `topmost` | `false` | `true` = 盖住所有程序；`false` = 只压在客户端之上 |
| `language` | `"auto"` | `auto` / `zh` / `en` |
| `db_path` | `""` | 空 = 自动探测 |
| `poll_ms` | `400` | 刷新间隔 |
| `window` | `{width:268,height:128,bar_width:640,bar_height:26,margin:12,bottom_offset:112}` | 两种布局各自的尺寸，以及距底边的抬升量（避开输入框） |
| `fonts` | `{ui:"",number:""}` | 空 = 按平台选择（Win 雅黑 / mac PingFang / Linux Noto） |
| `client_min_size` | `[480,360]` | 小于此尺寸的窗口不认作客户端主窗口 |
| `debug` | `false` | 预留 |

右键菜单可切换停靠方式、配色、置顶、不透明度，选择会写回配置。

## 命令行

```bash
python -m oc_tps --dump        # 不显示界面，把状态打到终端（排查用）
python -m oc_tps --db D:\path\to\opencode.db
python -m oc_tps --lang en
python -m oc_tps --version
```

## 已知限制

- **仅 Windows**。Linux/macOS 需要另写窗口后端（`ui_win.py` 已与计算逻辑分离，替换即可）。
- **仅桌面版**。CLI 用户请等官方 V2 的内置 `session.tps`，或使用 TUI 插件。
- 数据库结构由上游决定，大版本升级后可能失效——失效时会明确报错，不会假装有数据。
- 同时开多个会话时，只跟踪最近有活动的那个。
- 背景透明意味着**空白处点击穿透**：右键菜单和拖动需要点在文字或左侧圆点上。
- 拖动浮层会把停靠方式切成「自由摆放」并记住，想恢复跟随要在右键菜单里重选。
- 未提供官方打包产物；需要单文件 exe 可自行用 PyInstaller 打包。

## 开发

```bash
python -m unittest discover -s tests -v      # 纯逻辑单测，19 项，不依赖数据库
python tests/smoke_windows.py                # Windows 手工冒烟，19 项
python tests/smoke_windows.py --no-ui        # 只测数据与配置，不开窗口
```

冒烟测试需要本机正在运行的 OpenCode 桌面版，且**不会**写 OpenCode 的任何文件、也不会改动你的
`config.json`（写配置被临时屏蔽）。它覆盖：配置读写与深合并、schema 探测、结构不符报错、
中英文案、窗口创建与可见性、右下/左下停靠、跟随移动、最小化联动、9 种状态渲染、文案截断策略。

计算部分是纯函数（`engine.py`），测试不依赖数据库；界面与数据源分离，便于替换后端。

```
src/oc_tps/
  config.py    配置与跨平台目录
  strings.py   en / zh 文案
  source.py    读库 + schema 探测
  engine.py    速度计算（纯函数 + 状态机）
  ui_win.py    Windows 浮层后端
  logs.py      本地日志
  __main__.py  命令行入口
tests/         纯逻辑单测
docs/          数据结构说明、截图
```

## 隐私

- 只以只读方式打开数据库，`PRAGMA query_only=1`。
- 不联网、不上报、不写 OpenCode 的任何文件。
- 日志与配置只存在于本机配置目录。

## 许可

MIT，见 [LICENSE](LICENSE)。

---

## English summary

`oc-tps-hud` is a tiny always-on-top overlay that shows OpenCode Desktop's output throughput (tokens/s) by reading its local SQLite database **read-only**. It is not a plugin, does not patch OpenCode, and never touches the network.

Windows only (Win32 window tracking + color-key transparency). Requires Python 3.9+ with tkinter. Exact per-step rates come from `step-finish` token counts; in-flight values are a calibrated character-based estimate. Configuration lives in `%APPDATA%\oc-tps-hud\config.json` (or `~/.config/oc-tps-hud/`).

MIT licensed. Not affiliated with OpenCode.
