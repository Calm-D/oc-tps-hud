"""速度计算。除文件读写外都是纯函数，便于单测。

口径：
  精确值 = (output + reasoning) / (step-finish 时间 − step-start 时间)
  实时值 = Δ加权字符 × 校准系数 / Δt，4 秒滑窗 + 指数平滑 + 静默衰减
"""

import json
import os
import statistics
import time
from collections import deque

from . import config
from .source import SchemaError

WINDOW_SEC = 4.0
RECENT_STEPS = 8
DEFAULT_RATIO = 0.9
RATIO_MIN, RATIO_MAX = 0.3, 3.0
CALIB_MIN_CHARS = 500.0


def step_rate(tokens, duration):
    if duration <= 0.3 or tokens <= 0:
        return None
    return tokens / duration


def median_rate(pairs):
    vals = [t / d for t, d in pairs if d > 0]
    return statistics.median(vals) if vals else None


def smooth(prev, inst, weight=0.45):
    if prev <= 0:
        return inst
    return prev * (1 - weight) + inst * weight


def decay(rate, factor=0.75, floor=0.6):
    rate *= factor
    return 0.0 if rate < floor else rate


class Calibration:
    """按模型学习「加权字符 → token」的折算系数。"""

    def __init__(self, path=None):
        self.path = path or config.calibration_path()
        self.data = {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def ratio(self, model):
        try:
            return float(self.data.get(model, DEFAULT_RATIO))
        except Exception:
            return DEFAULT_RATIO

    def update(self, model, wchars, tokens):
        if wchars < CALIB_MIN_CHARS or tokens <= 0:
            return False
        r = tokens / wchars
        if not (RATIO_MIN <= r <= RATIO_MAX):
            return False
        old = self.ratio(model)
        self.data[model] = round(old * 0.7 + r * 0.3, 4)
        self.save()
        return True

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass


class Engine:
    def __init__(self, source, calibration=None):
        self.src = source
        self.cal = calibration or Calibration()
        self.hist = deque()
        self.mid = None
        self.rate = 0.0
        self.peak = 0.0
        self.last_growth = 0.0
        self.done_seen = set()
        self.recent = deque(maxlen=RECENT_STEPS)
        try:
            for pair in self.src.recent_steps(RECENT_STEPS):
                self.recent.append(pair)
        except Exception:
            pass

    def reset_step(self, mid):
        self.mid = mid
        self.hist.clear()
        self.rate = 0.0
        self.peak = 0.0
        self.last_growth = time.time()

    def median(self):
        return median_rate(self.recent)

    def tick(self):
        now = time.time()
        try:
            d = self.src.fetch()
        except SchemaError:
            return {"state": "noschema"}
        except Exception:
            try:
                self.src.connect()
            except Exception:
                pass
            return {"state": "error"}

        if d is None:
            return {"state": "nodata"}

        base = {
            "model": d.get("model", "?"),
            "recent": self.median(),
            "last": (self.recent[-1][0] / self.recent[-1][1]) if self.recent else None,
        }

        if d["state"] == "idle":
            base["state"] = "idle"
            return base
        if d["state"] == "queued":
            base["state"] = "queue"
            return base

        if d["state"] == "done":
            mid = d["mid"]
            if mid not in self.done_seen:
                self.done_seen.add(mid)
                r = step_rate(d["tokens"], (d["finish"] - d["start"]) / 1000.0)
                if r:
                    self.recent.append((d["tokens"], (d["finish"] - d["start"]) / 1000.0))
                    self.cal.update(d["model"], d["wchars"], d["tokens"])
                    self.rate = r
            base.update(state="done", rate=self.rate, tokens=d["tokens"],
                        elapsed=((d["finish"] or now * 1000) - d["start"]) / 1000.0,
                        tools=d["tools"])
            return base

        if d["mid"] != self.mid:
            self.reset_step(d["mid"])

        ratio = self.cal.ratio(d["model"])
        self.hist.append((now, d["wchars"]))
        while self.hist and now - self.hist[0][0] > WINDOW_SEC + 2:
            self.hist.popleft()

        ref = None
        for t, c in self.hist:
            if now - t <= WINDOW_SEC:
                ref = (t, c)
                break
        if ref and now - ref[0] >= 1.2:
            delta = d["wchars"] - ref[1]
            if delta > 0:
                inst = delta * ratio / (now - ref[0])
                self.rate = smooth(self.rate, inst)
                self.peak = max(self.peak, self.rate)
                self.last_growth = now
            else:
                self.rate = decay(self.rate)

        silent = now - self.last_growth
        if d["wchars"] == 0 and silent > 2.5:
            state = "ttft"
        elif silent > 3.0:
            state = "wait"
        else:
            state = "run"

        base.update(state=state, rate=self.rate, tokens=d["wchars"] * ratio,
                    elapsed=now - d["start"] / 1000.0, tools=d["tools"])
        return base
