import re, unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"rollout_channel_profiles_owner_local.sh"
SOURCE=SCRIPT.read_text(encoding="utf-8")

class ChannelProfileRolloutScriptTests(unittest.TestCase):
    def test_shell_script_has_exact_head_and_owner_local_guards(self):
        self.assertIn('--expected-head',SOURCE)
        self.assertIn('[[ "$HEAD" == "$EXPECTED_HEAD" ]]',SOURCE)
        self.assertIn('[[ -z "$(git status --porcelain)" ]]',SOURCE)
        self.assertIn('ABORT: frontend/assets config cannot be used as backend config',SOURCE)
        self.assertIn('materialize_channel_profile_backend_config.py',SOURCE)
        self.assertIn('BACKEND_CONFIG="/tmp/hv155-backend-wrangler.json"',SOURCE)
        self.assertIn('ACCEPTED_BASELINE="df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96"',SOURCE)

    def test_mutations_are_explicitly_gated(self):
        self.assertIn('if (( APPLY == 0 )); then',SOURCE)
        self.assertIn('(( DEPLOY == 0 || APPLY == 1 ))',SOURCE)
        self.assertIn('=== MUTATION 1: ADDITIVE MIGRATION ===',SOURCE)
        self.assertIn('=== MUTATION 2: 85 PROFILE POPULATION ===',SOURCE)
        self.assertIn('=== MUTATION 3: ACTIVATE CANDIDATE 100% ===',SOURCE)

    def test_deploy_uses_complete_backend_config_and_dynamic_rollback(self):
        self.assertIn('--config "$BACKEND_CONFIG"',SOURCE)
        self.assertIn('--config "$BACKEND_CONFIG_SOURCE"',SOURCE)
        self.assertNotIn('--config "$D1_CONFIG" --keep-vars',SOURCE)
        self.assertIn('OLD_VERSION_ID="$(',SOURCE)
        self.assertIn('wrangler versions view "$OLD_VERSION_ID"',SOURCE)
        self.assertIn('CANDIDATE_BINDING_CONTRACT=PASS',SOURCE)
        self.assertIn('ROLLBACK_TO=$OLD_VERSION_ID',SOURCE)

    def test_reentry_python_gates_do_not_contain_literal_backslash_n(self):
        self.assertNotIn('p=d["plan"]\\nassert',SOURCE)
        self.assertIn('p=d["plan"]\nassert p["updates"]==0, p',SOURCE)

    def test_semantic_readback_failure_rolls_back(self):
        self.assertIn("if ! python3 - /tmp/hv155-profile-readback.json <<'PY'",SOURCE)
        self.assertIn("PY\nthen\n  rollback\n  exit 1\nfi",SOURCE)

    def test_wrangler_4152_upload_uses_machine_readable_output_receipt(self):
        self.assertIn('WRANGLER_OUTPUT_FILE_PATH="$UPLOAD_OUTPUT"',SOURCE)
        self.assertIn('UPLOAD_OUTPUT="/tmp/hv155-version-upload.ndjson"',SOURCE)
        self.assertNotIn('--message "PR155 canonical profile authority $HEAD" --json',SOURCE)
        self.assertIn('--name "$WORKER" --config "$BACKEND_CONFIG" --keep-vars',SOURCE)
        self.assertIn('obj.get("type")!="version-upload"',SOURCE)
        self.assertIn('obj.get("worker_name") not in (None,worker)',SOURCE)
        self.assertIn('expected exactly one uploaded candidate version',SOURCE)
        self.assertIn('version-upload receipt missing canonical version_id',SOURCE)
        self.assertIn('wrangler versions view "$NEW_VERSION_ID"',SOURCE)
        upload=SOURCE.index('WRANGLER_OUTPUT_FILE_PATH="$UPLOAD_OUTPUT"')
        verify=SOURCE.index('wrangler versions view "$NEW_VERSION_ID"')
        activate=SOURCE.index('=== MUTATION 3: ACTIVATE CANDIDATE 100% ===')
        self.assertLess(upload,verify)
        self.assertLess(verify,activate)

    def test_population_and_readback_contract_is_present(self):
        for marker in (
            'PROFILE_ROWS=85',
            'AVATARS_PRESENT=85',
            'PROFILE_REPLAY_IDEMPOTENT=PASS',
            '/v1/channels/$ROBOCO/profile',
            '/v1/catalog/today',
            '/v1/history?day=$DAY',
            '/v1/videos/$VIDEO/metadata',
            '/v1/collab/live',
            '/v1/watchalong/recent',
            'https://holodocchi.com',
        ):
            self.assertIn(marker,SOURCE)

if __name__=="__main__":
    unittest.main()
