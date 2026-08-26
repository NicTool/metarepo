import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATE_HEAD = "a4d07855a3afe824d7d1d754550cb2d9a75fb145"


def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


class ComposeTests(unittest.TestCase):
    def test_api_builds_with_the_proposed_validate_by_default(self):
        spec = compose()["services"]["api"]["build"]["args"]["NICTOOL_VALIDATE_SPEC"]

        self.assertTrue(spec.startswith("${NICTOOL_VALIDATE_SPEC:-"))
        self.assertIn(VALIDATE_HEAD, spec)

    def test_api_runs_the_manifest_validate_checkout(self):
        volumes = compose()["services"]["api"]["volumes"]

        self.assertIn("./libs/validate:/app/node_modules/@nictool/validate", volumes)

    def test_legacy_gui_defaults_to_rest_against_the_api(self):
        legacy = compose()["services"]["nictool-legacy"]
        env = legacy["environment"]

        self.assertEqual(env["NICTOOL_DATA_PROTOCOL"], "${NICTOOL_DATA_PROTOCOL:-rest}")
        self.assertEqual(env["NICTOOL_SERVER_HOST"], "${NICTOOL_SERVER_HOST:-api}")
        self.assertEqual(env["NICTOOL_SERVER_PORT"], "${NICTOOL_SERVER_PORT:-3000}")
        self.assertEqual(env["DB_PORT"], "3306")
        self.assertIn("api", legacy["depends_on"])


if __name__ == "__main__":
    unittest.main()
