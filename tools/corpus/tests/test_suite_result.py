# Copyright (c) 2026, The NicTool Contributors

import unittest

from suite_result import classify


class SuiteResultTests(unittest.TestCase):
    def test_pass_requires_test_evidence(self):
        self.assertEqual("PASS", classify(0, "# tests 4\n# pass 4\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n"))
        self.assertEqual("PASS", classify(0, "Files=2, Tests=4, 1 wallclock secs\nResult: PASS\n"))
        for log in ("", "command completed", "# tests 0\n# pass 0", "NOTESTS"):
            self.assertEqual("UNAVAILABLE", classify(0, log))

    def test_skips_todos_and_cancellations_are_not_passes(self):
        for marker in ("# skipped 1", "# todo 1", "ok 1 # skip unavailable", "ok 1 # TODO later", "All tests skipped: unavailable"):
            self.assertEqual("INCOMPLETE", classify(0, "# tests 4\n# pass 3\n" + marker))
        self.assertEqual("FAIL", classify(0, "# tests 4\n# cancelled 1"))

    def test_failures_cannot_be_hidden_by_exit_status(self):
        for log in ("# tests 4\n# fail 1", "not ok 1 - broken", "Result: FAIL", "ℹ tests 4\nℹ fail 1"):
            self.assertEqual("FAIL", classify(0, log))
        self.assertEqual("FAIL", classify(1, "# tests 4\n# pass 4"))

    def test_nested_suites_do_not_hide_a_skip(self):
        self.assertEqual("INCOMPLETE", classify(0, "# tests 4\n# skipped 1\n# tests 8\n# skipped 0"))
