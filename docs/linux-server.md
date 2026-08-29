# NicTool v2 + v3 on a linux server

This is the "someone else follows it cold" guide. You end up with a plain
linux box running docker, the whole v2 stack, and the v3 api beside it
against the same db. If a step doesn't do what it says, that's a bug in this
page or in the code. Write down exactly what you typed and what came back,
and send it over.

Sections 1 to 4 were walked on Debian 12, Rocky 8, Rocky 9 and arch, and
every command did what it says on each. The suites passed at the time. The
trains in `mani.yaml` move, so treat that part as history rather than a
promise.

## 1. Prerequisites

Everything here runs as root. You need:

- docker, with the compose plugin
- git, make, curl, and openssl — `make env` uses openssl for the passwords
- `mani`, which clones the member repos
- `uv`, which runs the workspace tool `nt.py`

No `gh`. Nothing here needs the GitHub API: `make train` fetches PR heads
with plain `git fetch`. It does ask `gh` whether a PR has already closed or
merged, so it can leave that one out. Without gh the state reads `unknown`
and the PR goes in anyway.

### Packages

**Debian / Ubuntu**

```sh
curl -fsSL https://get.docker.com | sh
apt-get install -y git make curl openssl
```

**arch**

```sh
pacman -S docker docker-compose git make curl openssl uv
systemctl enable --now docker
```

**Rocky / Alma**

The minimal image has no `tar`, and `get.docker.com` is unreliable here, so
docker comes from its own repo.

```sh
dnf install -y tar git make curl openssl 'dnf-command(config-manager)'
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
```

### mani and uv

`mani` isn't packaged, so fetch it everywhere. `uv` came with the pacman line
above, so skip its command on arch.

```sh
# mani: https://manicli.com/installation. Its install.sh asks a question on
# the terminal, so over ssh or in a script fetch the release tarball instead.
# The asset name carries the version and the architecture: 0.32.1 was current
# when this was written, and an arm box wants linux_arm64.
curl -sL https://github.com/alajmo/mani/releases/download/v0.32.1/mani_0.32.1_linux_amd64.tar.gz \
  | tar xz -C /usr/local/bin mani
# uv: https://docs.astral.sh/uv/
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell. All four must answer: `docker compose version` (the
plugin, not the old python `docker-compose`), `git --version`,
`mani --version`, and `uv --version`.

### IPv6-only resolvers

Some cloud images give the VM nameservers on IPv6 only. `docker run` copes.
`docker build` doesn't: every image build fails with `Temporary failure
resolving 'deb.debian.org'`. Look at `/etc/resolv.conf`. If there's no IPv4
nameserver, give docker one before you build anything.

A fresh box has no `/etc/docker/daemon.json` yet. If yours does have one, add
the `dns` key to it by hand instead of running this:

```sh
test -e /etc/docker/daemon.json || printf '{ "dns": ["1.1.1.1", "9.9.9.9"] }\n' > /etc/docker/daemon.json
systemctl restart docker
```

### git identity

`make train` writes merge commits, so git needs to know who you are, even on
a throw-away box:

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

If the train stops with a "CONFLICT" that lists no files, check the identity
first (yes, that error is lying to you).

## 2. Install

```sh
git clone https://github.com/NicTool/metarepo.git
cd metarepo
make init      # clones every member repo at its manifest pin
make train     # assembles the PR branches mani.yaml declares (see below)
make env       # writes docker/.env with random passwords
chmod 600 docker/.env
make up-legacy # db + v3 api + v2
```

`make env` writes that file world-readable, and it holds the db passwords.

`make init` is quick.

`make train` builds a `train/<branch>` in each member repo that declares one
in `mani.yaml`, then checks it out. `make status` shows what it did. Read
`mani.yaml` to see which PRs are in flight while you're reading this. If it
declares no trains, skip the step — with nothing to assemble, it errors.

`make up-legacy` builds two images the first time. Budget a few minutes and
a lot of scrolling. It's done when this shows every
container `healthy`:

```sh
docker compose --env-file docker/.env --profile all ps
```

`make up-legacy` stops any container already holding one of its ports, on
the assumption it's an old copy of this stack. If you'd rather keep that
container, change the `*_PORT` values in `docker/.env` first.

**Why not `make up-all`?** It also builds the v3 web ui from the manifest's
`server` checkout. If that checkout has no `server/docker/Dockerfile`, both
`make up-all` and `make up-ui` die with `server/docker: no such file or
directory`. The v3 api and the v2 gui are the stack under test anyway.

## 3. Look at it

Replace `SERVER` with the box's address, and any port you changed in
`docker/.env`. The containers bind on every interface, so another machine on
the LAN can browse straight to them, firewall permitting. Nothing here is
TLS-terminated except the self-signed v2 port, so keep it on a private
network.

| What | URL | You should see |
|---|---|---|
| v3 api | `http://SERVER:3000/documentation` | a swagger page listing the routes |
| v3 web ui | `http://SERVER:8080` | nothing — `make up-legacy` doesn't start it, see above |
| v2 (classic) | `http://SERVER:8082` | the classic NicTool login page |
| v2 over TLS | `https://SERVER:8443` | same, self-signed certificate |
| db | `SERVER:3307` | any mysql client, creds from `docker/.env` |

