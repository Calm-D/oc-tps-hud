"""界面文案。默认跟随系统语言，可在 config.json 里用 language 强制指定。"""

import locale
import os

STRINGS = {
    "zh": {
        "state.run": "生成",
        "state.ttft": "等首字",
        "state.wait": "工具中",
        "state.done": "完成",
        "state.queue": "已发送",
        "state.idle": "空闲",
        "state.error": "数据库忙，重试中",
        "state.nodata": "未找到 OpenCode 数据",
        "state.noschema": "数据库结构不支持",
        "hint.start": "请确认客户端已启动",
        "hint.version": "请检查 OpenCode 版本（见 README）",
        "hint.retry": "稍后自动重试",
        "line.step": "本步 {tok} tok · {time}",
        "line.elapsed": "已用 {time}",
        "line.recent": "近 {n} 步中位 {v} tok/s",
        "line.last": "上步 {v} tok/s",
        "line.none": "尚无样本",
        "line.idle": "等待新任务",
        "unit": "tok/s",
        "menu.follow_br": "贴住客户端 · 右下角",
        "menu.follow_bl": "贴住客户端 · 左下角",
        "menu.follow_free": "自由摆放（不跟随）",
        "menu.theme_auto": "配色 · 自动",
        "menu.theme_light": "配色 · 浅底",
        "menu.theme_dark": "配色 · 深底",
        "menu.topmost": "置顶显示 / 取消",
        "menu.alpha": "不透明度 95% / 100%",
        "menu.quit": "退出",
        "err.platform": "当前版本仅支持 Windows（窗口跟随依赖 Win32）。",
        "err.title": "oc-tps-hud",
        "err.notk": "未找到 tkinter，请安装带 Tk 的 Python（python.org 版自带）。",
        "err.nodb": "未找到 opencode.db。可用 --db 或环境变量 OPENCODE_DB 指定路径。",
        "err.schema": "OpenCode 数据库结构与该版本不匹配：{detail}",
        "err.json1": "当前 SQLite 缺少 JSON1 扩展，无法解析消息内容。",
    },
    "en": {
        "state.run": "Generating",
        "state.ttft": "Waiting first token",
        "state.wait": "Tool running",
        "state.done": "Done",
        "state.queue": "Queued",
        "state.idle": "Idle",
        "state.error": "DB busy, retrying",
        "state.nodata": "No OpenCode data",
        "state.noschema": "Unsupported schema",
        "hint.start": "Make sure the client is running",
        "hint.version": "Check your OpenCode version (see README)",
        "hint.retry": "Will retry automatically",
        "line.step": "{tok} tok · {time}",
        "line.elapsed": "elapsed {time}",
        "line.recent": "median of last {n}: {v} tok/s",
        "line.last": "last {v} tok/s",
        "line.none": "no samples yet",
        "line.idle": "waiting for a task",
        "unit": "tok/s",
        "menu.follow_br": "Dock · bottom right",
        "menu.follow_bl": "Dock · bottom left",
        "menu.follow_free": "Free position",
        "menu.theme_auto": "Theme · auto",
        "menu.theme_light": "Theme · light",
        "menu.theme_dark": "Theme · dark",
        "menu.topmost": "Always on top",
        "menu.alpha": "Opacity 95% / 100%",
        "menu.quit": "Quit",
        "err.platform": "This build supports Windows only (Win32 window tracking).",
        "err.title": "oc-tps-hud",
        "err.notk": "tkinter not found. Install a Python build with Tk (python.org builds include it).",
        "err.nodb": "opencode.db not found. Use --db or the OPENCODE_DB environment variable.",
        "err.schema": "OpenCode database schema mismatch: {detail}",
        "err.json1": "SQLite lacks the JSON1 extension, cannot parse messages.",
    },
}


def detect_language(pref="auto"):
    if pref in STRINGS:
        return pref
    env = os.environ.get("OC_TPS_LANG", "").strip().lower()
    if env.startswith("zh"):
        return "zh"
    if env.startswith("en"):
        return "en"
    try:
        lang = (locale.getdefaultlocale()[0] or "").lower()
    except Exception:
        lang = ""
    return "zh" if lang.startswith("zh") else "en"


class Translator:
    def __init__(self, lang):
        self.lang = lang if lang in STRINGS else "zh"
        self.table = STRINGS[self.lang]

    def __call__(self, key, **kw):
        text = self.table.get(key) or STRINGS["zh"].get(key) or key
        if kw:
            try:
                return text.format(**kw)
            except Exception:
                return text
        return text
