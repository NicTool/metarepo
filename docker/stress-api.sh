#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime=${RUNTIME:-node:24}
runs=${N:-25}
api_dir=${STRESS_API_API_DIR:-"$root/api"}

if [[ ! $runs =~ ^[1-9][0-9]*$ ]]; then
    echo "N must be a positive integer" >&2
    exit 2
fi

if [[ ! -f "$api_dir/package.json" ]]; then
    echo "API checkout not found at $api_dir" >&2
    exit 2
fi

runtime_tag=$(printf '%s' "$runtime" | tr '[:upper:]/:@' '[:lower:]---')
runtime_tag=${runtime_tag//[^a-z0-9_.-]/-}
image_name=${STRESS_API_IMAGE:-"nictool-api-stress:$runtime_tag"}
log_root=${STRESS_API_LOG_DIR:-"$root/local/stress-api"}
run_dir="$log_root/$(date -u +%Y%m%dT%H%M%SZ)-$runtime_tag-$$"

mkdir -p "$run_dir"
docker build \
    --build-arg "RUNTIME=$runtime" \
    --file "$root/docker/stress-api.Dockerfile" \
    --tag "$image_name" \
    "$api_dir"

failures=0
for ((run = 1; run <= runs; run++)); do
    log="$run_dir/run-$(printf '%03d' "$run").log"
    started=$SECONDS
    if STRESS_API_IMAGE="$image_name" docker compose \
        --env-file "$root/docker/.env" \
        --profile stress \
        run --rm --no-deps -T api-stress >"$log" 2>&1; then
        rc=0
    else
        rc=$?
    fi
    if ((rc == 0)) && awk '/^(ℹ|#) (fail|skipped|cancelled) [1-9]/ { bad = 1 } END { exit !bad }' "$log"; then
        rc=1
    fi
    if ((rc == 0)); then
        printf 'run %d/%d PASS (%ds)\n' "$run" "$runs" "$((SECONDS - started))"
    else
        failures=$((failures + 1))
        printf 'run %d/%d FAIL rc=%d (%ds), %s\n' \
            "$run" "$runs" "$rc" "$((SECONDS - started))" "$log"
        cat "$log"
    fi
done

flake_rate=$(awk -v failures="$failures" -v runs="$runs" 'BEGIN { printf "%.2f", failures * 100 / runs }')
printf 'flake rate: %d/%d (%s%%); runtime: %s; logs: %s\n' \
    "$failures" "$runs" "$flake_rate" "$runtime" "$run_dir"

((failures == 0))
