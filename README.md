# NicTool Monorepo

This pulls together every piece of the NicTool DNS management stack -- the legacy Perl v2, the Node.js v3 API and web UI, shared libraries, and research notes -- so you can run them side by side from a single `docker compose up`.

The idea is straightforward: v2 running next to v3, sharing the same MariaDB, on the same machine. Compare behavior, contribute to v3, run end-to-end tests across both generations.

## What's in here

| Path | What it is | Upstream |
|------|-----------|----------|
| `api/` | v3 REST API (Hapi, MySQL2) | [NicTool/api](https://github.com/NicTool/api) |
| `server/` | v3 Web UI + configurator | [NicTool/server](https://github.com/NicTool/server) |
| `NicTool/` | Legacy Perl v2 (Apache + mod_perl) | [NicTool/NicTool](https://github.com/NicTool/NicTool) |
| `libs/validate/` | Joi-based DNS object validation | [NicTool/validate](https://github.com/NicTool/validate) |
| `libs/dns-zone/` | Zone import/export (BIND, tinydns, maradns, JSON) | [NicTool/dns-zone](https://github.com/NicTool/dns-zone) |
| `libs/dns-nameserver/` | Nameserver management | [NicTool/dns-nameserver](https://github.com/NicTool/dns-nameserver) |
| `libs/dns-resource-record/` | Resource record handling | [NicTool/dns-resource-record](https://github.com/NicTool/dns-resource-record) |
| `research/` | LLM-generated audits, gap analyses, design notes | [NicTool/research](https://github.com/NicTool/research) |

Every path is a plain git clone, declared in `mani.yaml` — the manifest that records which repos and which versions belong together. [mani](https://manicli.com) clones and enumerates them; `nt.py` keeps each checkout at its pinned release tag or branch (see below).

## Prerequisites

A handful of things on a fresh macOS machine. Everything else (Node 22, MariaDB 11, Perl) runs inside Docker containers.

Homebrew, if you don't already have it:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install the rest:

```sh
brew install colima docker docker-compose git mani uv gh
colima start
```

[mani](https://manicli.com) manages the member repos, [uv](https://docs.astral.sh/uv/) runs the workspace tool `nt.py`, and `gh` talks to GitHub for PR trains and release checks.

We use [Colima](https://github.com/abiosoft/colima) as the container runtime -- it's free, lightweight, and doesn't require a Docker Desktop license. Colima needs to be running before any `docker compose` or `make up-*` commands work. After a reboot, just `colima start` again.

> [Podman](https://podman.io/) also works if you prefer it, but the Makefile and compose file are written for the Docker CLI.

No Perl setup needed on your host -- the legacy v2 stack runs entirely inside Docker.

## Getting started

Clone, initialize, generate credentials, and bring up the stack:

```sh
git clone https://github.com/NicTool/monorepo.git
cd monorepo
make init
make env
make up
```

`make init` clones every repo in `mani.yaml` and checks each out at its pinned version. Node.js dependencies are installed inside the Docker containers during `make up`, so nothing is installed on your host.

> **SSH clone errors?** Some member repos have nested submodules (notably `api/.release`) that reference dependencies via SSH (`git@github.com:...`). If you don't have SSH keys configured for GitHub, initializing them will fail with "Permission denied (publickey)." Fix it by telling git to use HTTPS instead:
>
> ```sh
> git config --global url."https://github.com/".insteadOf "git@github.com:"
> ```
>
> Then re-run `make init`.

Day to day, three commands keep the workspace honest:

```sh
make status       # drift report: where is each repo vs its pin?
make sync         # fetch everything, move clean repos to their pins
make update       # any newer upstream releases? (make update W=1 writes them)
```

`nt.py` never touches a repo that has uncommitted changes or a checked-out
work branch — active work always wins over the manifest.

`make env` creates `docker/.env` with randomly generated passwords via `openssl rand` -- it won't overwrite an existing file, so it's safe to run more than once. Edit `docker/.env` directly to customize ports or credentials (see `docker/.env.example` for the full list).

Pick whichever slice of the stack you need:

```sh
make up          # v3 core (MariaDB + API)
make up-ui       # v3 full stack (MariaDB + API + Web UI)
make up-legacy   # Legacy Perl v2 (MariaDB + NicTool v2)
make up-all      # Everything at once
```

The first run builds all Docker images, which takes a few minutes. After that, layer caching keeps it fast.

Once the containers are healthy:

| Service | URL | What you should see |
|---------|-----|---------------------|
| v3 API | http://localhost:3000/documentation | Swagger/Hapi docs page |
| v3 Web UI | http://localhost:8080 | NicTool v3 login page |
| v2 Legacy (HTTP) | http://localhost:8082 | Classic NicTool login page |
| v2 Legacy (HTTPS) | https://localhost:8443 | Same, with self-signed cert |
| MariaDB | `localhost:3307` | Connect with any MySQL client |

All ports are configurable in `docker/.env`.

## Docker Compose profiles

| Profile | Services started |
|---------|-----------------|
| *(default)* | `db` + `api` |
| `ui` | `db` + `api` + `server` |
| `legacy` | `db` + `nictool-legacy` |
| `e2e` | `db` + `api` + `server` |
| `all` | All four services |

## Testing

All tests run inside containers -- nothing is installed on your host.

```sh
make test           # API + library tests (requires make up)
make test-api       # just the API tests
make test-server    # just the server tests (requires make up-ui)
make test-libs      # just the four libraries (no running services needed)
```

`make test-api` and `make test-server` exec into the running containers. `make test-libs` spins up ephemeral `node:22` containers for each library. The API integration tests need a running database, so run `make up` first.

The v2 container has its own Perl test suites. These run inside the container against the shared MariaDB:

```sh
make test-v2      # runs everything below in sequence
make test-v2-xt   # just the extended tests (see below)
```

`make test-v2` runs three things in order: the server unit tests, the client unit tests, and then the extended ("xt") integration tests. The xt tests exercise cross-group permissions, zone delegation, and other multi-object interactions that require a running database with seeded data. `make test-v2-xt` runs only that last step, which is useful when you're iterating on permission or delegation logic and don't want to wait for the full suite.

## Local development

The compose file bind-mounts source directories into each container, so code changes on your host are reflected immediately without rebuilding. Just restart the affected service:

```sh
docker compose --env-file docker/.env --profile all restart   # restart all
docker compose --env-file docker/.env restart api              # restart one
```

You only need `--build` when you change a Dockerfile or dependencies (`package.json`, `Makefile.PL`).

Tear down when you're done:

```sh
make clean        # stops everything and deletes volumes
```

## Day-to-day commands

```sh
make help         # list all targets
make logs         # tail logs from all services
make down         # stop everything (keeps data)
make clean        # stop everything and delete volumes (fresh start)
make status       # drift report for all repos
make sync         # fetch all repos, move clean ones to their pins
make update       # check upstream for newer release tags
make train        # assemble PR integration branches from mani.yaml
make test         # run v3 API + library tests (requires make up)
make test-api     # run v3 API tests only
make test-server  # run v3 server tests only (requires make up-ui)
make test-libs    # run library tests (no running services needed)
make test-v2      # run all v2 Perl tests (server, client, and extended; requires up-legacy)
make test-v2-xt   # run only v2 extended integration tests (permissions, delegation)
```

## Contributing from a fork

The manifest only knows about upstream -- `origin` in every repo points at
`NicTool/*` and is read-only. Forks are personal, so they live in each clone's
git config, never in `mani.yaml`. One command creates and wires them:

```sh
make fork                  # forks under your gh login
make fork OWNER=my-org     # or under an org you control
```

This forks any repo you haven't forked yet (via `gh`), adds a `fork` remote to
every clone, and fast-forwards existing forks from upstream. Re-run it any
time -- coming back after months away, it re-syncs your forks and repairs
missing remotes, reusing whatever owner the remotes already point at.

Then branch in the member repo, push to `fork`, and open a PR against
upstream:

```sh
git -C api checkout -b my-change
git -C api push -u fork my-change
gh pr create --repo NicTool/api --head <owner>:my-change --base main
```

Done with forks? `./nt.py fork --remove` drops the remotes; your forks on
GitHub stay put.

## Project structure

```
monorepo/
  docker/
    .env.example          # reference for environment variables
    .env                  # generated credentials (gitignored)
    generate-env.sh       # creates .env with random passwords
  docker-compose.yml      # all services, all profiles
  Makefile                # task runner
  mani.yaml               # manifest: repos, pins, PR trains
  nt.py                   # workspace tool: sync / status / update / train / fork
  api/                    # [repo] v3 REST API
  server/                 # [repo] v3 Web UI
  NicTool/                # [repo] Legacy Perl v2
  research/               # [repo] audits, gap analyses, design notes
  libs/
    validate/             # [repo] DNS validation
    dns-zone/             # [repo] zone import/export
    dns-nameserver/       # [repo] nameserver management
    dns-resource-record/  # [repo] resource record handling
```

Member repos are gitignored — this workspace records *intent* (pins, trains)
in `mani.yaml`, never member-repo content.

## Known issues

- `/swagger.json` returns a 500 due to a Joi version mismatch between the API and the swagger plugin. The API itself works fine -- it's just the generated schema that breaks.
- The legacy v2 entrypoint generates a test user (`nictest@test_group`) with a random password stored at `/usr/local/nictool/server/t/test.cfg` inside the container.
