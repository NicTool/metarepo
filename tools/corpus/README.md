<!-- Copyright (c) 2026, The NicTool Contributors -->

# NicTool corpus

Real database shapes make good upgrade tests. They don't make safe fixtures
until every identifying value, secret and stray bit of free text has been
accounted for.

This metarepo tooling is licensed under the BSD 3-Clause License. See `LICENSE`.
Run the Python commands below from `tools/corpus`.

## Current corpus status

Corpus SQL files are local, git-ignored build outputs. Manifests belong in git.
Neither corpus has been approved for publication. Aggregate privacy and DNS
reports are in `corpora/reports/`.

The 2.41 source is a controlled table-only dump made on 2026-09-06. The 2.34
source was a backup whose source file was last modified on 2024-07-31.
Its live rows are retained, while bulk
history is reduced by the declared `historical-patterns` policy. Source
checksums are in the manifests; the raw dumps and secret are not retained in
this repository.

The separate prototype repository contains unsafe corpus history. None of
that history is imported here. Keep it private.

Use metarepo release assets for reviewed `.sql.gz` files, identified by an
explicit release tag and the checked-in manifest checksum. Do not commit SQL,
use an unpinned `latest` download, or upload private source and audit inputs.
No corpus release exists yet.

| file | db version | zone rows | record rows | retained history rows | publication status |
|---|---:|---:|---:|---:|---|
| `nictool-2024-07-31-v2.34-abraham-ingersoll.sql.gz` | 2.34 | 1,706 | 13,648 | 2,519 | awaiting review |
| `nictool-2026-09-06-v2.41-abraham-ingersoll.sql.gz` | 2.41 | 278 | 1,579 | 88,841 | awaiting review |

## Input contract

`anonymize.py` accepts the complete NicTool 2.34 and 2.41 table schemas declared
in `schema.py`. Select the source schema with `--db-version`; 2.41 is the
default. Both ordinary mysqldump rows and extended multi-tuple `INSERT INTO
\`table\` VALUES` statements are parsed as complete SQL statements. Strings may
contain doubled quotes, literal newlines and the mysqldump backslash escapes.
Unquoted values are limited to `NULL` and numeric values in known numeric
columns. Hex, bit and expression values are rejected so they cannot bypass a
string field's mapping.

The source must be mode 0600. Produce it without routines, triggers, database
creation statements or tablespace metadata:

```sh
umask 077
mysqldump -u root -p --single-transaction --skip-comments \
  --skip-routines --skip-triggers --no-tablespaces nictool | gzip > nictool-2.41.raw.sql.gz
openssl rand -base64 48 > .secret
chmod 600 .secret nictool-2.41.raw.sql.gz
./anonymize.py nictool-2.41.raw.sql.gz corpora/nictool-2.41-alias.sql.gz \
  --secret-file .secret --contributor alias \
  --source-alias private-production --source-date 2026-08-30 \
  --db-version 2.41 --static-profile 2.41 --retention-profile full
```

The `2.34-2024-07-31` static profile describes the 2024-07-31 source's exact mix
of lookup rows from public 2.34 and 2.41 NicTool releases. It is valid only with
the 2.34 schema. It does not learn or allowlist private source text.

`--retention-profile full` retains every non-session row. The optional
`historical-patterns` profile retains all live, static and relationship rows.
For each history table it keeps the first and last source row of every
structural shape. Shapes distinguish record and action types, numeric classes,
text lengths, Unicode and control characters, address classes, hostnames,
emails, DKIM, verification values and opaque tokens. The manifest records the
method and every removed row by table. The private source audit independently
recomputes the selection.

`CORPUS_SECRET` is also accepted. A secret on the command line is not. It must
contain at least 32 bytes, and a secret file must not be group or world
accessible. The contributor is a lower-case alias made from letters, digits,
underscores and hyphens, up to 40 characters. Use only an attribution approved
for publication, never an email address. Keep the source and secret out of git. Delete temporary source
copies when the run and audit are finished.

Unknown tables, missing or extra columns, explicit-column inserts, unsupported
raw expressions, routines, triggers, `DEFINER`, unsafe DDL metadata and any
other SQL statement stop the run. Existing output files are replaced only with
`--force`, and parse or mapping errors leave them untouched.

## Safety and data-shape policy

