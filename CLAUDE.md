# NicTool Workspace

## What this repo is

A workspace (meta-repo) that assembles NicTool's constituent repos as plain git
clones and provides a unified Docker Compose dev environment. The workspace
contains no application code — only `mani.yaml`, `nt.py`, `Makefile`,
`docker/`, and this doctrine. The member repos are gitignored; the workspace
records intent (pins, trains), never their content.

## The manifest is the source of truth

`mani.yaml` declares every repo: upstream URL, version pin, and PR train.
**Read `mani.yaml` — do not trust any repo list written in prose, including in
this file.** Per-project `env` keys:

- `pin` — a release tag (`v3.0.0` → detached checkout at the tag) or a branch
  name (checkout + fast-forward from origin)
- `train` — ordered upstream PR numbers merged into an integration branch

## Tool ownership — do not blur these

| tool | owns |
|---|---|
| `mani` | cloning, `.gitignore` upkeep, running commands across repos (`mani run status`) |
| `nt.py` | pins (`sync`), drift (`status`), release updates (`update`), PR trains (`train`), fork remotes (`fork`) |
| plain `git` in each repo | branches, commits, pushes — normal development |
| `docker compose` / `make` | building, running, testing everything |

Do not add another wrapper, task runner, or dependency graph. The workspace
has no submodules; some member repos have their own nested submodules (e.g.
`.release`), which `nt sync` initializes and aligns — never manage them by
hand. Do not install project dependencies or run tests on the host; everything
runs in containers.

## Repo states (from `nt.py status`)

- **ok** — checked out at its pin
- **claimed** — a work branch is checked out; tooling never touches a claimed
  repo, and `nt sync` skips it until the branch is gone
- **dirty** — uncommitted changes; also never touched
- **drift** — detached somewhere that isn't the pin; `nt sync` fixes this

## Remotes

Every repo: `origin` = upstream `NicTool/*` (no push access; `nt sync` heals
it to match the manifest), `fork` = the user's fork (push here). Forks are
personal state wired into each clone's git config by `nt fork` — they never
appear in `mani.yaml`. `nt fork` creates missing GitHub forks, fast-forwards
existing ones from upstream, and repairs the remotes; it reuses whatever owner
the remotes already point at. `nt fork --remove` drops the remotes. If a repo
has no `fork` remote, run `nt fork` before pushing. Never push to `origin`.

## Making changes (single repo or a package of changes)

1. Branch inside each affected repo: `git -C <repo> checkout -b <branch>`.
   For a cross-repo change, use the same branch name in every affected repo.
2. Commit inside each repo; push each branch to the fork:
   `git -C <repo> push -u fork <branch>`
3. Open PRs against upstream, from the fork's branch:
   `gh pr create --repo NicTool/<repo> --head <fork-owner>:<branch> --base <default>`
   (`NicTool/NicTool` uses `master`; every other repo uses `main`. The fork
   owner is whoever the repo's `fork` remote points at — check with
   `git -C <repo> remote get-url fork`.)
4. The workspace repo needs no commit — member repos are gitignored.

Commits to the workspace repo itself are only for tooling: `mani.yaml` (pin and
train changes), `nt.py`, `Makefile`, `docker/`, this file.

## PR trains

A train (declared in `mani.yaml` `env.train`) is an ordered set of open
upstream PRs that future work must sit on top of. `nt.py train` builds branch
`train/<pin>` = `origin/<pin>` + each PR merged in order, and stops with the
conflicting file list if a merge fails.

- `train/*` branches are throwaway; `nt train` recreates them with `-B`.
  **Never commit directly on a `train/*` branch** — branch off it.
- When a train PR merges upstream, `nt train` flags it; remove it from
  `mani.yaml` and re-run.
- New commits destined for an open PR are cherry-picked onto that PR's own
  branch and pushed to the fork — not pushed from the train branch.

## Docker environment

| service | what | internal hostname | port |
|---|---|---|---|
| `db` | MariaDB 11 | `db` | 3306 (host: 3307) |
| `api` | v3 Node.js REST API | `api` | 3000 |
| `server` | v3 web UI (profile: ui) | `server` | 8080 |
| `nictool-legacy` | v2 Perl (profile: legacy) | `nictool-legacy` | 8082 |

```sh
make up            # db + api          make test        # v3 API + lib tests
make up-legacy     # db + v2 Perl      make test-v2-xt  # v2 SOAP extended tests
```

Run commands in a container:

```sh
docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c '...'
```

The `nictool-legacy` container bind-mounts `./NicTool/server` into
`/usr/local/nictool/server`. Edits to templates/htdocs are visible immediately;
**changes to Perl libs need `make install` inside the container** because
Apache loads them from the installed path, not the bind mount.

## Worktrees

Claude Code worktrees carry the workspace files but not the member repos'
context. `docker compose` must run from the main workspace directory (where
`docker/.env` lives). When testing member-repo changes from a worktree, copy
the modified files into the main workspace's repo (that's what is
bind-mounted), test, then restore with `git -C <repo> checkout -- <path>`.
