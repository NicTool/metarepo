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

Every path is a git submodule pointing to the NicTool org upstream. If you want to contribute from your own fork, `make fork` sets that up automatically (see below).

## Prerequisites

A handful of things on a fresh macOS machine. The versions match what the Dockerfiles use internally (Node 22, MariaDB 11, Debian bookworm for legacy Perl).

Homebrew, if you don't already have it:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install the rest:

```sh
brew install colima docker docker-compose node@22 pnpm git
colima start
```

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

`make init` checks out all submodules recursively, then runs `pnpm install` to wire up the Node.js workspace. `make env` creates `docker/.env` with randomly generated passwords via `openssl rand` -- it won't overwrite an existing file, so it's safe to run more than once. Edit `docker/.env` directly to customize ports or credentials (see `docker/.env.example` for the full list).

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

v3 Node.js tests use the built-in `node:test` runner. From the monorepo root:

```sh
make test
```

This runs `pnpm --recursive test`, which hits every package with a `test` script: the API, server, and all four libraries. The API integration tests need a running database -- if you've already run `make up`, the MariaDB container should be there.

For end-to-end tests against running containers:

```sh
make up-all
docker compose exec api npm test       # v3 API (339 tests)
docker compose exec server npm test     # v3 Server
```

The v2 container has its own Perl test suites. These run inside the container against the shared MariaDB:

```sh
make test-v2      # runs server, client, and permission/delegation tests
make test-v2-xt   # just the permission & delegation tests
```

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
make sync         # update all submodules to latest from their tracked branch
make test         # run v3 Node.js tests
make test-v2      # run all v2 Perl tests (requires up-legacy)
make install      # reinstall Node.js dependencies
```

## Contributing from a fork

The submodules point to the NicTool org by default. To fork everything into your own GitHub account and repoint the submodules:

```sh
make fork
```

This uses `gh` to fork each upstream repo, then sets `origin` to your fork and `upstream` to NicTool. You'll need `gh auth login` first.

To pull in the latest from upstream at any point:

```sh
make sync
```

## Project structure

```
monorepo/
  docker/
    .env.example          # reference for environment variables
    .env                  # generated credentials (gitignored)
    generate-env.sh       # creates .env with random passwords
  docker-compose.yml      # all services, all profiles
  Makefile                # task runner
  pnpm-workspace.yaml     # Node.js workspace config
  package.json            # monorepo root (test + lint scripts)
  api/                    # [submodule] v3 REST API
  server/                 # [submodule] v3 Web UI
  NicTool/                # [submodule] Legacy Perl v2
  research/               # [submodule] audits, gap analyses, design notes
  libs/
    validate/             # [submodule] DNS validation
    dns-zone/             # [submodule] zone import/export
    dns-nameserver/       # [submodule] nameserver management
    dns-resource-record/  # [submodule] resource record handling
```

## Known issues

- `/swagger.json` returns a 500 due to a Joi version mismatch between the API and the swagger plugin. The API itself works fine -- it's just the generated schema that breaks.
- The legacy v2 entrypoint generates a test user (`nictest@test_group`) with a random password stored at `/usr/local/nictool/server/t/test.cfg` inside the container.
