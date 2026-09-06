# Copyright (c) 2026, The NicTool Contributors

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IntegrationRunnerTests(unittest.TestCase):
    def test_runner_does_not_call_a_skipped_suite_passing(self):
        script = (ROOT / "scripts" / "integration-test.sh").read_text()
        function = script.split("run_suite() {", 1)[1].split("\n}\n", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", "-c", 'script_dir=$1; suite_log_dir=$2; failed_suites=(); run_suite() {' + function + '\n}\nrun_suite fixture printf "# tests 2\\n# pass 1\\n# skipped 1\\n"', "fixture", str(ROOT), directory],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(0, result.returncode)
        self.assertIn("suite result fixture INCOMPLETE", result.stdout + result.stderr)
        self.assertNotIn("fixture PASS", result.stdout + result.stderr)

    def test_upgrade_prompts_receive_both_required_newlines(self):
        script = (ROOT / "scripts" / "integration-test.sh").read_text()

        self.assertIn("printf '\\n\\n' |", script)

    def test_source_overrides_cover_build_mount_and_upgrade_paths(self):
        script = (ROOT / "scripts" / "integration-test.sh").read_text()
        compose = (ROOT / "docker-compose.corpus.yml").read_text()

        for variable in ("NICTOOL_API_SOURCE", "NICTOOL_LEGACY_SOURCE", "NICTOOL_VALIDATE_SOURCE"):
            with self.subTest(variable=variable):
                self.assertIn(variable, script)
                self.assertIn(variable, compose)
        self.assertIn('for upgrade in "$api_source"/sql/upgrade/', script)

    def test_corpus_stack_explicitly_enables_legacy_test_fixtures(self):
        compose = (ROOT / "docker-compose.corpus.yml").read_text()

        self.assertIn('NICTOOL_TEST_ENV: "1"', compose)

    def test_failed_perl_suite_names_are_printed_without_dumping_the_log(self):
        script = (ROOT / "scripts" / "integration-test.sh").read_text()

        self.assertIn("not ok [0-9]+", script)
        self.assertIn("#.*Failed test", script)

    def test_source_audit_and_application_findings_are_explicit_options(self):
        script = (ROOT / "scripts" / "integration-test.sh").read_text()

        self.assertIn('--source "$source_file" --require-source', script)
        self.assertIn('allow_test_failures', script)
        self.assertIn("application test failures were retained as findings", script)


if __name__ == "__main__":
    unittest.main()
