from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "deploy_daily_digest_static_assets_owner_local.sh"


class DailyDigestStaticReleaseGateTests(unittest.TestCase):
    def write_month(self, repo: Path, month: str = "2026-11") -> Path:
        path = repo / f"daily-digest-static/data/daily-digest/months/{month}.json"
        path.write_text(
            '{"schema_version":1,"kind":"holodocchi.daily_digest_month",'
            f'"month":"{month}","days":{{}}}}\n',
            encoding="utf-8",
        )
        return path

    def write_month_with_day(self, repo: Path, day: str = "2026-11-02") -> Path:
        month = day[:7]
        path = repo / f"daily-digest-static/data/daily-digest/months/{month}.json"
        path.write_text(
            '{"schema_version":1,"kind":"holodocchi.daily_digest_month",'
            f'"month":"{month}","days":{{"{day}":{{'
            '"schema_version":1,"kind":"holodocchi.daily_digest",'
            f'"target_day":"{day}"'
            '}}}\n',
            encoding="utf-8",
        )
        return path

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
        curl = bin_dir / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            "out=''\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -o) out=\"$2\"; shift 2 ;;\n"
            "    -w) shift 2 ;;\n"
            "    --max-time) shift 2 ;;\n"
            "    -sS) shift ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            "status=\"${MOCK_CURL_STATUS:-404}\"\n"
            "if [ \"$status\" = 200 ]; then printf '%s' \"${MOCK_CURL_BODY:-}\" >\"$out\"; else : >\"$out\"; fi\n"
            "printf '%s' \"$status\"\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)
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
            self.write_month(repo)
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
            self.write_month(repo)
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
            self.write_month(repo)
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid related clips sidecar", result.stderr)

    def test_sidecar_only_candidate_with_zero_month_shards_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            sidecar_dir = repo / "daily-digest-static/data/daily-digest/2026-11"
            sidecar_dir.mkdir(parents=True)
            (sidecar_dir / "2026-11-02-related-clips.json").write_text(
                '{"schema_version":1,"kind":"holodocchi.daily_digest.related_clips",'
                '"target_day":"2026-11-02","status":"ok","stories":[],"sources":{}}\n',
                encoding="utf-8",
            )
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("zero month shards", result.stderr)

    def test_prepare_preserves_live_related_clips_missing_from_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            self.write_month_with_day(repo)
            env["MOCK_CURL_STATUS"] = "200"
            env["MOCK_CURL_BODY"] = (
                '{"schema_version":1,"kind":"holodocchi.daily_digest.related_clips",'
                '"target_day":"2026-11-02","status":"ok","stories":[],"sources":{}}\n'
            )
            result = self.run_prepare(repo, head, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            preserved = (
                repo
                / "daily-digest-static/data/daily-digest/2026-11/"
                "2026-11-02-related-clips.json"
            )
            self.assertTrue(preserved.is_file())
            self.assertIn(
                "PRESERVED_LIVE_RELATED_CLIPS=data/daily-digest/2026-11/"
                "2026-11-02-related-clips.json",
                result.stdout,
            )

    def test_prepare_fails_closed_on_live_related_clips_read_error(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            self.write_month_with_day(repo)
            env["MOCK_CURL_STATUS"] = "503"
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected live related clips status 503", result.stderr)

    def test_unrelated_runtime_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo, head, env = self.make_repo(Path(td))
            (repo / "unexpected.txt").write_text("drift\n", encoding="utf-8")
            result = self.run_prepare(repo, head, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-Daily-Digest runtime drift", result.stderr)


if __name__ == "__main__":
    unittest.main()
