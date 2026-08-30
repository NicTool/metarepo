import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

spec = importlib.util.spec_from_file_location("check", HOOKS / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def diff(path: str, *added: str, start: int = 10) -> str:
    body = "\n".join("+" + line for line in added)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{start},0 +{start},{len(added)} @@\n{body}\n")


class CommentLengthTests(unittest.TestCase):
    def test_three_line_comment_fails(self):
        problems = check.check_diff(diff("lib/x.pm", "# one", "# two", "# three", "my $x = 1;"))
        self.assertEqual(problems, ["lib/x.pm:10: 3-line comment; one line plus a link (brevity is the default)"])

    def test_two_lines_pass(self):
        self.assertEqual(check.check_diff(diff("lib/x.pm", "# one", "# two", "my $x = 1;")), [])

    def test_file_header_is_exempt(self):
        self.assertEqual(check.check_diff(diff("bin/x.pl", "#!/usr/bin/perl", "# a", "# b", "# c", start=1)), [])

    def test_pod_is_not_a_comment(self):
        added = ("=head1 NAME", "", "# not a comment", "# still pod", "# still pod", "=cut", "1;")
        self.assertEqual(check.check_diff(diff("lib/x.pm", *added)), [])

    def test_js_block_comment_counts_lines(self):
        added = ("/*", " * one", " * two", " * three", " */", "const x = 1")
        problems = check.check_diff(diff("lib/x.js", *added))
        self.assertEqual(len(problems), 1)
        self.assertIn("5-line comment", problems[0])

    def test_prose_files_are_ignored(self):
        self.assertEqual(check.check_diff(diff("README.md", "# a", "# b", "# c", "# d")), [])


class SayItOnceTests(unittest.TestCase):
    def test_comment_repeating_a_banner_fails(self):
        added = (
            "# DBD::mysql 5.x builds only against Oracle's MySQL client library.",
            "warn <<EOW;",
            "cpanm will pick DBD::mysql 5.x, which builds only against Oracle's",
            "MySQL client library, 8.0 or newer.",
            "EOW",
        )
        problems = check.check_diff(diff("server/Makefile.PL", *added))
        self.assertEqual(problems, [("server/Makefile.PL:10: comment repeats line 12: "
                                     "'builds only against oracle s' (say it once)")])

    def test_pod_is_neither_side(self):
        added = ("# ABSTRACT: REST/JSON transport for NicTool v3 API", "1;", "=head1 NAME",
                 "REST/JSON transport for NicTool v3 API", "=cut")
        self.assertEqual(check.check_diff(diff("lib/x.pm", *added)), [])

    def test_far_apart_text_is_not_nearby(self):
        text = "answer like the v2 server did"
        added = ("# " + text, *["1;"] * 60, f"ok($x, '{text}');")
        self.assertEqual(check.check_diff(diff("t/x.t", *added)), [])
        added = ("# " + text, *["1;"] * 10, f"ok($x, '{text}');")
        self.assertEqual(len(check.check_diff(diff("t/x.t", *added))), 1)

    def test_unrelated_comment_passes(self):
        added = ("# visible under cpanm -v only", "warn 'the client library is MariaDB';")
        self.assertEqual(check.check_diff(diff("server/Makefile.PL", *added)), [])


class WordChoiceTests(unittest.TestCase):
    def test_banned_word_in_comment(self):
        problems = check.check_diff(diff("lib/x.js", "// leverage the cache here", "cache.get(k)"))
        self.assertEqual(problems, ["lib/x.js:10: 'leverage' (AGENTS.md word choice)"])

    def test_banned_word_in_code_is_not_the_hook_s_job(self):
        self.assertEqual(check.check_diff(diff("lib/x.js", "const realm = auth.realm")), [])

    def test_hyphenated_and_case(self):
        problems = check.check_diff(diff("x.py", "# This is Load-Bearing", "x = 1"))
        self.assertEqual(len(problems), 1)

    def test_list_matches_agents_md(self):
        text = (ROOT / "AGENTS.md").read_text()
        section = text.split("## Word choice")[1].split("\n## ")[0]
        listed = set(re.findall(r"\*([a-z-]+)\*", section))
        self.assertEqual(listed, set(check.BANNED))


class SubjectTests(unittest.TestCase):
    def test_area_prefix_with_identifier_passes(self):
        self.assertEqual(check.check_message("Makefile.PL: say why DBD::mysql won't build here\n"), ([], []))

    def test_capitalised_opening_word_fails(self):
        problems, _ = check.check_message("Fix the thing\n")
        self.assertEqual(problems, ["subject opens with 'Fix'; lower-case opening word (commits and PRs)"])

    def test_identifier_opening_passes(self):
        self.assertEqual(check.check_message("DBD::mysql needs a newer client\n")[0], [])

    def test_release_and_merge_are_exempt(self):
        self.assertEqual(check.check_message("Release v2.42.0\n"), ([], []))
        self.assertEqual(check.check_message("Merge branch 'x'\n"), ([], []))

    def test_length(self):
        problems, notes = check.check_message("nt: " + "x" * 70 + "\n")
        self.assertIn("never over 72", problems[0])
        problems, notes = check.check_message("nt: " + "x" * 50 + "\n")
        self.assertEqual(problems, [])
        self.assertIn("aim under 50", notes[0])

    def test_banned_word_in_body(self):
        problems, _ = check.check_message("nt: tidy\n\nThis leverages the cache.\n")
        self.assertEqual(problems, [])
        problems, _ = check.check_message("nt: tidy\n\nA robust cache.\n")
        self.assertEqual(problems, ["message line 3: 'robust' (AGENTS.md word choice)"])

    def test_git_comment_lines_are_skipped(self):
        self.assertEqual(check.check_message("# Please enter the commit message\nnt: ok\n"), ([], []))


class HookEndToEndTests(unittest.TestCase):
    """Real git, temp repo, core.hooksPath at hooks/: the shims must run check.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@x"}
        self.git("init", "-q")
        self.git("config", "core.hooksPath", str(HOOKS))

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True,
                              text=True, check=check)

    def commit(self, path: str, content: str, message: str):
        (self.repo / path).write_text(content)
        self.git("add", path)
        return self.git("commit", "-q", "-m", message, check=False)

    def test_clean_commit_passes(self):
        proc = self.commit("x.pm", "# one line\nmy $x = 1;\n", "x: add a thing")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_pre_commit_rejects_long_comment(self):
        proc = self.commit("x.pm", "1;\n2;\n# a\n# b\n# c\n", "x: add a thing")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("3-line comment", proc.stderr)

    def test_commit_msg_rejects_capitalised_subject(self):
        proc = self.commit("x.pm", "1;\n", "Add a thing")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("lower-case opening word", proc.stderr)

    def test_range_mode_checks_every_commit(self):
        self.commit("x.pm", "1;\n", "x: base")
        self.git("branch", "base")
        self.commit("x.pm", "1;\n2;\n", "x: fine")
        (self.repo / "x.pm").write_text("1;\n2;\n3;\n")
        self.git("commit", "-q", "--no-verify", "-am", "Broken subject")
        proc = subprocess.run([sys.executable, str(HOOKS / "check.py"), "--range", "base..HEAD"],
                              cwd=self.repo, env=self.env, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("lower-case opening word", proc.stderr)


class CopyrightYearTests(unittest.TestCase):
    def setUp(self):
        self.year = check.datetime.now(tz=check.timezone.utc).year

    def test_stale_year_fails(self):
        problems = check.check_diff(diff("sql/x.sql", f"# Copyright 2004-{self.year - 1} Someone", start=1))
        want = (f"sql/x.sql:1: copyright runs to {self.year - 1}, "
                f"not {self.year} (a line you add carries today's year)")
        self.assertEqual(problems, [want])

    def test_current_year_passes(self):
        self.assertEqual(check.check_diff(diff("sql/x.sql", f"# Copyright 2004-{self.year} Someone", start=1)), [])

    def test_single_current_year_passes(self):
        self.assertEqual(check.check_diff(diff("sql/x.sql", f"# Copyright {self.year} Someone", start=1)), [])

    def test_no_year_passes(self):
        self.assertEqual(check.check_diff(diff("sql/x.sql", "# Copyright The Network People, Inc.", start=1)), [])

    def test_prose_files_are_checked_too(self):
        problems = check.check_diff(diff("README.md", f"Copyright 2004-{self.year - 1} Someone", start=1))
        self.assertEqual(len(problems), 1)

    def test_a_string_further_down_is_not_a_banner(self):
        line = f'    banner = "# Copyright 2004-{self.year - 1} Someone"'
        self.assertEqual(check.check_diff(diff("tests/t.py", line, start=200)), [])

class ProseTests(unittest.TestCase):
    def problems(self, text: str) -> list[str]:
        return check.check_prose(text)[0]

    def notes(self, text: str) -> list[str]:
        return check.check_prose(text)[1]

    def test_figurative_word_fails(self):
        self.assertEqual(len(self.problems("One wart, kept on purpose.")), 1)

    def test_every_hit_on_a_line_is_reported(self):
        self.assertEqual(len(self.problems("The wart quietly stayed.")), 2)

    def test_semicolon_fails(self):
        self.assertEqual(len(self.problems("It parsed; nobody noticed.")), 1)

    def test_wink_is_not_a_semicolon(self):
        self.assertEqual(self.problems("Not a character, do you? ;-)"), [])
        self.assertEqual(self.problems("Fair enough ;)"), [])

    def test_generated_by_trailer_fails(self):
        self.assertEqual(len(self.problems("Body.\n\nCo-Authored-By: Claude Fable 5")), 1)

    def test_run_on_sentence_fails(self):
        self.assertEqual(len(self.problems("word " * 31)), 1)

    def test_code_fence_is_exempt(self):
        text = "```\nDROP TABLE x; SELECT 1;\n```\n"
        self.assertEqual(self.problems(text), [])

    def test_inline_code_is_exempt(self):
        self.assertEqual(self.problems("Run `a; b` to start."), [])

    def test_hedges_are_never_flagged(self):
        text = "My best guess is that it may have failed. I think it might be the store."
        self.assertEqual(check.check_prose(text), ([], []))

    def test_trailing_clause_is_a_note_not_a_failure(self):
        problems, notes = check.check_prose("It mounts the sibling, which is why it runs.")
        self.assertEqual(problems, [])
        self.assertEqual(len(notes), 1)

    def test_rhetorical_closer_is_a_note(self):
        self.assertTrue(any("rhetorical" in n for n in self.notes("We fixed it.\n\nWhy not?")))

    def test_clean_body_passes(self):
        text = "The store allocated the id. The api is the only consumer.\n\n```\na; b\n```\n"
        self.assertEqual(check.check_prose(text), ([], []))


if __name__ == "__main__":
    unittest.main()
