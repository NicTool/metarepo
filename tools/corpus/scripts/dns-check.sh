#!/usr/bin/env bash
# Copyright (c) 2026, The NicTool Contributors

set -euo pipefail
umask 077
workspace=$(cd "$(dirname "$0")/../../.." && pwd)
export NICTOOL_CORPUS_TOOLS="$workspace/tools/corpus"
export NICTOOL_DNS_RESOURCE_RECORD_SOURCE=${NICTOOL_DNS_RESOURCE_RECORD_SOURCE:-$workspace/libs/dns-resource-record}
export NICTOOL_DNS_ZONE_SOURCE=${NICTOOL_DNS_ZONE_SOURCE:-$workspace/libs/dns-zone}
mkdir -p "$workspace/local"
NICTOOL_CORPUS_INPUT_DIR=$(mktemp -d "$workspace/local/corpus-dns.XXXXXX")
export NICTOOL_CORPUS_INPUT_DIR
trap 'rm -rf -- "$NICTOOL_CORPUS_INPUT_DIR"' EXIT
compose=(docker compose -f "$workspace/docker/compose.corpus-dns.yml")
if [[ "${1:-}" == --test && $# == 1 ]]; then
    "${compose[@]}" run --rm -T corpus-dns node --test /work/corpus/dns-check.test.mjs
    exit
fi
[[ $# == 1 || $# == 2 ]] || { echo 'usage: dns-check.sh CORPUS [PRIVATE_SOURCE]' >&2; exit 2; }
corpus=$1
manifest=${corpus%.gz}
manifest=${manifest%.sql}.manifest.json
args=("$corpus" "$manifest" "$NICTOOL_CORPUS_INPUT_DIR/dns.json")
[[ $# == 1 ]] || args+=(--source "$2")
python3 -B "$NICTOOL_CORPUS_TOOLS/dns_input.py" "${args[@]}"
"${compose[@]}" run --rm -T corpus-dns
