# NicTool Workspace

## What this repository is

This metarepo assembles NicTool's constituent repositories as plain Git clones
and provides the shared Docker Compose development environment. It owns
workspace tooling, configuration, tests, and documentation; member application
source remains in the Git-ignored repositories declared by `mani.yaml`.

Two companion guides ride along in this repo and apply to all work:

- `AGENTS-elements-of-style.md` — house style for prose: comments, commits, PRs,
  issues, reviews, docs
- `AGENTS-architecture-first-principles.md` — engineering doctrine for design
  decisions in every member repository

## The manifest is the source of truth

`mani.yaml` declares every member repository, its upstream URL, and its version
pin. Read it instead of trusting a repository list in prose. Per-part `env`
keys are:

- `pin` — a release tag (`v3.0.0` means a detached checkout at that tag) or a
  branch name (checkout and fast-forward from `origin`)
- `train` — an optional ordered list of upstream PRs for a temporary
  integration branch

`mani.yaml` temporarily declares the v2 REST bridge trains for NicTool#365 and
api#61. Run `./nt.py train` to assemble them for integration testing; do not
use the resulting `train/*` branches as bases for unrelated work. Remove each
train after its PR is merged.

## Tool ownership

| Tool | Owns |
|---|---|
| `mani` | Cloning, `.gitignore` upkeep, and commands across member repositories |
| `nt.py` | Pins, drift reporting, release updates, optional PR trains, and fork remotes |
| Plain `git` inside a member repository | Branches, commits, and pushes |
| `docker compose` / `make` | Building, running, and testing member applications |
| `uv` / `uvx` | Running and validating the workspace's Python tooling |

Do not add another wrapper, task runner, or dependency graph. The metarepo has
no submodules; some member repositories have nested submodules such as
`.release`, which `./nt.py sync` initializes and aligns. Do not manage those
nested submodules separately.

Install and test member-project dependencies in containers. Run the workspace
tool and its checks on the host through `uv`:

```sh
uv run --with pyyaml==6.0.2 python -m unittest -v
uvx ruff check .
```

## Member-repository states

`./nt.py status` reports:

- **ok** — the checkout is at its manifest pin
- **claimed** — a work branch is checked out; `./nt.py sync` may fetch and
  repair remotes but does not move the worktree
- **dirty** — the checkout has uncommitted changes; `./nt.py sync` does not
  move the worktree
- **drift** — a detached checkout is not at its pin; `./nt.py sync` moves a
  clean checkout back to the pin

Never discard, reset, or overwrite a claimed or dirty member repository to
make the workspace match the manifest.

## Remotes and clean bases

In every member repository:

- `origin` is the upstream `NicTool/*` repository and is the source of clean
  base branches and release tags
- `fork` is the user's GitHub fork and is the push target

`./nt.py fork` creates or synchronizes GitHub forks and repairs local `fork`
remotes. Use `./nt.py fork --part <manifest-name>` to operate on one member.
`./nt.py fork --remove` removes only local `fork` remotes; it does not change
`origin` or delete GitHub forks. Never push contribution branches to `origin`.

Merged work does not require a persistent integration branch. Fetch upstream
and base subsequent work on the upstream default branch (`master` for
`NicTool/NicTool`, `main` for every other current member), or on the equivalent
fork branch after `./nt.py fork` reports that it synchronized successfully.
Keep local feature branches until their work is safely upstream; delete them
only as a deliberate cleanup action, as described below.

## Branches are single-use; main stays linear

PRs land on the default branch as one squash commit, so `main` (or `master`)
is a straight line of reviewed changes. Work with that, not against it:

- One branch, one PR. Once the PR is squash-merged, the branch is finished.
  Do not add commits to it for a follow-up: the squash replaced its commits
  with a new one, so the old branch now conflicts with `main`, and a second
  PR from it shows the already-merged diff again. metarepo#10 became
  unmergeable exactly this way.
- Start every follow-up from a fresh `origin/main` on a new branch, even when
  it continues the same piece of work.
