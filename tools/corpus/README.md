<!-- Copyright (c) 2026, The NicTool Contributors -->

# NicTool corpus tools

Turn a NicTool db dump into anonymized test data, then use it to test DNS
libraries and db upgrades. The tools support NicTool 2.34 and 2.41.

Run these commands from the metarepo root. You'll need python 3 and a DB dump
client. The application tests also need docker and the member repositories
set up as described in the [workspace README](../../README.md).

## Extract and anonymize a dump

Keep the raw dump and mapping secret in the git-ignored `local/` directory:

```sh
umask 077
set -o pipefail
mkdir -p local/corpus tools/corpus/corpora
mysqldump -u root -p --single-transaction --skip-comments \
  --skip-routines --skip-triggers --no-tablespaces nictool \
  | gzip > local/corpus/source.sql.gz
openssl rand -base64 48 > local/corpus/secret

python3 tools/corpus/anonymize.py \
  local/corpus/source.sql.gz tools/corpus/corpora/nictool-2.41.sql.gz \
  --secret-file local/corpus/secret --db-version 2.41 \
  --contributor anonymous --source-date "$(date +%F)"
```

This writes an anonymized `.sql.gz` and a matching `.manifest.json` with
checksums and row counts. Keep them together. Existing outputs are left alone
unless you pass `--force`.

Names, addresses, free text and secrets are replaced while relationships
between rows are retained. Session rows are removed. User passwords become
`nictool-corpus`, so use the result only in a test environment.

For a 2.34 dump, use `--db-version 2.34` and a matching output filename.
The tool stops on unsupported schemas or SQL. `--retention-profile
historical-patterns` keeps representative history rows to make a smaller
corpus. The default keeps all history except sessions.

## Check it

Compare the result with the private source before sharing it:

```sh
python3 tools/corpus/audit.py \
  tools/corpus/corpora/nictool-2.41.sql.gz \
  tools/corpus/corpora/nictool-2.41.manifest.json \
  --source local/corpus/source.sql.gz --require-source \
  --output tools/corpus/corpora/nictool-2.41.audit.json
```

To check specific names, domains or tokens too, put one per line in a private
mode-0600 file and pass `--indicators FILE --require-indicators`.
Reports contain counts and field categories rather than matched private values.
A failed audit needs investigation before the corpus is shared.

## Use it

The matching manifest must sit beside the dump:

```sh
make test-corpus-dns CORPUS=tools/corpus/corpora/nictool-2.41.sql.gz
make test-corpus-integration CORPUS=tools/corpus/corpora/nictool-2.41.sql.gz
```

The first command checks records with the workspace DNS libraries. The second
restores the dump in an isolated docker project, checks row counts, runs db
upgrades and application tests, then removes that project's containers and data.

Add `SOURCE=local/corpus/source.sql.gz` to either command to compare with the
private source. This helps distinguish an existing data problem from one
introduced by anonymization.

To keep the integration environment for inspection, run the script directly:

```sh
tools/corpus/scripts/integration-test.sh --keep \
  tools/corpus/corpora/nictool-2.41.sql.gz "$PWD"
```

Failed, cancelled, skipped or unavailable suites prevent a passing integration
result. `make test-corpus` tests the corpus tools
themselves with synthetic data.

## Share it

After the source audit and human review, upload the anonymized `.sql.gz` and
its `.manifest.json` as assets on a versioned metarepo release. Include the
reviewed audit and test reports there if they're useful. Generated dumps,
manifests and reports belong with the release assets, not in the source tree.

Never upload the raw dump, mapping secret or indicator file. Review attribution
in the manifest too. `--contributor` accepts a public alias, not an email address.

Recipients download the dump and matching manifest from the same release.
They can check the download without access to the private source:

```sh
python3 tools/corpus/audit.py \
  tools/corpus/corpora/nictool-2.41.sql.gz \
  tools/corpus/corpora/nictool-2.41.manifest.json
```

Then they can run the same `make test-corpus-dns` and
`make test-corpus-integration` commands above.
