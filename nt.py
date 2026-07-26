#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""nt — NicTool workspace tool.

mani owns cloning and cross-repo commands; nt owns what mani can't express:

  sync    make each repo match its manifest pin (never clobbers claimed repos)
  status  drift report: pin vs HEAD, dirty files, ahead/behind
  update  check upstream for newer release tags, --write rewrites mani.yaml
  train   assemble a PR integration branch from env.train
  fork    create GitHub forks and wire 'fork' remotes (--remove to drop them)

Pins live in mani.yaml under each project's env.pin: a release tag means a
detached checkout at that tag; a branch name means checkout + fast-forward.
Forks are personal state: they live in each clone's git config, never in
mani.yaml, so the committed manifest carries no usernames.
"""

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "mani.yaml"
TAG_RE = re.compile(r"v?\d+\.\d+\.\d+$")
PR_REF = "refs/nt/pr"


@dataclass
class Project:
    name: str
    path: Path
    url: str
    pin: str
    train: list[int] = field(default_factory=list)

    @property
    def pin_is_tag(self) -> bool:
        return TAG_RE.fullmatch(self.pin) is not None

    @property
    def upstream_slug(self) -> str:
        return self.url.removeprefix("https://github.com/").removesuffix(".git")


def sh(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, capturing output; exit with a clear message on failure."""
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        sys.exit(f"error: {' '.join(args)} (in {cwd or ROOT})\n{proc.stderr.strip()}")
    return proc


def git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return sh(["git", *args], cwd=path, check=check)


def load_projects() -> list[Project]:
    """Parse mani.yaml into Project records; pins and trains come from env."""
    if not MANIFEST.exists():
        sys.exit(f"error: {MANIFEST} not found")
    doc = yaml.safe_load(MANIFEST.read_text())
    projects = []
    for name, spec in doc["projects"].items():
        env = spec.get("env") or {}
        if "pin" not in env:
            sys.exit(f"error: project {name} has no env.pin in mani.yaml")
        train = [int(n) for n in str(env.get("train", "")).split()]
        projects.append(Project(
            name=name,
            path=ROOT / spec.get("path", name),
            url=spec["url"],
            pin=str(env["pin"]),
            train=train,
        ))
    return projects


