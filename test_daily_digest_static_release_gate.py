from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "deploy_daily_digest_static_assets_owner_local.sh"


class DailyDigestStaticReleaseGateTests(unittest.TestCase):
    def make_repo(self, root: Path) -> tuple[Path, str, dict[str, str]]:
        repo = root / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "daily-digest-static/data/daily-digest/months").mkdir(parents=True)
        (repo / "cloudflare").mkdir(parents=True)
        shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
        (repo / "daily-digest-static/data/daily-digest/months/.gitkeep").write_text("", encoding="utf-8")
        (repo / "cloudflare/daily-digest-static-assets.wrangler.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

        bin_dir = root / "bin"
        bin_dir.mkdir()
        npx = bin_dir / "npx"
        npx.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        npx.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        return repo, head, env

    def run_prepare(self, repo: Path, head: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(repo / "scripts" / SCRIPT.name), "prepare", head],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_generated_month_json_is_allowed_runtime_drift(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            month = repo / "daily-digest-static/data/daily-digest/months/2026-11.json"
            month.write_text(
                '{"schema_version":1,"kind":"holodocchi.daily_digest_month","month":"2026-11","days":{}}\n',
                encoding="utf-8",
            )
            result = self.run_prepare(repo, head, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DAILY_DIGEST_STATIC_PREPARE=PASS", result.stdout)
            self.assertIn("BASELINE_VERSION=ABSENT", result.stdout)


    def test_generated_related_clips_json_is_allowed_runtime_drift(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            sidecar_dir = repo / "daily-digest-static/data/daily-digest/2026-11"
            sidecar_dir.mkdir(parents=True)
            sidecar = sidecar_dir / "2026-11-02-related-clips.json"
            sidecar.write_text(
                '{"schema_version":1,"kind":"holodocchi.daily_digest.related_clips","target_day":"2026-11-02","status":"ok","stories":[],"sources":{}}\n',
                encoding="utf-8",
            )
            result = self.run_prepare(repo, head, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DAILY_DIGEST_STATIC_PREPARE=PASS", result.stdout)

    def test_invalid_related_clips_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            sidecar_dir = repo / "daily-digest-static/data/daily-digest/2026-11"
            sidecar_dir.mkdir(parents=True)
            sidecar = sidecar_dir / "2026-11-02-related-clips.json"
            sidecar.write_text(
                '{"schema_version":1,"kind":"wrong","target_day":"2026-11-02","status":"ok","stories":[],"sources":{}}\n',
                encoding="utf-8",
            )
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid related clips sidecar", result.stderr)

    def test_unrelated_runtime_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            (repo / "unexpected.txt").write_text("drift\n", encoding="utf-8")
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-Daily-Digest runtime drift", result.stderr)


if __name__ == "__main__":
    unittest.main()
