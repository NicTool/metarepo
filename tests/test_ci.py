import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_ci_runs_workspace_checks(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()

        self.assertIn("python -m unittest discover -v", workflow)
        self.assertIn("uvx ruff check .", workflow)
        self.assertIn("python -m py_compile nt.py tests/*.py", workflow)

    def test_ci_validates_all_compose_profiles(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()

        self.assertIn("make env", workflow)
        self.assertIn("--profile legacy --profile test config --quiet", workflow)


if __name__ == "__main__":
    unittest.main()