**Logging in.** A fresh install has one usable account: the test user the v2
container creates on first start. The username is `nictest@test_group`. The
password is on the `password =>` line of `NicTool/server/t/test.cfg` on the
host. It works on the v2 login page, and against the v3 api (`POST /session`
with `{"username":"nictest@test_group","password":"..."}`).

That password changes every time the v2 container starts, because the
entrypoint rewrites `test.cfg`. Re-read the file after a restart.

As things stand there's no root admin. v2's installer would create one from
`ROOT_USER_EMAIL` and `ROOT_USER_PASSWORD` in `docker/.env`, but in this
stack the db is initialised from v3's `api/sql` first. The v2 installer then
sees a populated db and never runs. That's a known gap, so report how much it
hurt. An upgraded v2 database keeps its real root user, see section 5.

**Watching the bridge.** The v2 GUI you're looking at talks to the v3 api,
not to its own SOAP server. To watch that happen:

```sh
docker compose --env-file docker/.env logs -f api
```

Then click around in v2. Its api calls show up in that log.

Things worth trying, in order:

1. Log in to v2.
2. Make a zone, and add a few records to it.
3. Log in to the v3 api, then `GET http://SERVER:3000/zone` with that session
   token and find the same zone.

## 4. Prove it works

```sh
make test           # v3 api, plus the dns libraries
make test-v2-rest   # the part of v2's extended suite the bridge supports, through v3
make test-v2-xt     # v2's whole extended suite against its own SOAP server
```

`make test` runs the api suite in the api container, and each dns library in
its own node container. Each command takes a few minutes, and the SOAP suite
is the slow one.

A clean run exits zero with nothing failed, skipped or cancelled — `make`
counts a skip as a failure on purpose. A red one can come from the trains
`mani.yaml` is carrying rather than from your box, so save the last screen
and send `make status` with it.

## 5. Upgrading an existing NicTool v2

> Walked with two databases at `db_version` 2.41: a copy of a real
> production one, and an anonymised corpus built from it. The restore,
> `upgrade.pl` and the v3 sql upgrades all went through clean. The real root
> user logged into v3 and saw every live zone, and the v2-over-v3 suite
> passed against that data.
>
> No other `db_version` has been walked. If yours is older, that's the most
> useful run anybody can make.

The plan:

1. Take a dump of the existing v2 db.
2. Load it into this stack's db instead of the empty one.
3. Run v2's own upgrade script to bring the schema to the current v2 level.
4. Let v3 add what it needs on top.

Nothing touches the old server.

### 5.1 On the old server

```sh
mysqldump -u root -p --single-transaction --routines nictool > nictool-$(date +%F).sql
```

`-p` prompts for the account's password. Use one that can dump the tables,
triggers and routines.

Copy that file to the new box. Note the old NicTool version, and the
`db_version` it reports (`SELECT option_value FROM nt_options WHERE
option_name='db_version'`). Both go in your report.

### 5.2 On the new box: db only, then restore

Do the install above up to and including `make env`, but instead of
`make up-legacy`:

```sh
docker compose --env-file docker/.env up -d --wait db
. docker/.env
docker compose --env-file docker/.env exec -T db \
  mariadb -uroot -p"$DB_ROOT_PASSWORD" \
  -e "DROP DATABASE nictool; CREATE DATABASE nictool;"
docker compose --env-file docker/.env exec -T db \
  mariadb -uroot -p"$DB_ROOT_PASSWORD" nictool < nictool-YYYY-MM-DD.sql
```

That first `up` initialized an empty v3 schema. The drop throws it away, so
the dump lands on a clean database. The `nictool` db user from `docker/.env`
already has rights on it.

### 5.3 Bring v2 up on the restored data

```sh
make up-legacy
```

The v2 container reads `db_version`, sees one, and leaves your schema alone.
It still wants its test fixtures: a `test_group` at group id 2, and a
`nictest` user at user id 2 with every permission in that group. It looks for
the group by id and the user by name. So if your data already holds a user
called `nictest`, the setup resets that account's password instead of making
its own.

If the container exits with `Duplicate entry '2' for key 'PRIMARY'`, its
setup script assumed user id 2 was free, which on a real database it isn't.
Give it a `nictest` to find instead:

```sh
. docker/.env
docker compose --env-file docker/.env exec -T db \
  mariadb -uroot -p"$DB_ROOT_PASSWORD" nictool -e "INSERT INTO nt_user
  (nt_group_id, first_name, last_name, username, password, pass_salt, email, deleted)
  VALUES (1, 'Test', 'User', 'nictest', 'x', '', 'nictest@example.com', 0);"
```

