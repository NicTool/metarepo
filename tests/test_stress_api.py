import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docker" / "stress-api.sh"


class StressApiTargetTests(unittest.TestCase):
    def test_make_target_passes_runtime_and_count(self):
        output = subprocess.run(
            ["make", "-n", "stress-api", "RUNTIME=node:25", "N=7"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout

        self.assertIn('RUNTIME="node:25"', output)
        self.assertIn('N="7"', output)
        self.assertIn("./docker/stress-api.sh", output)

    def test_compose_service_uses_the_built_image_without_api_node_modules_mount(self):
        service = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["api-stress"]

        self.assertEqual(service["profiles"], ["stress"])
        self.assertEqual(service["image"], "${STRESS_API_IMAGE:-nictool-api-stress:node-24}")
        self.assertIn("./libs/validate:/app/node_modules/@nictool/validate:ro", service["volumes"])
        self.assertNotIn("./api:/app", service["volumes"])


class StressApiScriptTests(unittest.TestCase):
    def test_runs_every_iteration_and_keeps_failed_output(self):
        with tempfile.TemporaryDirectory() as temp:
            tempdir = Path(temp)
            api_dir = tempdir / "api"
            api_dir.mkdir()
            (api_dir / "package.json").write_text("{}\n")
            calls = tempdir / "calls"
            count = tempdir / "count"
            fake_docker = tempdir / "docker"
            fake_docker.write_text(
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    echo "$*" >> "{calls}"
                    case "$*" in
                      build*) exit 0 ;;
                      *run*api-stress*)
                        n=0
                        [ ! -f "{count}" ] || n=$(cat "{count}")
                        n=$((n + 1))
                        echo "$n" > "{count}"
                        case "$n" in
                          2)
                            echo 'DIAGZR filtered= 2'
                            exit 1
                            ;;
                          3) echo '# skipped 1' ;;
                          *) echo 'tests passed' ;;
                        esac
                        ;;
                    esac
                    """
                )
            )
            fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)
            logs = tempdir / "logs"
            env = {
                **os.environ,
                "PATH": f"{tempdir}:{os.environ['PATH']}",
                "RUNTIME": "node:24",
                "N": "4",
                "STRESS_API_API_DIR": str(api_dir),
                "STRESS_API_LOG_DIR": str(logs),
            }

            result = subprocess.run(
                [SCRIPT],
                cwd=ROOT,
                capture_output=True,
                check=False,
                env=env,
                text=True,
            )

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("run 1/4 PASS", result.stdout)
            self.assertIn("run 2/4 FAIL", result.stdout)
            self.assertIn("run 3/4 FAIL", result.stdout)
            self.assertIn("run 4/4 PASS", result.stdout)
            self.assertIn("DIAGZR filtered= 2", result.stdout)
            self.assertIn("# skipped 1", result.stdout)
            self.assertIn("flake rate: 2/4 (50.00%)", result.stdout)
            self.assertIn("runtime: node:24", result.stdout)
            self.assertEqual(count.read_text().strip(), "4")
            self.assertIn("--build-arg RUNTIME=node:24", calls.read_text())
            self.assertIn(str(api_dir), calls.read_text())

            failed_logs = list(logs.glob("*/run-002.log"))
            self.assertEqual(len(failed_logs), 1)
            self.assertIn("DIAGZR filtered= 2", failed_logs[0].read_text())

    def test_rejects_a_non_positive_run_count_before_calling_docker(self):
        result = subprocess.run(
            [SCRIPT],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env={**os.environ, "N": "0"},
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("N must be a positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
