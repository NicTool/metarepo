#!/usr/bin/env python3
"""Mechanical checks from AGENTS-elements-of-style.md on a diff and a commit
message: comment length, a comment repeating nearby text, the AGENTS.md word
list, and commit subject shape. Runs as the pre-commit and commit-msg hooks
(./nt.py sync points core.hooksPath here) and under ./nt.py lint.
Standard library only, so it runs wherever git does.
"""

import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath

# The list in AGENTS.md "Word choice"; tests/test_hooks.py keeps them equal.
BANNED = (
    "seam", "load-bearing", "ratchet", "leverage", "robust", "seamless",
    "ecosystem", "delve", "tapestry", "landscape", "realm", "utilize",
    "supercharge", "unlock", "crucial", "pivotal",
)
BANNED_RE = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, BANNED)) + r")(?![\w-])", re.IGNORECASE)

COMMENT_LINES_MAX = 2
SHARED_WORDS = 5
NEAR = 40
SUBJECT_MAX = 72
SUBJECT_AIM = 50
SUBJECT_EXEMPT = re.compile(r"^(Release v\d|Merge |Revert |fixup! |squash! )")
SUBJECT_AREA = re.compile(r"^[\w./@-]+(\([^)]*\))?!?: ")
CAPITALISED_WORD = re.compile(r"^[A-Z][a-z]+\b")

HASH = {".pl", ".pm", ".t", ".PL", ".py", ".sh", ".bash", ".yml", ".yaml",
        ".toml", ".conf", ".cfg", ".mk", ".rb", ".pp"}