- Bring a branch up to date by rebasing onto `origin/main` and pushing with
  `--force-with-lease`. Never merge `main` into a branch, and never put a
  merge commit on `main`.
- After the squash lands, delete the branch. Git cannot see that a squashed
  branch is merged, so `git branch -d` refuses; prove it yourself, then force
  it:

  ```sh
  git fetch origin && git diff --stat origin/main <branch>   # empty = nothing lost
  git branch -D <branch>
  git push fork --delete <branch>
  git fetch --prune fork
  ```

  A branch whose PR merged upstream is safely upstream; deleting it is the
  deliberate cleanup the previous section refers to.
- The same applies in member repositories; `./nt.py sync` never moves a
  claimed checkout, so a finished branch left checked out keeps the member
  off its pin until someone deletes it.

## Never post to GitHub without human review (hard rule)

Nothing agent-authored may appear on GitHub without a human approving the exact
content first. This applies to every visible artifact: issues, pull requests,
issue and PR comments, code review submissions, discussions, releases, and any
other public or collaborator-visible write. Read-only GitHub usage (`gh issue
view`, `gh pr checks`, searches) is unrestricted; every write needs the gate.

The co-maintainers treat LLM slop on upstream trackers as a serious problem.
One careless comment costs trust that is expensive to win back.

For issues and PRs specifically:

1. Investigate the behavior and reproduce it when possible. If the reported
   problem cannot be reproduced, stop and report that result; do not invent a
   replacement issue merely to produce an upstream artifact.
2. Draft the exact title and body, keeping both concise, factual, and limited
   to verified evidence. Omit speculation, process narration, apologies, and
   unnecessary implementation prescriptions.
3. Show the complete draft to the user and wait for explicit approval of that
   exact text. The user may edit it or ask for a shorter version. An earlier
   general request to "file an issue" or "open a PR" is not approval to skip
   this review.
4. After approval, publish the reviewed text unchanged. If new evidence
   requires a material rewrite, present the revised draft for approval again.

Do not use `gh issue create`, `gh pr create`, `gh pr review`, `gh issue
comment`, or any equivalent publishing API before this human-review gate has
been satisfied. Pushing commits to the user's own fork is exempt: forks are
personal state, and a PR is only opened after the gate.

## Making changes

1. Inspect the target member's status and fetch `origin`.
2. Create a branch from its clean upstream default branch. Use the same branch
   name in every affected repository for a cross-repository change.
3. Commit in each member repository and push to `fork`:
   `git -C <repo> push -u fork <branch>`
4. Draft the upstream PR title and body, then follow the human-review gate
   above before running
   `gh pr create --repo NicTool/<repo> --head <fork-owner>:<branch> --base <default>`.
5. After the PR is squash-merged, delete the branch and start any follow-up
   from a fresh default branch.
6. After an upstream release is published, update the applicable `mani.yaml`
   pin in a separate metarepo change. A merged commit on `main` is not a
   release tag.

Member-repository contents are Git-ignored by the metarepo, so member code
changes are never committed here. Metarepo commits are for workspace-owned
files such as `mani.yaml`, `nt.py`, `Makefile`, `docker-compose.yml`,
`docker/`, tests, and agent guidance.

## Documentation voice

Preserve the repository author's intentionally informal, human voice.

- Keep deliberately lower-case tool and technology names in prose, such as
  `docker`, `colima`, `node`, `perl`, and `db`. Do not normalize them to
  official brand capitalization merely for style.
- Prefer `db` or `DB` over naming the database implementation unless the
  distinction is technically relevant.
- Preserve colloquial wording, humour, and personality when they do not obscure
  the meaning. Do not rewrite documentation into corporate or promotional
  language.
- Correct genuine spelling mistakes, grammatical errors, ambiguity, and factual
  inaccuracies, but do not present intentional informality as an error.
- In reviews, distinguish required corrections from optional stylistic
  suggestions.

## Comments in member-repository code

Keep comments rare and high-signal.

- Assume domain familiarity; do not narrate control flow, syntax, or dependency
  documentation.
