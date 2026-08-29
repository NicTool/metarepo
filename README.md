# NicTool Metarepo

This repo pulls together v2 and v3 of NicTool so you can run them side by side
from one workspace. For now it's used to run v2 alongside v3 against the same
DB, compare behaviour, run end-to-end tests, etc., all toward hastening the
release of v3 through the good graces of Sir Simerson.

## What's in here

| Path | What it is | Upstream |
|------|-----------|----------|
| `api/` | v3 REST API (Hapi, MySQL2) | [NicTool/api](https://github.com/NicTool/api) |
| `server/` | v3 Web UI + configurator | [NicTool/server](https://github.com/NicTool/server) |
| `NicTool/` | old-school Perl v2 (Apache + mod_perl) | [NicTool/NicTool](https://github.com/NicTool/NicTool) |
| `libs/validate/` | Joi-based DNS object validation | [NicTool/validate](https://github.com/NicTool/validate) |
| `libs/dns-zone/` | Zone import/export (BIND, tinydns, JSON, whatever) | [NicTool/dns-zone](https://github.com/NicTool/dns-zone) |
| `libs/dns-nameserver/` | Nameserver management | [NicTool/dns-nameserver](https://github.com/NicTool/dns-nameserver) |
| `libs/dns-resource-record/` | Resource record handling | [NicTool/dns-resource-record](https://github.com/NicTool/dns-resource-record) |
| `research/` | LLM-assisted audits, gap analyses, design notes | [NicTool/research](https://github.com/NicTool/research) |

Every path is a plain git clone, declared in `mani.yaml` — the manifest that records which repos and which versions belong together. [mani](https://manicli.com) clones and enumerates them; Vibe-coded `nt.py` keeps each checkout at its pinned release tag or branch (see below).

## Prerequisites

The idea is to require only a few deps on a fresh macOS machine, with everything
else such as node, db, perl, etc. running inside docker containers.

Start with [Homebrew](https://brew.sh/) and a clean docker environment such as [colima](https://colima.run/):

```sh
brew install colima docker docker-compose git mani uv gh
colima start
```

[mani](https://manicli.com) manages the member repos, [uv](https://docs.astral.sh/uv/) runs the workspace tool `nt.py`, and `gh` talks to GitHub. There should be no special Perl or nodejs dependency dance required on your workstation.

> [Podman](https://podman.io/) should also work, but the Makefile and compose file are written for the Docker CLI.


## Getting started

Clone, init, generate credentials, and bring up the full stack:

```sh
git clone https://github.com/NicTool/metarepo.git
cd metarepo
make init
make env
make up-all
```

`make init` clones every repo in `mani.yaml` and checks each out at its pinned
version. `make up-all` then installs the component deps inside the docker
containers.

Day to day, three commands keep the workspace tidy:

```sh
make status       # drift report: where is each repo vs its pin?
make sync         # fetch everything, move clean repos to their pins
make update       # any newer upstream releases? (make update W=1 writes them)
```

`nt.py` should never touch a repo that has uncommitted changes or a checked-out
work branch; active work takes precedence over the pre-defined mani-fest.

`make env` creates `docker/.env`, if it doesn't already exist, with randomly
generated passwords via `openssl rand`. Edit `docker/.env` directly to
customize ports or credentials (see `docker/.env.example` for the full list).

Working on a sub-part of the full NicTool v2+v3 stack is also possible:

```sh
make up          # v3 core (DB + API)
make up-ui       # v3 full stack (DB + API + Web UI)
make up-legacy   # Legacy Perl v2 (DB + API + NicTool v2)
make up-all      # Everything at once
```

The first run without a cache builds the selected docker images, so it may take
a while.

Setting this up on a linux server instead of a Mac, or upgrading an existing
v2 database into it? See [docs/linux-server.md](docs/linux-server.md).

Once the containers are healthy, defaults are:

| Service | URL | What you should see |
|---------|-----|---------------------|
| v3 API | http://localhost:3000/documentation | Swagger/Hapi docs page |
| v3 Web UI | http://localhost:8080 | NicTool v3 login page |
| v2 Legacy (HTTP) | http://localhost:8082 | Classic NicTool login page |
| v2 Legacy (HTTPS) | https://localhost:8443 | Same, with self-signed cert |
| DB | `localhost:3307` | Connect with any MySQL client |

## Docker Compose profiles

| Profile | Services started |
|---------|-----------------|
| *(default)* | `db` + `api` |
| `ui` | `db` + `api` + `server` |
| `legacy` | `db` + `api` + `nictool-legacy` |
| `e2e` | `db` + `api` + `server` |
| `test` | One-off v2 Playwright runner |
| `all` | All four services |

The v2 GUI in `nictool-legacy` talks to the v3 api over REST. To point it back
at its own SOAP endpoint, set `NICTOOL_DATA_PROTOCOL=soap`,
`NICTOOL_SERVER_HOST=localhost`, and `NICTOOL_SERVER_PORT=8082` in
`docker/.env`. The v2 test targets set their protocol explicitly either way.

## REST bridge integration

While api#61 and NicTool#365 are open, `mani.yaml` declares trains for both. A
fresh workspace can assemble the exact integration branches without recording a
personal fork:

```sh
make init
make train
```

The api depends on `@nictool/validate` `^1.0.0`; `docker-compose.yml` mounts
the manifest's `libs/validate` checkout over the installed copy so the api runs
whatever the manifest pins. validate#31 is merged but not yet released, so the
manifest follows validate's `main` until the next release tag replaces it. Once
the companion PRs are merged and released, remove the manifest trains and
restore the release pins.

`api_node_modules` is a named volume seeded from the image on first start, so a
changed dependency only takes effect after `make clean` (or `docker volume rm
nictool-metarepo_api_node_modules`).

## Testing

All tests run inside containers.

```sh
make test           # API + library tests (requires make up)
make test-api       # just the API tests
make test-server    # just the server tests (requires make up-ui)
make test-libs      # just the four libraries (no running services needed)
```

`make test-api` and `make test-server` exec into the running containers.
`make test-libs` spins up ephemeral `node:22` containers for each library.
The API integration tests require `make up` first.

The v2 container has its own Perl test suites running inside the container against the shared DB:

```sh
make test-v2          # all v2 unit and extended tests through SOAP
make test-v2-soap     # explicit name for make test-v2
make test-v2-rest     # supported REST bridge extended tests
make test-v2-e2e-rest # v2 browser suite through REST
make test-v2-unit     # server and client unit tests with SOAP defaults
make test-v2-xt       # all extended tests through SOAP
make test-v2-xt-rest  # supported extended tests through REST
```

`make test-v2` and `make test-v2-soap` run the server and client unit tests,
then every extended ("xt") test through SOAP. The REST bridge target runs
`xt/14_permissions.t`, `xt/16_delegation.t`, and `xt/20_permission.t`, the
extended tests supported by both protocols. Each target sets its endpoint,
protocol, and test config explicitly, regardless of the container defaults.
The browser target runs in a pinned Playwright container, installs its node
packages there, and uses the account generated when `nictool-legacy` starts.

## Local development

The compose file bind-mounts source directories into each container, so code changes on your host are reflected immediately without rebuilding. Just restart the affected service:

```sh
docker compose --env-file docker/.env --profile all restart   # restart all
docker compose --env-file docker/.env restart api              # restart one
```

Rebuild after changing a Dockerfile. If `package.json` or `Makefile.PL` changes,
reinstall the deps inside the affected container; an existing dependency volume
may survive an image rebuild.

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
make test         # run v3 API + library tests (requires make up)
make test-api     # run v3 API tests only
make test-server  # run v3 server tests only (requires make up-ui)
make test-libs    # run library tests (no running services needed)
make test-v2       # run all v2 unit and extended tests through SOAP
make test-v2-rest  # run the supported v2 extended tests through REST
make test-v2-xt    # run all v2 extended tests through SOAP
```

## Contributing from a fork

The manifest only knows about upstream -- `origin` in every repo points at
`NicTool/*` and is likely read-only. Personal forks live in each clone's
git config rather than in `mani.yaml`. This shortcut can create all of the forks
and wire them up for you:

```sh
make fork                  # forks under your gh login
make fork OWNER=my-org     # or under an org you control
make fork PART=dns-resource-record  # fork and wire just one manifest part
```

This forks any repo you haven't forked yet (via `gh`), adds a `fork` remote to
every clone, and fast-forwards existing forks from upstream. Re-run it any
time -- coming back after days away, it re-syncs your forks and repairs
missing remotes, reusing whatever owner the remotes already point at.
When `PART=<name>` is supplied, only that manifest part is created, synced,
or wired; combine it with `OWNER=my-org` when needed. The direct CLI equivalent
is `./nt.py fork --part dns-resource-record`.

Then branch in the member repo, push to `fork`, and open a PR against
upstream:

```sh
git -C api checkout -b my-change
git -C api push -u fork my-change
gh pr create --repo NicTool/api --head <owner>:my-change --base main
```

Done with forks? `./nt.py fork --remove` drops all the remotes, while
`./nt.py fork --remove --part dns-resource-record` drops only that part's
remote. Your forks on GitHub stay put.

## Project structure

```
metarepo/
  docker/
    .env.example          # reference for environment variables
    .env                  # generated credentials (gitignored)
    generate-env.sh       # creates .env with random passwords
  docker-compose.yml      # all services, all profiles
  Makefile                # task runner
  mani.yaml               # manifest: repos and pins
  nt.py                   # workspace tool: sync / status / update / fork
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

Member repos are gitignored — this workspace records *intent* through the pins
in `mani.yaml`, never member-repo content.

## Issues and feedback

There really shouldn't be any component-specific issues listed here. Check the
open issues and PRs for the relevant sub-project instead.

This metarepo is a work in progress; contributions and feedback would be quite
welcome.