DNS labels use a shared mapping across live rows, history and DNS targets.
Generated DNS labels and free-text words begin with a
lower-case `q`; opaque tokens and key material begin with upper-case `Q`. These
markers let the audit distinguish generated values without knowing the secret.
Before mapping, the tool reserves every source value and word so a generated
name, username, label or token cannot collide with different source material.

Wildcards, the protocol labels in `KEEP_UNDERSCORE_LABELS`, and the service
labels in `KEEP_LABELS` remain recognizable. Other labels, including opaque
underscore-prefixed and long hex labels, are replaced. Generated labels have
at least eight characters and cannot collide with earlier generated labels.
The mapped original TLD is retained before the synthetic `.test` or `.example`
suffix so different source TLDs cannot merge zones.
CNAME, MX, NS, PTR, SRV and DNAME targets use the same label mapping as zones
and record names. An in-corpus target therefore still points at its mapped
name. An external target is still changed deterministically, but no claim is
made that it resolves inside the corpus.

Addresses remain valid and keep their class:

| source class | output class |
|---|---|
| public/global IPv4 | `198.18.0.0/15` |
| `10/8`, `172.16/12`, `192.168/16` | the same respective RFC1918 block |
| IPv4 link-local, loopback and carrier-grade | the same class |
| IPv4 multicast | `233.252.0.0/24` |
| global IPv6 | `2001:db8::/32` |
| IPv6 ULA, link-local and site-local | the same class |
| IPv6 multicast | the same flags and scope |

`0.0.0.0`, `255.255.255.255`, `127.0.0.1`, `::` and `::1` are explicit static
exceptions because there is no identifying host component to replace. Address
fragments in typed address fields, free text and address-leading hostnames use
the same prefix mapping as complete addresses. Non-empty malformed values in
typed IPv4 or IPv6 fields stop the run. Full reverse names use the complete
address mapping too.

TXT and SPF values keep allowlisted protocol words while domains, addresses,
Unicode text, short text, verification values and opaque tokens change. DKIM
matching is case-insensitive and covers short, quoted and whitespace-split
`p=` material. Generated key and token values cannot begin with the base64
prefix used by DER sequences.

Every live user password becomes `nictool-corpus` in the
PBKDF2-SHA512/5000, 32-byte format supported by NicTool 2.34 and 2.41.
Passwords and salts in history are blank. Session rows are omitted. Static rows
remain unchanged only when the complete row matches the selected
`resource_record_type` or `nt_nameserver_export_type` allowlist in `schema.py`.
Enum-valued action and object fields, plus quoted DDL enum and default values,
remain only through the table and column allowlists there. Mapped free text
that would exceed its declared `CHAR` or `VARCHAR` length is replaced with a
shorter synthetic word and counted in the manifest. A mapped relational name
that would not fit stops the run.

## Manifest and audit

Each run writes a deterministic gzip file and a JSON manifest. The manifest
records the tool version, source alias and date, source and corpus checksums,
compressed and plain SQL sizes, source and output row counts, dropped session
counts, history-retention counts, password format, mapping counts, the schema
and static profiles, the static allowlist, the address and DNS target policies,
and the reproducibility contract. The source hash covers decompressed SQL
bytes; the raw source itself is never retained.

Generic checks are exhaustive over parsed rows, not samples:

```sh
./audit.py corpora/nictool-2.41-alias.sql.gz \
  corpora/nictool-2.41-alias.manifest.json
```

Publication review requires the private mode-0600 raw source. The audit checks
its manifest checksum and row totals, compares mapped fields row by row, and
builds private category indexes for source names, domains, emails, addresses,
key material and tokens. It reports only counts and field classes:

```sh
./audit.py corpora/nictool-2.41-alias.sql.gz \
  corpora/nictool-2.41-alias.manifest.json \
  --source nictool-2.41.raw.sql.gz --require-source \
  --output nictool-2.41.private-audit.json
```

A separate mode-0600 file with one literal known name, domain, email, network,
address or token per line supplements that source comparison:

```sh
chmod 600 known-indicators.txt
./audit.py corpora/nictool-2.41-alias.sql.gz \
  corpora/nictool-2.41-alias.manifest.json \
  --source nictool-2.41.raw.sql.gz --require-source \
  --indicators known-indicators.txt --require-indicators \
  --output nictool-2.41.private-audit.json
```

