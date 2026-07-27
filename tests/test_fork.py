import io
import nt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class ForkPartTests(unittest.TestCase):
    def setUp(self):
        self.projects = [
            nt.Project(
                "NicTool",
                Path("."),
                "https://github.com/NicTool/NicTool.git",
                "master",
            ),
            nt.Project(
                "dns-resource-record",
                Path("."),
                "https://github.com/NicTool/dns-resource-record.git",
                "v1.8.1",
            ),
        ]

    @patch("nt.wire_fork", return_value="fork remote added")
    @patch("nt.existing_fork_owner", return_value=None)
    @patch("nt.gh_login", return_value="chorlham")
    def test_fork_part_only_wires_selected_manifest_entry(
        self, _login, _existing_owner, wire
    ):
        with patch("sys.stdout", new_callable=io.StringIO):
            nt.cmd_fork(
                self.projects,
                owner=None,
                remove=False,
                part="dns-resource-record",
            )

        wire.assert_called_once_with(self.projects[1], "chorlham", [])

    @patch("nt.wire_fork", return_value="fork remote added")
    @patch("nt.existing_fork_owner")
    @patch("nt.gh_login", return_value="chorlham")
    def test_explicit_owner_bypasses_existing_remote_inference(
        self, _login, existing_owner, wire
    ):
        with patch("sys.stdout", new_callable=io.StringIO):
            nt.cmd_fork(
                self.projects,
                owner="my-org",
                remove=False,
                part="dns-resource-record",
            )

        existing_owner.assert_not_called()
        wire.assert_called_once_with(self.projects[1], "my-org", ["--org", "my-org"])

    def test_unknown_part_fails_before_network_checks(self):
        with (
            patch("nt.gh_login") as login,
            self.assertRaisesRegex(
                SystemExit,
                r"unknown part 'missing'.*NicTool, dns-resource-record",
            ),
        ):
            nt.cmd_fork(
                self.projects,
                owner=None,
                remove=False,
                part="missing",
            )

        login.assert_not_called()

    @patch("nt.git")
    @patch("nt.fork_remote_url", return_value="https://github.com/chorlham/repo.git")
    def test_remove_part_only_removes_selected_manifest_entry(
        self, fork_remote_url, git
    ):
        with patch("sys.stdout", new_callable=io.StringIO):
            nt.cmd_fork(
                self.projects,
                owner=None,
                remove=True,
                part="dns-resource-record",
            )

        fork_remote_url.assert_called_once_with(self.projects[1])
        git.assert_called_once_with(
            self.projects[1].path,
            "remote",
            "remove",
            "fork",
        )

    @patch("nt.cmd_fork")
    @patch("nt.load_projects")
    def test_main_passes_part_to_fork_command(self, load_projects, cmd_fork):
        load_projects.return_value = self.projects

        with patch.object(
            sys,
            "argv",
            ["nt", "fork", "--part", "dns-resource-record", "my-org"],
        ):
            nt.main()

        cmd_fork.assert_called_once_with(
            self.projects,
            "my-org",
            False,
            "dns-resource-record",
        )

    def test_fork_help_explains_remove_scope(self):
        stdout = io.StringIO()

        with (
            patch.object(sys, "argv", ["nt", "fork", "--help"]),
            patch.object(sys, "stdout", stdout),
            self.assertRaisesRegex(SystemExit, "0"),
        ):
            nt.main()

        help_text = stdout.getvalue()
        normalized_help = " ".join(help_text.split())
        self.assertIn(
            "remove local 'fork' remote(s) only; leave origin and "
            "GitHub forks unchanged",
            normalized_help,
        )


if __name__ == "__main__":
    unittest.main()
