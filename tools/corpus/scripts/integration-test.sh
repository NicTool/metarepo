#!/usr/bin/env bash
# Copyright (c) 2026, The NicTool Contributors

set -euo pipefail
umask 077

usage() {
    echo "usage: $0 [--allow-test-failures] [--allow-unaudited] [--indicators FILE] [--keep] [--source FILE] CORPUS WORKSPACE" >&2
    exit 2
}

allow_unaudited=false
allow_test_failures=false
indicator_file=
keep=false
source_file=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-test-failures) allow_test_failures=true; shift ;;
        --allow-unaudited) allow_unaudited=true; shift ;;
        --indicators) [[ $# -ge 2 ]] || usage; indicator_file=$2; shift 2 ;;
        --keep) keep=true; shift ;;
        --source) [[ $# -ge 2 ]] || usage; source_file=$2; shift 2 ;;
        --) shift; break ;;
        -*) usage ;;
        *) break ;;
    esac
done
[[ $# -eq 2 ]] || usage

corpus=$1
workspace=$2
script_dir=$(cd "$(dirname "$0")/.." && pwd)
corpus=$(cd "$(dirname "$corpus")" && pwd)/$(basename "$corpus")
workspace=$(cd "$workspace" && pwd)
manifest=${corpus%.gz}
manifest=${manifest%.sql}.manifest.json
api_source=${NICTOOL_API_SOURCE:-$workspace/api}
legacy_source=${NICTOOL_LEGACY_SOURCE:-$workspace/NicTool}
validate_source=${NICTOOL_VALIDATE_SOURCE:-$workspace/libs/validate}
record_source=${NICTOOL_DNS_RESOURCE_RECORD_SOURCE:-$workspace/libs/dns-resource-record}

[[ -f "$corpus" && -f "$manifest" ]] || usage
[[ -f "$workspace/docker-compose.yml" ]] || usage
[[ -f "$api_source/package.json" && -f "$legacy_source/server/sql/upgrade.pl" && -f "$validate_source/package.json" ]] || usage

audit_args=("$script_dir/audit.py" "$corpus" "$manifest")
if [[ -n "$indicator_file" ]]; then
    audit_args+=(--indicators "$indicator_file" --require-indicators)
fi
if [[ -n "$source_file" ]]; then
    audit_args+=(--source "$source_file" --require-source)
fi
if ! python3 -B "${audit_args[@]}"; then
    if [[ "$allow_unaudited" != true ]]; then
        echo "audit failed; --allow-unaudited is for local diagnosis only" >&2
        exit 1
    fi
    echo "continuing with a failed audit for local diagnosis" >&2
fi

if [[ ! -f "$workspace/docker/.env" ]]; then
    "$workspace/docker/generate-env.sh"
fi
set -a
. "$workspace/docker/.env"
set +a

export COMPOSE_PROJECT_NAME="nictool-corpus-$$"
export COMPOSE_FILE="$workspace/docker-compose.yml:$script_dir/docker-compose.corpus.yml"
export NICTOOL_DB_NAME=nictool_corpus
export DB_PORT=0 API_PORT=0 SERVER_PORT=0 LEGACY_HTTP_PORT=0 LEGACY_HTTPS_PORT=0
export NICTOOL_API_SOURCE="$api_source"
export NICTOOL_LEGACY_SOURCE="$legacy_source"
export NICTOOL_VALIDATE_SOURCE="$validate_source"
export NICTOOL_DNS_RESOURCE_RECORD_SOURCE="$record_source"

compose=(docker compose --env-file "$workspace/docker/.env")
suite_log_dir=$(mktemp -d "${TMPDIR:-/tmp}/nictool-corpus-tests.XXXXXX")
chmod 700 "$suite_log_dir"
cleanup() {
    if [[ -n "$suite_log_dir" && -d "$suite_log_dir" ]]; then
        rm -rf -- "$suite_log_dir"
    fi
    if [[ "$keep" == true ]]; then
        echo "kept compose project $COMPOSE_PROJECT_NAME"
    else
        "${compose[@]}" --profile all --profile test down -v --remove-orphans
    fi
}
trap cleanup EXIT

"${compose[@]}" up -d --wait db
"${compose[@]}" exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot -e "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\`;"'
import_log="$suite_log_dir/import.log"
if [[ "$corpus" == *.gz ]]; then
    if ! gzip -dc "$corpus" | "${compose[@]}" exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot "$MYSQL_DATABASE"' >"$import_log" 2>&1; then
        echo "corpus import failed; SQL text was written only to the private temporary log" >&2
        exit 1
    fi
else
    if ! "${compose[@]}" exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot "$MYSQL_DATABASE"' < "$corpus" >"$import_log" 2>&1; then
        echo "corpus import failed; SQL text was written only to the private temporary log" >&2
        exit 1
    fi
fi

while IFS=$'\t' read -r table expected; do
    [[ "$table" =~ ^[a-z0-9_]+$ ]]
    actual=$("${compose[@]}" exec -T db sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mariadb -N -uroot \"\$MYSQL_DATABASE\" -e 'SELECT COUNT(*) FROM \`$table\`'" </dev/null | tr -d '\r')
    printf 'post-import rows %-32s expected=%s actual=%s\n' "$table" "$expected" "$actual"
    [[ "$actual" == "$expected" ]]
done < <(python3 -B -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf8")); print("\n".join(f"{table}\t{count}" for table,count in sorted(data["rows"].items())))' "$manifest")

for table in nt_user_session nt_user_session_log; do
    actual=$("${compose[@]}" exec -T db sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mariadb -N -uroot \"\$MYSQL_DATABASE\" -e 'SELECT COUNT(*) FROM \`$table\`'" </dev/null | tr -d '\r')
    printf 'post-import rows %-32s expected=0 actual=%s\n' "$table" "$actual"
    [[ "$actual" == 0 ]]
done

"${compose[@]}" up --build -d --wait nictool-legacy
printf '\n\n' | "${compose[@]}" exec -T nictool-legacy bash -c \
    'cd /usr/local/nictool/server/sql && perl upgrade.pl --dsn "DBI:mysql:database=$NICTOOL_DB_NAME;host=db;port=3306" --user root --pass "$DB_ROOT_PASSWORD"' \
    2>&1 | DB_ROOT_PASSWORD="$DB_ROOT_PASSWORD" perl -pe 'BEGIN { $secret = $ENV{"DB_ROOT_PASSWORD"} } s/\Q$secret\E/[redacted]/g'

for upgrade in "$api_source"/sql/upgrade/[0-9][0-9]_*.sql; do
    printf 'applying %s\n' "${upgrade##*/}"
    "${compose[@]}" exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -uroot "$MYSQL_DATABASE"' < "$upgrade"
done

"${compose[@]}" up -d --wait api nictool-legacy
failed_suites=()
runtime_types=$("${compose[@]}" exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mariadb -N -uroot "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM nt_nameserver_export_type WHERE name IN (\"coredns\",\"native\")"' </dev/null | tr -d '\r')
printf 'post-upgrade v3 runtime types expected=2 actual=%s\n' "$runtime_types"
if [[ "$runtime_types" != 2 ]]; then
    failed_suites+=("v3-upgrade-seeds")
fi

run_suite() {
    local name=$1
    local log="$suite_log_dir/$name.log"
    shift
    echo "running $name"
    local status=0 result
    "$@" >"$log" 2>&1 || status=$?
    result=$(python3 -B "$script_dir/suite_result.py" "$status" "$log")
    echo "suite result $name $result"
    if [[ "$result" != PASS ]]; then
        failed_suites+=("$name")
    fi
    awk '/^(==> libs\/|All tests successful\.|Files=|Result:|# (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms)|ℹ (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms)|Failed [0-9]|make:.*Error)/ || /^[[:space:]]*not ok [0-9]+/ || /unknown nameserver type|Error logging in:|#.*Failed test/' "$log"
}

run_suite v3-api make -C "$workspace" test-api
run_suite v3-libraries make -C "$workspace" test-libs
run_suite v2-unit make -C "$workspace" test-v2-unit
run_suite v2-soap make -C "$workspace" test-v2-xt-soap
run_suite v2-rest make -C "$workspace" test-v2-xt-rest

if [[ ${#failed_suites[@]} -gt 0 ]]; then
    printf 'failed suites: %s\n' "${failed_suites[*]}" >&2
    if [[ "$allow_test_failures" != true ]]; then
        exit 1
    fi
    echo "application test failures were retained as findings" >&2
fi