The report contains counts and field classes, never matched values. It checks
manifest checksums and row totals, sessions, password shape, emails, every
valid IPv4 and IPv6 candidate, address fragments in free text, opaque DNS
labels and TXT tokens, DKIM material, complete DER sequences, dump headers,
routines, triggers and `DEFINER` clauses. Indicator matching uses normalized,
case-insensitive SQL text, decoded string values and the manifest. A passing
generic audit without the private source comparison is not enough to propose
publication. Email, IPv4, IPv6, address-fragment, hostname, TXT, key and token
counts are classified by table, column and output policy in the report.

## Restore, upgrade and test

From the metarepo root:

```sh
make test-corpus
make test-corpus-dns CORPUS=tools/corpus/corpora/nictool-2.41-alias.sql.gz
make test-corpus-integration CORPUS=tools/corpus/corpora/nictool-2.41-alias.sql.gz
```

`test-corpus-dns` runs a privacy audit, then feeds every live and retained
history record through `@nictool/dns-resource-record`. It uses that library's
NicTool mappings, constructors and BIND import/export, plus `@nictool/dns-zone`
for current, non-deleted zones. History is never combined into a current zone.
The source checkouts come from the workspace, not freshly resolved npm versions.

Pass `SOURCE=/private/path/source.sql` to compare each retained source record
with its mapped counterpart. A source pass followed by an output failure is a
regression. `both-failed` means the same check stage failed on both sides, not
proof of an identical cause. `changed-to-valid` also needs review because
anonymization may have removed a useful defect. Without a source, failures are
unclassified. Missing library support is a finding, never a pass.

Private paired inputs are mode 0600 under git-ignored `local/`, mounted read-only
in a network-disabled container, and removed when the command exits. Reports
contain counts and stages, never source values or exception messages.
Any DNS finding returns exit 1; an unreadable or invalid input returns exit 2.

Use `NICTOOL_DNS_RESOURCE_RECORD_SOURCE` and `NICTOOL_DNS_ZONE_SOURCE` for
isolated member worktrees. Once an upstream PR exists, use the existing
`mani.yaml` train mechanism. Don't put local worktree paths into the manifest.

The new escape regression fails against the workspace's released record
library. The fixes are committed locally, not yet upstream. For this checkout:

```sh
export NICTOOL_DNS_RESOURCE_RECORD_SOURCE="$PWD/local/worktrees/corpus-dns-resource-record"
export NICTOOL_DNS_ZONE_SOURCE="$PWD/local/worktrees/corpus-dns-zone"
make test-corpus
```

Those paths are local review worktrees, not portable dependency pins.
A fresh checkout must obtain the reviewed library commits before that
regression can pass.

The integration runner uses a new compose project and volume for each run. It
drops only that project's `nictool_corpus` database, imports by streaming,
checks all manifest row counts, runs the v2 and v3 upgrades, then runs the v3
API and library suites plus the v2 unit, SOAP and supported REST-bridge suites.
It removes the isolated project unless `--keep` is passed.

```sh
scripts/integration-test.sh --source nictool-2.41.raw.sql.gz \
  --indicators known-indicators.txt --allow-test-failures \
  corpora/nictool-2.41-alias.sql.gz \
  /path/to/nictool-metarepo
```

Use the matching raw source for the historical corpus:

```sh
scripts/integration-test.sh --source nictool-2.34-2024-07-31.raw.sql.gz \
  --indicators known-indicators.txt --allow-test-failures \
  corpora/nictool-2.34-2024-07-31-alias.sql.gz \
  /path/to/nictool-metarepo
```

By default any application suite failure makes the runner fail. When the
corpus is being used to find application defects, `--allow-test-failures`
keeps those failures visible and returns success only after the audit, import,
row-count checks and upgrade commands have completed. It never labels a failed,
cancelled, skipped or unavailable suite as passing.

For diagnosis only, an external failed-audit corpus can be loaded with
`--allow-unaudited`. That option is not part of publication review and does not
make a failed audit acceptable.

The fresh runs on both dated corpora restored every manifest row count and
completed the upgrade commands. SOAP passed 6,085 tests and REST passed 5,796
on each. API, library and v2 unit findings remain. The API run reported five
cancelled tests with an unknown native nameserver type. The v2 server unit run
failed two import checks. Optional library checks were skipped, not passed.

Run the fast suite while developing:

```sh
python3 -B -m unittest discover -s tests -v
```

The matching static checks are `uvx ruff
check .`, `python3 -m py_compile anonymize.py audit.py schema.py tests/*.py`,
`bash -n scripts/*.sh` and `git diff --check`.