def current_branch(p: Project) -> str:
    """Return the checked-out branch name, or '' when HEAD is detached."""
    return git(p.path, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()


def dirty_files(p: Project, ignore_submodules: bool = False) -> int:
    """Count dirty entries; optionally ignore nested-submodule pointer drift (healable)."""
    args = ["status", "--porcelain", *(["--ignore-submodules=all"] if ignore_submodules else [])]
    return len(git(p.path, *args).stdout.splitlines())


def align_nested_submodules(p: Project) -> str:
    """Point member repos' own nested submodules at their recorded SHAs; note on failure."""
    if not (p.path / ".gitmodules").exists():
        return ""
    rc = git(p.path, "submodule", "update", "--init", "--recursive", "--quiet", check=False)
    return "" if rc.returncode == 0 else " (nested submodule update FAILED — SSH keys? see README)"


def ahead_behind(p: Project, upstream_ref: str) -> tuple[int, int]:
    out = git(p.path, "rev-list", "--left-right", "--count",
              f"HEAD...{upstream_ref}", check=False).stdout.split()
    return (int(out[0]), int(out[1])) if len(out) == 2 else (0, 0)


def default_branch(p: Project) -> str:
    """The branch a fresh clone starts on, per origin/HEAD."""
    ref = git(p.path, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    return ref.removeprefix("refs/remotes/origin/")


def parked_on_default(p: Project, branch: str) -> bool:
    """True when a repo merely sits where clone left it: default branch, no local commits."""
    return branch == default_branch(p) and ahead_behind(p, f"origin/{branch}")[0] == 0


def describe_head(p: Project) -> str:
    """One-line description of where a repo's HEAD is relative to its pin."""
    branch, dirty = current_branch(p), dirty_files(p)
    notes = [f"{dirty} dirty"] if dirty else []
    if p.pin_is_tag:
        head = git(p.path, "rev-parse", "HEAD").stdout.strip()
        at_pin = git(p.path, "rev-parse", "-q", "--verify",
                     f"refs/tags/{p.pin}^{{commit}}", check=False).stdout.strip() == head
        if branch and parked_on_default(p, branch):
            state = f"drift: on {branch}, pin is {p.pin}"
        elif branch:
            state = f"claimed: on {branch}"
        elif at_pin:
            state = f"ok: at {p.pin}"
        else:
            state = f"drift: detached at {head[:9]}, pin is {p.pin}"
    elif branch == p.pin:
        ahead, behind = ahead_behind(p, f"origin/{p.pin}")
        state = f"ok: on {p.pin}"
        if ahead:
            notes.append(f"{ahead} unpushed")
        if behind:
            notes.append(f"{behind} behind origin")
    elif branch:
        state = f"claimed: on {branch}"
    else:
        state = f"drift: detached, pin is branch {p.pin}"
    return state + (f"  ({', '.join(notes)})" if notes else "")


def cmd_status(projects: list[Project]) -> None:
    for p in projects:
        line = describe_head(p) if p.path.is_dir() else "missing: run nt sync"
        print(f"{p.name:<22} {p.pin:<10} {line}")


def ensure_remotes(p: Project) -> list[str]:
    """Keep origin matching the manifest; fork remotes belong to nt fork."""
    notes = []
    origin = git(p.path, "remote", "get-url", "origin", check=False).stdout.strip()
    if origin != p.url:
        git(p.path, "remote", "set-url", "origin", p.url)
        notes.append(f"origin repointed {origin or '(none)'} -> {p.url}")
    return notes


def checkout_pin(p: Project) -> str:
    """Move a repo to its pin if that is safe; report what happened."""
    if dirty_files(p, ignore_submodules=True):
        return "skipped: dirty working tree"
    branch = current_branch(p)
    if p.pin_is_tag:
        if branch and not parked_on_default(p, branch):
            return f"skipped: claimed by branch {branch}"
        git(p.path, "checkout", "-q", "--detach", f"refs/tags/{p.pin}^{{commit}}")
        return f"at {p.pin}{align_nested_submodules(p)}"
    if branch and branch != p.pin:
        return f"skipped: claimed by branch {branch}"
    git(p.path, "checkout", "-q", p.pin)
    ff = git(p.path, "merge", "--ff-only", f"origin/{p.pin}", check=False)
    if ff.returncode != 0:
        return f"on {p.pin}: not fast-forwardable from origin (local commits?)"
    return f"on {p.pin}, up to date with origin{align_nested_submodules(p)}"


def cmd_sync(projects: list[Project]) -> None:
    if sh(["mani", "sync", "--parallel"], check=False).returncode != 0:
        sys.exit("error: mani sync failed (is mani installed? brew install mani)")
    for p in projects:
        for note in ensure_remotes(p):
            print(f"{p.name}: {note}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: git(p.path, "fetch", "--tags", "--prune", "-q", "origin"), projects))
    for p in projects:
        print(f"{p.name:<22} {checkout_pin(p)}")


def latest_stable_tag(p: Project) -> str | None:
    """Newest vX.Y.Z tag on origin, by semver order; None if the repo has none."""
    out = git(p.path, "ls-remote", "--tags", "origin").stdout
    tags = {ref.rsplit("/", 1)[-1].removesuffix("^{}") for line in out.splitlines()
            if (ref := line.split("\t")[-1])}
    stable = [t for t in tags if TAG_RE.fullmatch(t)]
    if not stable:
        return None
    return max(stable, key=lambda t: [int(n) for n in t.lstrip("v").split(".")])


def rewrite_pins(changes: dict[str, str]) -> None:
    """Rewrite env.pin values in mani.yaml, preserving comments and layout."""
    lines, project = MANIFEST.read_text().splitlines(keepends=True), None
    for i, line in enumerate(lines):
        if m := re.match(r"^  (\S+):\s*$", line):
            project = m.group(1)
        if project in changes and (m := re.match(r"^(\s+pin:\s*)\S+(\s*)$", line)):
            lines[i] = f"{m.group(1)}{changes[project]}{m.group(2)}"
    MANIFEST.write_text("".join(lines))


def cmd_update(projects: list[Project], write: bool) -> None:
    changes = {}
    tagged = [p for p in projects if p.pin_is_tag]
    with ThreadPoolExecutor(max_workers=8) as pool:
        latest = dict(zip((p.name for p in tagged), pool.map(latest_stable_tag, tagged)))
    for p in projects:
        if not p.pin_is_tag:
            print(f"{p.name:<22} tracks branch {p.pin} (not tag-pinned, skipped)")
        elif latest[p.name] and latest[p.name] != p.pin:
            changes[p.name] = latest[p.name]
            print(f"{p.name:<22} {p.pin} -> {latest[p.name]}")
        else:
            print(f"{p.name:<22} {p.pin} is current")
    if changes and write:
        rewrite_pins(changes)
        print(f"\nwrote {len(changes)} pin(s) to mani.yaml — run: nt sync")
    elif changes:
        print(f"\n{len(changes)} update(s) available — rerun with --write to apply")


def fork_remote_url(p: Project) -> str:
    return git(p.path, "remote", "get-url", "fork", check=False).stdout.strip()


def gh_login() -> str:
    proc = sh(["gh", "api", "user", "--jq", ".login"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        sys.exit("error: gh isn't authenticated — run: gh auth login")
    return proc.stdout.strip()


def existing_fork_owner(projects: list[Project]) -> str | None:
    """The owner the wired fork remotes already agree on, if any."""
    owners = {url.removeprefix("https://github.com/").split("/")[0]
              for p in projects if (url := fork_remote_url(p))}
    if len(owners) > 1:
        sys.exit(f"error: fork remotes disagree on owner ({', '.join(sorted(owners))}) — "
                 "pick one: nt fork <owner>")
    return next(iter(owners), None)


def wire_fork(p: Project, owner: str, org_flag: list[str]) -> str:
    """Fork p upstream to owner if needed, sync it, and wire the 'fork' remote."""
    repo = p.upstream_slug.split("/")[1]
    url = f"https://github.com/{owner}/{repo}.git"
    notes = []
    if sh(["gh", "repo", "view", f"{owner}/{repo}", "--json", "name"], check=False).returncode != 0:
        forked = sh(["gh", "repo", "fork", p.upstream_slug, "--clone=false", *org_flag], check=False)
        if forked.returncode != 0:
            sys.exit(f"error: forking {p.upstream_slug} to {owner} failed:\n{forked.stderr.strip()}")
        notes.append("forked on GitHub")
    elif sh(["gh", "repo", "sync", f"{owner}/{repo}"], check=False).returncode == 0:
        notes.append("fork synced from upstream")
    else:
        notes.append("fork NOT synced (default branch diverged from upstream?)")
    current = fork_remote_url(p)
    if not current:
        git(p.path, "remote", "add", "fork", url)
        notes.append("fork remote added")
    elif current != url:
        git(p.path, "remote", "set-url", "fork", url)
        notes.append(f"fork remote repointed -> {url}")
    return ", ".join(notes)


def cmd_fork(projects: list[Project], owner: str | None, remove: bool) -> None:
    cloned = [p for p in projects if p.path.is_dir()]
    if remove:
        for p in cloned:
            if fork_remote_url(p):
                git(p.path, "remote", "remove", "fork")
                print(f"{p.name:<22} fork remote removed")
            else:
                print(f"{p.name:<22} no fork remote")
        print("\nyour GitHub forks are untouched — delete those on github.com if you want")
        return
    if len(cloned) < len(projects):
        missing = ", ".join(p.name for p in projects if p not in cloned)
        sys.exit(f"error: not cloned yet: {missing} — run nt sync first")
    login = gh_login()
    owner = owner or existing_fork_owner(projects) or login
    org_flag = ["--org", owner] if owner != login else []
    for p in projects:
        print(f"{p.name:<22} {wire_fork(p, owner, org_flag)}")


def pr_state(p: Project, number: int) -> str:
    """Ask GitHub whether a PR is open/merged/closed; 'unknown' if gh fails."""
    out = sh(["gh", "api", f"repos/{p.upstream_slug}/pulls/{number}",
              "--jq", 'if .merged then "merged" else .state end'], check=False)
    return out.stdout.strip() or "unknown"


def cmd_train(projects: list[Project], name: str | None) -> None:
    trains = [p for p in projects if p.train and (name is None or p.name == name)]
    if not trains:
        sys.exit(f"error: no project {'named ' + name if name else ''} with env.train in mani.yaml")
    for p in trains:
        assemble_train(p)


def assemble_train(p: Project) -> None:
    """Build train/<pin> = origin/<pin> + each train PR merged in order."""
    if not p.path.is_dir():
        sys.exit(f"error: {p.name} not cloned — run nt sync first")
    if dirty_files(p):
        sys.exit(f"error: {p.name} has a dirty working tree; commit or stash first")
    if p.pin_is_tag:
        sys.exit(f"error: {p.name} is tag-pinned; trains need a branch pin")
    prior = current_branch(p) or git(p.path, "rev-parse", "--short", "HEAD").stdout.strip()
    refspecs = [f"+refs/pull/{n}/head:{PR_REF}/{n}" for n in p.train]
    git(p.path, "fetch", "-q", "origin", p.pin, *refspecs)
    branch = f"train/{p.pin}"
    git(p.path, "checkout", "-q", "-B", branch, f"origin/{p.pin}")
    print(f"{p.name}: {branch} reset to origin/{p.pin} (was on {prior})")
    for n in p.train:
        state = pr_state(p, n)
        if state not in ("open", "unknown"):
            print(f"  PR #{n}: {state} upstream — remove it from the train in mani.yaml")
            continue
        merge = git(p.path, "merge", "--no-ff", "--no-edit", "-q",
                    "-m", f"train: merge PR #{n}", f"{PR_REF}/{n}", check=False)
        if merge.returncode != 0:
            conflicts = git(p.path, "diff", "--name-only", "--diff-filter=U").stdout.strip()
            git(p.path, "merge", "--abort", check=False)
            sys.exit(f"  PR #{n}: CONFLICT with the train so far, in:\n"
                     f"{conflicts}\n"
                     f"{p.name} left on {branch}; resolve by hand or reorder the train")
        print(f"  PR #{n}: merged ({state})")
    print(f"{p.name}: train assembled on {branch}; branch from here for new work")


def main() -> None:
    parser = argparse.ArgumentParser(prog="nt", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="drift report for every repo")
    sub.add_parser("sync", help="clone/fetch and move clean repos to their pins")
    up = sub.add_parser("update", help="check upstream for newer release tags")
    up.add_argument("--write", action="store_true", help="rewrite pins in mani.yaml")
    tr = sub.add_parser("train", help="assemble PR integration branch(es)")
    tr.add_argument("project", nargs="?", help="project name (default: all with env.train)")
    fk = sub.add_parser("fork", help="create GitHub forks and wire 'fork' remotes")
    fk.add_argument("owner", nargs="?",
                    help="GitHub user/org owning the forks "
                         "(default: whatever the remotes already use, else your gh login)")
    fk.add_argument("--remove", action="store_true",
                    help="remove fork remotes; GitHub forks are left alone")
    args = parser.parse_args()
    projects = load_projects()
    match args.cmd:
        case "status":
            cmd_status(projects)
        case "sync":
            cmd_sync(projects)
        case "update":
            cmd_update(projects, args.write)
        case "train":
            cmd_train(projects, args.project)
        case "fork":
            cmd_fork(projects, args.owner, args.remove)


if __name__ == "__main__":
    main()
