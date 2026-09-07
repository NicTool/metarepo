import io
import json
import nt
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch


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
            ["/opt/homebrew/bin/brew", "install", "mani"],
            check=False,
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
                call(
                    ["mani", "sync"],
                    cwd=None,
                    capture_output=True,
                    text=True,
                    check=False,
                ),
                call(
                    ["/opt/homebrew/bin/brew", "install", "mani"],
                    check=False,
                ),
                call(
                    ["mani", "sync"],
                    cwd=None,
                    capture_output=True,
                    text=True,
                    check=False,
                ),
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
            self.assertRaisesRegex(SystemExit, "127"),
        ):
            nt.sh(["mani", "sync"])

        message = stderr.getvalue()
        self.assertIn("brew install mani", message)
        self.assertNotIn("Run this command now?", message)
        run.assert_called_once_with(
            ["mani", "sync"],
            cwd=None,
            capture_output=True,
            text=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()


class TrainTests(unittest.TestCase):
    def project(self):
        return nt.Project(name="NicTool", path=nt.Path("/tmp/nictool"), url="https://github.com/NicTool/NicTool.git", pin="master", train=[365])

    @patch("nt.shutil.which", return_value=None)
    @patch("nt.sh")
    def test_pr_state_is_unknown_without_gh(self, sh, _which):
        self.assertEqual(nt.pr_state(self.project(), 365), "unknown")
        sh.assert_not_called()

    @patch("nt.pr_state", return_value="unknown")
    @patch("nt.current_branch", return_value="master")
    @patch("nt.dirty_files", return_value=0)
    @patch("nt.git")
    def test_merge_failure_without_conflicts_shows_git_error(self, git, *_):
        def fake_git(path, *args, check=True):
            if args[0] == "merge":
                return subprocess.CompletedProcess(args, 128, "", "fatal: unable to auto-detect email address")
            return subprocess.CompletedProcess(args, 0, "", "")
        git.side_effect = fake_git

        with (
            patch.object(nt.Path, "is_dir", return_value=True),
            patch("sys.stdout", io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            nt.assemble_train(self.project())

        message = str(raised.exception)
        self.assertIn("git merge failed", message)
        self.assertIn("auto-detect email address", message)
        self.assertNotIn("CONFLICT", message)


class LintTests(unittest.TestCase):
    @patch("nt.sys.exit")
    @patch("nt.sh")
    @patch("nt.current_branch", return_value="work")
    @patch("nt.default_branch", return_value="main")
    def test_lint_skips_missing_clones(self, _default, _branch, sh, _exit):
        sh.return_value = subprocess.CompletedProcess([], 0, "", "")
        missing = nt.Project(name="ghost", path=nt.ROOT / "does-not-exist", url="", pin="main")
        with patch.object(sys, "stdout", io.StringIO()):
            nt.cmd_lint([missing])
        for args, kwargs in sh.call_args_list:
            self.assertNotEqual(kwargs.get("cwd"), missing.path)


class TrainResolutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = nt.Path(temporary.name)
        self.repo = self.root / 'api'
        self.repo.mkdir()
        self.project = nt.Project('api', self.repo, '', 'main', [61])
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.com')
        self.git('config', 'core.hooksPath', '/dev/null')
        self.write_commit('base')
        self.git('switch', '-qc', 'pr')
        self.write_commit('right')
        self.git('update-ref', 'refs/nt/pr/61', 'HEAD')
        self.git('switch', '-q', 'main')
        self.write_commit('left')
        self.git('merge', '--no-ff', '--no-commit', 'refs/nt/pr/61', check=False)
        directory = self.root / 'trains' / 'api'
        directory.mkdir(parents=True)
        (self.repo / 'value').write_text('both\n')
        (directory / '61.patch').write_text(self.git('diff', 'AUTO_MERGE'))
        (directory / '61.json').write_text(json.dumps({
            'base_tree': self.git('rev-parse', 'HEAD^{tree}').strip(),
            'head': self.git('rev-parse', 'refs/nt/pr/61').strip(),
        }))
        (self.repo / 'value').write_text(self.git('show', 'AUTO_MERGE:value'))

    def git(self, *args, check=True):
        return subprocess.run(['git', '-C', str(self.repo), *args],
                              text=True, capture_output=True, check=check).stdout

    def write_commit(self, value):
        (self.repo / 'value').write_text(value + '\n')
        self.git('add', 'value')
        self.git('commit', '-qm', value)

    def test_resolution_preserves_both_merge_parents(self):
        parents = [self.git('rev-parse', ref).strip() for ref in ['HEAD', 'refs/nt/pr/61']]
        with patch.object(nt, 'ROOT', self.root):
            self.assertTrue(nt.resolve_train_merge(self.project, 61))
        self.assertEqual(self.git('show', '-s', '--format=%P').split(), parents)
        self.assertEqual((self.repo / 'value').read_text(), 'both\n')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_changed_pr_is_rejected_without_touching_conflicts(self):
        before = (self.repo / 'value').read_text()
        self.git('update-ref', 'refs/nt/pr/61', 'HEAD')
        with patch.object(nt, 'ROOT', self.root):
            self.assertFalse(nt.resolve_train_merge(self.project, 61))
        self.assertEqual((self.repo / 'value').read_text(), before)
        self.assertTrue(self.git('diff', '--name-only', '--diff-filter=U'))

    def test_changed_base_is_rejected_without_touching_conflicts(self):
        metadata = self.root / 'trains' / 'api' / '61.json'
        expected = json.loads(metadata.read_text())
        expected['base_tree'] = '0' * 40
        metadata.write_text(json.dumps(expected))
        before = (self.repo / 'value').read_text()
        with patch.object(nt, 'ROOT', self.root):
            self.assertFalse(nt.resolve_train_merge(self.project, 61))
        self.assertEqual((self.repo / 'value').read_text(), before)
