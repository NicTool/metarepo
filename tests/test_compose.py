import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.58.2-noble"
TEMPORARY_TRAINS = {
    "NicTool": ("master", 365),
    "api": ("main", 61),
    "server": ("main", 8),
}
UNRELEASED_MAIN_PINS = ("validate", "dns-zone")


def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


class ComposeTests(unittest.TestCase):
    def test_manifest_declares_the_temporary_trains(self):
        manifest = yaml.safe_load((ROOT / "mani.yaml").read_text())
        projects = manifest["projects"]

        for project, (pin, pull_request) in TEMPORARY_TRAINS.items():
            self.assertEqual(projects[project]["env"]["pin"], pin)
            self.assertEqual(projects[project]["env"]["train"], pull_request)

    def test_manifest_follows_unreleased_library_work(self):
        manifest = yaml.safe_load((ROOT / "mani.yaml").read_text())

        for project in UNRELEASED_MAIN_PINS:
            self.assertEqual(manifest["projects"][project]["env"], {"pin": "main"})

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

    def test_legacy_waits_for_the_root_user_seed(self):
        services = compose()["services"]
        seed = services["root-user-init"]

        self.assertEqual(seed["profiles"], ["legacy", "all"])
        self.assertEqual(seed["depends_on"]["db"]["condition"], "service_healthy")
        self.assertEqual(seed["depends_on"]["api"]["condition"], "service_healthy")
        self.assertEqual(seed["image"], "node:22-trixie-slim")
        self.assertEqual(seed["working_dir"], "/app")
        self.assertIn("./docker/seed-root-user.mjs:/init/seed-root-user.mjs:ro", seed["volumes"])
        self.assertEqual(seed["command"], ["node", "/init/seed-root-user.mjs"])
        self.assertEqual(
            services["nictool-legacy"]["depends_on"]["root-user-init"]["condition"],
            "service_completed_successfully",
        )

    def test_legacy_profile_enables_the_generated_test_environment(self):
        legacy = compose()["services"]["nictool-legacy"]

        self.assertEqual(legacy["environment"]["NICTOOL_TEST_ENV"], "1")

    def test_browser_runner_stays_out_of_the_all_profile(self):
        self.assertEqual(compose()["services"]["v2-e2e"]["profiles"], ["test"])

    def test_browser_tests_run_in_the_pinned_playwright_image(self):
        e2e = compose()["services"]["v2-e2e"]

        self.assertEqual(e2e["image"], PLAYWRIGHT_IMAGE)
        self.assertEqual(e2e["environment"]["NICTOOL_URL"], "https://nictool-legacy")
        self.assertIn("v2_e2e_node_modules:/work/node_modules", e2e["volumes"])
        self.assertEqual(e2e["command"], ["sh", "-c", "npm ci && npm test"])

    def test_v3_ui_uses_the_remote_api_and_persists_its_config(self):
        server = compose()["services"]["server"]
        env = server["environment"]

        self.assertEqual(env["NICTOOL_API_HOST"], "api")
        self.assertEqual(env["NICTOOL_API_PORT"], 3000)
        self.assertEqual(env["NICTOOL_API_SCHEME"], "http")
        self.assertEqual(env["NICTOOL_HTTP_PORT"], "${SERVER_CONTAINER_PORT:-8080}")
        self.assertIn("server-data:/data", server["volumes"])
        self.assertIn("/nt/service", server["healthcheck"]["test"][-1])

    def test_v3_ui_tests_use_the_compose_database(self):
        dsn = compose()["services"]["server"]["environment"]["NICTOOL_TEST_DSN"]

        self.assertIn("@db:3306/", dsn)


if __name__ == "__main__":
    unittest.main()
