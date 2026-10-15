from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNNER_PATH = ROOT / "tools" / "run_4174_snapshot.py"

spec = importlib.util.spec_from_file_location("run_4174_snapshot", RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {RUNNER_PATH}")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RuntimeDataIsolationTest(unittest.TestCase):
    def test_nested_runtime_root_rejected_before_creation(self) -> None:
        probe = runner.VENDOR / ".checkpoint2-invalid-runtime-data-probe"
        self.assertFalse(
            probe.exists(),
            f"test precondition failed; probe already exists: {probe}",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "runtime-data root must be outside vendored code root",
        ):
            runner.validate_runtime_data_root(probe)

        self.assertFalse(
            probe.exists(),
            "invalid runtime-data path was created inside immutable vendor tree",
        )


if __name__ == "__main__":
    unittest.main()