- Match the surrounding file's comment density.
- Comment non-local constraints or invariants only when the code cannot make
  them obvious. Keep the explanation to the shortest useful clause.
- Put implementation history, debugging notes, and verification results in
  commits and PR descriptions.
- Review every added comment before pushing; remove anything that does not
  protect understanding or correctness.

## Data access goes through the store layer (hard rule)

v3's data stores are pluggable by design: every entity reaches its backend
through `lib/<entity>/store/` — a `base.js` interface contract, `mysql.js`,
`file.js` (json/toml), and stubs for backends not yet implemented — selected at
import time by `storeType()`. mysql is the complete backend today; mongodb and
elasticsearch are declared stubs whose every method throws `not yet
implemented`.

New code must not import `Mysql` directly. Queries belong behind an interface
method in a store module. A subsystem with no file-store implementation gets a
loud stub, not a silent hard dependency on mysql. This is what keeps "ditch SQL
entirely" and browser-mode ("look ma, no server!") reachable instead of
aspirational — see "brokers over backends" in
`AGENTS-architecture-first-principles.md`.

When reviewing, treat a direct `mysql2` import outside a `store/` module as a
blocking finding, the same category as a bypassed permission check. A test in
the api (`lib/store-access.test.js`) fails on any such import; keep it green.

## Word choice

Write like the maintainer, not like an LLM. Never use these tell-tale words in
code, comments, commit messages, PRs, issues, or replies: *seam*, *load-bearing*,
*ratchet*, *leverage*, *robust*, *seamless*, *ecosystem*, *delve*, *tapestry*,
*landscape*, *realm*, *utilize*, *supercharge*, *unlock*, *crucial*, *pivotal*.
Prefer plain direct words and the project's own vocabulary: store, backend,
broker, query, export. If a sentence sounds like a press release, shorten it
until it doesn't.

## Docker environment

| Service | Purpose | Internal hostname | Port |
|---|---|---|---|
| `db` | shared DB | `db` | 3306 (host 3307) |
| `api` | v3 Node.js REST API | `api` | 3000 |
| `server` | v3 web UI | `server` | 8080 |
| `nictool-legacy` | v2 Perl | `nictool-legacy` | 80/443 (host 8082/8443) |

```sh
make up            # db + api
make test          # v3 API + library tests
make up-legacy     # db + v2 Perl
make test-v2-xt    # v2 SOAP extended tests
make test-v2-rest  # supported v2 REST bridge extended tests
```

Run commands in the legacy container with:

```sh
docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c '...'
```

The legacy container bind-mounts `./NicTool/server` into
`/usr/local/nictool/server`. Template and htdocs edits are immediately visible.
Install changed Perl libraries inside the container because Apache loads them
from the installed path.

### Container runtime on this Mac

docker runs through colima, which is not started at boot. If `docker ps`
fails with a socket error, run `colima start` first. The VM uses the vz
backend (macOS Virtualization.Framework) with virtiofs mounts and rosetta;
recreate it with `colima delete` + `colima start --vm-type=vz
--vz-rosetta --mount-type virtiofs` if it ever needs rebuilding. Deleting the
VM loses images and volumes; the db re-initializes from `api/sql` on next
`make up`.

`make env` (via `docker/generate-env.sh`) generates `docker/.env` only if
missing. The db bakes credentials in at first initialization, so regenerating
`.env` later orphans the existing `db-data` volume — wipe it (`make clean`)
and let init run again rather than debugging access-denied errors.

While the REST bridge PRs are in flight, `mani.yaml` declares their trains.
README's "REST bridge integration" section covers the temporary settings and
their removal.

## Worktrees

Metarepo worktrees contain tracked workspace files, not the Git-ignored member
clones or `docker/.env`. Use metarepo worktrees only for workspace-owned
changes. Perform member-repository work in the local member clone or a
worktree created by that member repository.

Do not copy files over a dirty member checkout for testing, and do not restore
files with `git checkout --`. Hand work back to the local checkout or use an
explicit Compose override when validation requires the main Docker environment.
