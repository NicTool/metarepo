import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.58.2-noble"
BRIDGE_TRAINS = {
    "NicTool": ("master", 365),
    "api": ("main", 61),
}


def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


class ComposeTests(unittest.TestCase):
    def test_manifest_declares_the_bridge_trains(self):
        manifest = yaml.safe_load((ROOT / "mani.yaml").read_text())
        projects = manifest["projects"]

        for project, (pin, pull_request) in BRIDGE_TRAINS.items():
            self.assertEqual(projects[project]["env"]["pin"], pin)
            self.assertEqual(projects[project]["env"]["train"], pull_request)

    def test_manifest_pins_the_released_validate(self):
        manifest = yaml.safe_load((ROOT / "mani.yaml").read_text())

        self.assertEqual(manifest["projects"]["validate"]["env"], {"pin": "v1.0.0"})

    def test_api_build_takes_no_validate_spec(self):
        build = compose()["services"]["api"]["build"]

        self.assertNotIn("args", build)

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

    def test_browser_runner_stays_out_of_the_all_profile(self):
        self.assertEqual(compose()["services"]["v2-e2e"]["profiles"], ["test"])

    def test_browser_tests_run_in_the_pinned_playwright_image(self):
        e2e = compose()["services"]["v2-e2e"]

        self.assertEqual(e2e["image"], PLAYWRIGHT_IMAGE)
        self.assertEqual(e2e["environment"]["NICTOOL_URL"], "https://nictool-legacy")
        self.assertIn("v2_e2e_node_modules:/work/node_modules", e2e["volumes"])
        self.assertEqual(e2e["command"], ["sh", "-c", "npm ci && npm test"])


if __name__ == "__main__":
    unittest.main()
