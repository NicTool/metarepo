# Copyright (c) 2026, The NicTool Contributors

import re
import sys
from pathlib import Path


def classify(exit_code, log):
    if exit_code or re.search(r"^(?:#|ℹ)\s+(?:fail|cancelled)\s+[1-9]|^\s*not ok\b|^Result:\s*FAIL", log, re.MULTILINE):
        return "FAIL"
    if re.search(r"^(?:#|ℹ)\s+(?:skipped|todo)\s+[1-9]|^\s*(?:not )?ok\b[^\n]*#\s*(?:skip|todo)\b|All tests skipped", log, re.MULTILINE | re.IGNORECASE):
        return "INCOMPLETE"
    if not re.search(r"^(?:#|ℹ)\s+tests\s+[1-9]|^Files=\d+, Tests=[1-9]", log, re.MULTILINE):
        return "UNAVAILABLE"
    return "PASS"


if __name__ == "__main__":
    print(classify(int(sys.argv[1]), Path(sys.argv[2]).read_text(errors="replace")))
