import io
import subprocess
import sys
import unittest
from unittest.mock import call, patch

import nt


class TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class MissingPrerequisiteTests(unittest.TestCase):
    @patch("nt.subprocess.run")
    @patch("nt.shutil.which")
    def test_preflight_installs_missing_requirement(self, which, run):
        which.side_effect = [
            None,
            "/opt/homebrew/bin/brew",
            "/opt/homebrew/bin/mani",
        ]
        run.return_value = subprocess.CompletedProcess(
            ["brew", "install", "mani"], 0
        )

        with (
            patch.object(sys, "stdin", TtyInput("y\n")),
            patch.object(sys, "stderr", io.StringIO()),
        ):
            nt.require_command("mani")

        run.assert_called_once_with(
            ["/opt/homebrew/bin/brew", "install", "mani"]
        )

    @patch("nt.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("nt.subprocess.run")
    def test_offers_brew_install_then_retries_command(self, run, _which):
        run.side_effect = [
            FileNotFoundError(2, "No such file or directory", "mani"),
            subprocess.CompletedProcess(["brew", "install", "mani"], 0),
            subprocess.CompletedProcess(["mani", "sync"], 0, "synced", ""),
        ]
        stderr = io.StringIO()

        with (
            patch.object(sys, "stdin", TtyInput("yes\n")),
            patch.object(sys, "stderr", stderr),
        ):
            result = nt.sh(["mani", "sync"])

        self.assertEqual(result.stdout, "synced")
        self.assertIn("error: missing prerequisite: mani", stderr.getvalue())
        self.assertIn("Run this command now? [y/N]", stderr.getvalue())
        self.assertIn("mani installed; continuing.", stderr.getvalue())
        self.assertEqual(
            run.call_args_list,
            [
                call(["mani", "sync"], cwd=None, capture_output=True, text=True),
                call(["/opt/homebrew/bin/brew", "install", "mani"]),
                call(["mani", "sync"], cwd=None, capture_output=True, text=True),
            ],
        )

    @patch("nt.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("nt.subprocess.run")
    def test_noninteractive_run_prints_command_without_prompting(self, run, _which):
        run.side_effect = FileNotFoundError(2, "No such file or directory", "mani")
        stderr = io.StringIO()

        with (
            patch.object(sys, "stdin", io.StringIO()),
            patch.object(sys, "stderr", stderr),
        ):
            with self.assertRaisesRegex(SystemExit, "127"):
                nt.sh(["mani", "sync"])

        message = stderr.getvalue()
        self.assertIn("brew install mani", message)
        self.assertNotIn("Run this command now?", message)
        run.assert_called_once_with(
            ["mani", "sync"], cwd=None, capture_output=True, text=True
        )


if __name__ == "__main__":
    unittest.main()