HASH_NAMES = {"Makefile", "Dockerfile", ".gitignore", ".dockerignore", ".env"}
SLASH = {".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".c", ".h", ".go", ".java"}
DASH = {".sql"}

WORD_RE = re.compile(r"[a-z0-9]+")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def comment_style(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.name in HASH_NAMES or p.name.startswith("Makefile"):
        return "hash"
    if p.suffix in HASH:
        return "hash"
    if p.suffix in SLASH:
        return "slash"
    if p.suffix in DASH:
        return "dash"
    return None


def added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    """Map each changed file to its added lines as (new line number, text)."""
    files: dict[str, list[tuple[int, str]]] = {}
    path, lineno = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            name = raw[4:].split("\t")[0]
            path = None if name == "/dev/null" else name.removeprefix("b/")
            if path is not None:
                files.setdefault(path, [])
        elif raw.startswith(("--- ", "diff --git")):
            continue
        elif m := HUNK_RE.match(raw):
            lineno = int(m.group(1))
        elif path is None:
            continue
        elif raw.startswith("+"):
            files[path].append((lineno, raw[1:]))
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1
    return files


def classify(style: str, lines: list[tuple[int, str]]) -> list[tuple[int, str, str]]:
    """Tag each added line as (line number, kind, text): code, comment, or pod."""
    out = []
    in_pod = in_block = False
    for lineno, text in lines:
        s = text.strip()
        kind, body = "code", text
        if style == "hash":
            if re.match(r"^=[a-z]\w*", text):
                in_pod = not s.startswith("=cut")
                kind = "pod"
            elif in_pod:
                kind = "pod"
            elif s.startswith("#") and not s.startswith("#!"):
                kind, body = "comment", s.lstrip("#").strip()
        elif style == "dash":
            if s.startswith("--"):
                kind, body = "comment", s.lstrip("-").strip()
        elif style == "slash":
            if in_block:
                kind, body = "comment", s.split("*/")[0].lstrip("* ").strip()
                in_block = "*/" not in s
            elif s.startswith("/*"):
                kind, body = "comment", s[2:].split("*/")[0].strip("* ").strip()
                in_block = "*/" not in s
            elif s.startswith("//"):
                kind, body = "comment", s.lstrip("/").strip()
        out.append((lineno, kind, body))
    return out


def runs(tagged, kind: str):
    """Group consecutive lines of one kind into lists of (line number, text)."""
    current: list[tuple[int, str]] = []
    for lineno, k, text in tagged:
        if k == kind and current and lineno == current[-1][0] + 1:
            current.append((lineno, text))
        else:
            if current:
                yield current
            current = [(lineno, text)] if k == kind else []
    if current:
        yield current


def ngrams(run: list[tuple[int, str]]) -> dict[tuple[str, ...], int]:
    """Every SHARED_WORDS-word sequence in a run, with the line its first word is on."""
    words = [(lineno, w) for lineno, text in run for w in WORD_RE.findall(text.lower())]
    return {tuple(w for _, w in words[i:i + SHARED_WORDS]): words[i][0]
            for i in range(len(words) - SHARED_WORDS + 1)}


def check_diff(diff: str) -> list[str]:
    problems = []
    for path, lines in added_lines(diff).items():
        style = comment_style(path)
        if style is None or not lines:
            continue
        tagged = classify(style, lines)
        code_grams: dict[tuple[str, ...], int] = {}
        for run in runs(tagged, "code"):
            for gram, lineno in ngrams(run).items():
                code_grams.setdefault(gram, lineno)
        for run in runs(tagged, "comment"):
            start = run[0][0]
            if len(run) > COMMENT_LINES_MAX and start > 2:
                problems.append(f"{path}:{start}: {len(run)}-line comment; "
                                "one line plus a link (brevity is the default)")
            for gram, lineno in ngrams(run).items():
                other = code_grams.get(gram)
                if other is not None and abs(other - lineno) <= NEAR:
                    problems.append(f"{path}:{lineno}: comment repeats line {other}: "
                                    f"'{' '.join(gram)}' (say it once)")
                    break
        for lineno, kind, text in tagged:
            if kind == "comment" and (m := BANNED_RE.search(text)):
                problems.append(f"{path}:{lineno}: '{m.group(1)}' (AGENTS.md word choice)")
                break
    return problems


def check_message(message: str) -> tuple[list[str], list[str]]:
    """Return (problems, notes) for a commit message."""
    lines = [ln for ln in message.splitlines() if not ln.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [], []
    subject = lines[0].rstrip()
    problems, notes = [], []
    if not SUBJECT_EXEMPT.match(subject):
        if len(subject) > SUBJECT_MAX:
            problems.append(f"subject is {len(subject)} chars; never over {SUBJECT_MAX} (commits and PRs)")
        elif len(subject) > SUBJECT_AIM:
            notes.append(f"subject is {len(subject)} chars; aim under {SUBJECT_AIM} (commits and PRs)")
        description = SUBJECT_AREA.sub("", subject, count=1)
        if CAPITALISED_WORD.match(description):
            problems.append(f"subject opens with '{description.split()[0]}'; lower-case opening word (commits and PRs)")
    for lineno, text in enumerate(lines, 1):
        if m := BANNED_RE.search(text):
            problems.append(f"message line {lineno}: '{m.group(1)}' (AGENTS.md word choice)")
            break
    return problems, notes


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def report(problems: list[str], notes: list[str], label: str) -> bool:
    for note in notes:
        print(f"note: {label}: {note}", file=sys.stderr)
    for problem in problems:
        print(f"{label}: {problem}", file=sys.stderr)
    return not problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check the index (pre-commit)")
    mode.add_argument("--message", metavar="FILE", help="check a commit message file (commit-msg)")
    mode.add_argument("--range", metavar="BASE..HEAD", help="check every commit in a range")
    args = parser.parse_args()

    if args.staged:
        return 0 if report(check_diff(git("diff", "--cached", "-U0", "--no-color")), [], "staged") else 1
    if args.message:
        with open(args.message, encoding="utf-8", errors="replace") as fh:
            problems, notes = check_message(fh.read())
        return 0 if report(problems, notes, "commit message") else 1

    base, _, head = args.range.partition("..")
    ok = report(check_diff(git("diff", "-U0", "--no-color", f"{base}...{head}")), [], f"{base}...{head}")
    for sha in git("rev-list", "--reverse", f"{base}..{head}").split():
        problems, notes = check_message(git("log", "-1", "--format=%B", sha))
        ok &= report(problems, notes, sha[:7])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
