import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make_dry_run(target: str) -> str:
    return subprocess.run(
        ["make", "-n", target],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout


class V2TestTargetTests(unittest.TestCase):
    def test_default_v2_target_uses_only_soap(self):
        output = make_dry_run("test-v2")

        self.assertIn("NICTOOL_DATA_PROTOCOL=soap", output)
        self.assertIn("NICTOOL_TEST_CFG=t/test.cfg", output)
        self.assertIn("prove -v xt/*.t", output)
        self.assertNotIn("NICTOOL_DATA_PROTOCOL=rest", output)

    def test_rest_target_names_the_supported_extended_tests(self):
        output = make_dry_run("test-v2-rest")

        self.assertIn("NICTOOL_DATA_PROTOCOL=rest", output)
        self.assertIn("NICTOOL_TEST_CFG=t/test-rest.cfg", output)
        self.assertIn(
            "prove -v xt/14_permissions.t xt/16_delegation.t xt/20_permission.t",
            output,
        )
        self.assertNotIn("prove -v xt/*.t", output)

    def test_rest_browser_target_uses_generated_account_and_group(self):
        output = make_dry_run("test-v2-e2e-rest")

        self.assertIn("username", output)
        self.assertIn("password", output)
        self.assertIn("test_gid", output)
        self.assertIn('NICTOOL_TEST_USER="$user"', output)
        self.assertIn('NICTOOL_TEST_PASSWORD="$password"', output)
        self.assertIn('NICTOOL_TEST_GID="$test_gid"', output)
        self.assertIn("run --rm --no-deps -T", output)
        self.assertIn("v2-e2e", output)
        self.assertNotIn("cd NicTool/client/t/e2e", output)


class TeardownTargetTests(unittest.TestCase):
    def test_down_and_clean_cover_the_browser_runner_profile(self):
        self.assertIn("--profile all --profile test down\n", make_dry_run("down"))
        self.assertIn("--profile all --profile test down -v\n", make_dry_run("clean"))

    def test_up_all_leaves_the_browser_runner_alone(self):
        output = make_dry_run("up-all")

        self.assertNotIn("--profile test", output)


if __name__ == "__main__":
    unittest.main()
