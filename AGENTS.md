# NicTool Workspace

## What this repository is

This metarepo assembles NicTool's constituent repositories as plain Git clones
and provides the shared Docker Compose development environment. It owns
workspace tooling, configuration, tests, and documentation; member application
source remains in the Git-ignored repositories declared by `mani.yaml`.

## The manifest is the source of truth

`mani.yaml` declares every member repository, its upstream URL, and its version
pin. Read it instead of trusting a repository list in prose. Per-part `env`
keys are:

- `pin` — a release tag (`v3.0.0` means a detached checkout at that tag) or a
  branch name (checkout and fast-forward from `origin`)
- `train` — an optional ordered list of upstream PRs for a temporary
  integration branch

No PR train is currently declared. Base new NicTool work on clean
`origin/master`, or on a fork default branch after it has synchronized from
upstream. Do not recreate a train unless `mani.yaml` intentionally declares
one again.

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
only as a deliberate cleanup action.

## Publishing issues and pull requests

Treat GitHub issues and pull requests as human-authored external
communications. Never create or publish one immediately, even when the task
initially asks to file an issue or open a PR.

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

Do not use `gh issue create`, `gh pr create`, or an equivalent publishing API
before this human-review gate has been satisfied.

## Making changes

1. Inspect the target member's status and fetch `origin`.
2. Create a branch from its clean upstream default branch. Use the same branch
   name in every affected repository for a cross-repository change.
3. Commit in each member repository and push to `fork`:
   `git -C <repo> push -u fork <branch>`
4. Draft the upstream PR title and body, then follow the human-review gate
   above before running
   `gh pr create --repo NicTool/<repo> --head <fork-owner>:<branch> --base <default>`.
5. After an upstream release is published, update the applicable `mani.yaml`
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
```

Run commands in the legacy container with:

```sh
docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c '...'
```

The legacy container bind-mounts `./NicTool/server` into
`/usr/local/nictool/server`. Template and htdocs edits are immediately visible.
Install changed Perl libraries inside the container because Apache loads them
from the installed path.

## Worktrees

Metarepo worktrees contain tracked workspace files, not the Git-ignored member
clones or `docker/.env`. Use metarepo worktrees only for workspace-owned
changes. Perform member-repository work in the local member clone or a
worktree created by that member repository.

Do not copy files over a dirty member checkout for testing, and do not restore
files with `git checkout --`. Hand work back to the local checkout or use an
explicit Compose override when validation requires the main Docker environment.
