"""纯逻辑单测：不依赖 OpenCode、不依赖数据库文件。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from oc_tps import engine as eng  # noqa: E402
from oc_tps.source import weighted_len  # noqa: E402


class TestWeightedLen(unittest.TestCase):
    def test_ascii(self):
        self.assertAlmostEqual(weighted_len("abcd"), 1.0)

    def test_cjk(self):
        self.assertAlmostEqual(weighted_len("中文"), 2.0)

    def test_mixed(self):
        self.assertAlmostEqual(weighted_len("中文ab"), 2.5)

    def test_empty(self):
        self.assertEqual(weighted_len(""), 0.0)


class TestRateMath(unittest.TestCase):
    def test_step_rate(self):
        self.assertAlmostEqual(eng.step_rate(300, 2.0), 150.0)

    def test_step_rate_guards(self):
        self.assertIsNone(eng.step_rate(0, 2.0))
        self.assertIsNone(eng.step_rate(300, 0.1))

    def test_median_rate(self):
        self.assertAlmostEqual(eng.median_rate([(100, 1.0), (100, 2.0), (300, 1.0)]), 100.0)
        self.assertIsNone(eng.median_rate([]))

    def test_smooth_first_sample(self):
        self.assertAlmostEqual(eng.smooth(0.0, 120.0), 120.0)

    def test_smooth_blends(self):
        self.assertAlmostEqual(eng.smooth(100.0, 200.0), 145.0)

    def test_decay_floor(self):
        self.assertEqual(eng.decay(0.5), 0.0)
        self.assertAlmostEqual(eng.decay(10.0), 7.5)


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "calibration.json")

    def test_default_ratio(self):
        cal = eng.Calibration(self.path)
        self.assertAlmostEqual(cal.ratio("unknown"), eng.DEFAULT_RATIO)

    def test_rejects_small_sample(self):
        cal = eng.Calibration(self.path)
        self.assertFalse(cal.update("m", 100.0, 200.0))
        self.assertAlmostEqual(cal.ratio("m"), eng.DEFAULT_RATIO)

    def test_rejects_absurd_ratio(self):
        cal = eng.Calibration(self.path)
        self.assertFalse(cal.update("m", 1000.0, 100000.0))

    def test_learns_and_persists(self):
        cal = eng.Calibration(self.path)
        self.assertTrue(cal.update("m", 1000.0, 1200.0))
        again = eng.Calibration(self.path)
        self.assertGreater(again.ratio("m"), eng.DEFAULT_RATIO)
        self.assertLess(again.ratio("m"), 1.2)


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t


class FakeSource:
    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0

    def connect(self):
        pass

    def recent_steps(self, limit=8):
        return [(800, 4.0)]

    def fetch(self):
        if self.i < len(self.frames):
            f = self.frames[self.i]
            self.i += 1
            return f
        return self.frames[-1]


def frame(wchars, state="run", mid="m1", tokens=0, start=None, finish=None):
    return {"state": state, "mid": mid, "model": "test-model", "wchars": wchars,
            "start": start if start is not None else 1000_000,
            "finish": finish, "tokens": tokens, "tools": 0}


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig_time = eng.time
        self.clock = FakeTime()
        eng.time = self.clock

    def tearDown(self):
        eng.time = self.orig_time

    def make(self, frames):
        return eng.Engine(FakeSource(frames), eng.Calibration(os.path.join(self.tmp, "c.json")))

    def test_streaming_produces_rate(self):
        e = self.make([frame(0.0), frame(600.0), frame(1200.0)])
        e.tick()                      # 建立基线
        self.clock.t += 2.0
        d = e.tick()                  # 2 秒内增长 600 字符
        self.assertEqual(d["state"], "run")
        self.assertGreater(d["rate"], 0)
        self.assertGreater(d["tokens"], 0)

    def test_silence_falls_back_to_wait(self):
        e = self.make([frame(500.0)])
        e.tick()
        self.clock.t += 10.0
        d = e.tick()
        self.assertEqual(d["state"], "wait")

    def test_no_output_means_ttft(self):
        e = self.make([frame(0.0)])
        e.tick()
        self.clock.t += 5.0
        d = e.tick()
        self.assertEqual(d["state"], "ttft")

    def test_done_uses_exact_tokens(self):
        e = self.make([frame(1000.0, state="done", tokens=400, start=1000_000, finish=1002_000)])
        d = e.tick()
        self.assertEqual(d["state"], "done")
        self.assertAlmostEqual(d["rate"], 200.0)

    def test_queued_and_idle(self):
        e = self.make([{"state": "queued", "model": "m"}, {"state": "idle", "model": "m"}])
        self.assertEqual(e.tick()["state"], "queue")
        self.assertEqual(e.tick()["state"], "idle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