Then run `make up-legacy` again. The setup finds that user, resets only its
password, and the container comes up. That account is there so the container
starts, and nothing more. The test suites want it in `test_group`, which this
workaround doesn't create, and they aren't meant to run against your data
anyway.

Either way you now have a test account in your database. When you're done,
look at what the setup left behind:

```sh
docker compose --env-file docker/.env exec -T db \
  mariadb -uroot -p"$DB_ROOT_PASSWORD" nictool -e "
  SELECT nt_user_id, nt_group_id, username FROM nt_user WHERE username='nictest';
  SELECT nt_group_id, name FROM nt_group WHERE name='test_group' AND parent_group_id=1;"
```

Unless someone made one, your data has no `nictest` and no `test_group` under
the root group. If the rows above are the ones the setup created, delete
them:

```sh
docker compose --env-file docker/.env exec -T db \
  mariadb -uroot -p"$DB_ROOT_PASSWORD" nictool -e "
  DELETE FROM nt_user WHERE username='nictest' AND (nt_group_id=1 OR nt_group_id IN
    (SELECT nt_group_id FROM nt_group WHERE name='test_group' AND parent_group_id=1));
  DELETE FROM nt_perm WHERE nt_user_id IS NULL AND nt_group_id IN
    (SELECT nt_group_id FROM nt_group WHERE name='test_group' AND parent_group_id=1);
  DELETE FROM nt_group_log WHERE nt_group_id IN
    (SELECT nt_group_id FROM nt_group WHERE name='test_group' AND parent_group_id=1);
  DELETE FROM nt_group_subgroups WHERE nt_subgroup_id IN
    (SELECT nt_group_id FROM nt_group WHERE name='test_group' AND parent_group_id=1);
  DELETE FROM nt_group WHERE name='test_group' AND parent_group_id=1;"
```

Now run v2's upgrade script inside the container. It checks every schema
change it knows about against what's actually in the database, applies the
ones that are missing, and repairs a few known bad states from old releases.
It describes each one before it acts.

```sh
. docker/.env
docker compose --env-file docker/.env --profile legacy exec -T nictool-legacy bash -c \
  "cd /usr/local/nictool/server/sql && perl upgrade.pl \
     --dsn 'DBI:mysql:database=nictool;host=db;port=3306' \
     --user root --pass '$DB_ROOT_PASSWORD'"
```

Read what it prints. If it stops on orphan rows, that's exactly the kind of
thing to report. `--prune` exists for that case, but it deletes rows, so
don't use it without a dump in hand.

Log in to v2 at `http://SERVER:8082` with an account from the old system.
Make sure your zones are there before going further.

### 5.4 Let v3 in

v3 keeps its schema changes for an existing v2 database in
`api/sql/upgrade/`, numbered, meant to run in order:

| file | what it does | re-runnable? |
|---|---|---|
| `01_drop_obsolete_summary_tables.sql` | drops v2 summary tables v3 doesn't use | yes |
| `02_drop_obsolete_qlog_tables.sql` | drops v2 query-log tables | yes |
| `03_nameserver_runtime_columns.sql` | adds v3's nameserver columns | no (a duplicate-column error the second time is fine) |
| `04_clear_orphan_rows.sql` | fixes zero dates and **deletes orphan rows** so constraints can be added | yes |
| `05_enable_foreign_keys.sql` | adds the foreign keys new installs already have | yes |

`01`, `02` and `04` are destructive. The first two drop obsolete tables.
`04` rewrites zero datetimes and deletes orphan rows. Read every header
before you start. Then:

```sh
. docker/.env
for f in api/sql/upgrade/[0-9][0-9]_*.sql; do
  echo "==> $f"
  docker compose --env-file docker/.env exec -T db \
    mariadb -uroot -p"$DB_ROOT_PASSWORD" nictool < "$f"
done
```

An errno 150 from `05` means orphan rows remain. An errno 1292 means a zero
datetime survived `04`. Both are report material.

### 5.5 Everything up

```sh
make up-legacy
```

Log in to the v3 api (`POST http://SERVER:3000/session`) with the same old
account, or as `root@NicTool` for the root user. v3 verifies v2's password
hashes, so the old passwords still work.

Don't run section 4 against data you care about. `make test` writes and
deletes fixtures at fixed ids in the 4000s and 9000s, and the v2 suites want
the `nictest@test_group` account you just deleted. Do that pass on a
disposable copy.

## 6. What to send back

For each snag, send the command, its full output rather than a summary, and
what you expected instead. Redact the passwords first — `upgrade.pl` prints
the one you hand it. Add `make status` and `docker compose --env-file
docker/.env --profile all ps` as they were at that moment. Bugs in the stack
become issues in the member repo. Bugs in this page get fixed here.

## Cleaning up

```sh
make down    # stop, keep the data
make clean   # stop and delete the db volume; the next up starts empty
```
