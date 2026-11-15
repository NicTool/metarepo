# v2 REST bridge

A NicTool v2 client transport that speaks to the v3 api. It lets v2's own
test suites run against v3, so they show what v3 still lacks. It is a
workspace tool, not part of NicTool: v2 runs it unmodified, and the whole
directory goes away once v2 users are on v3.

- `lib/NicTool/Transport/REST.pm` maps each v2 API call onto v3 routes and
  shapes the answer the way v2's server did.
- `lib/NicTool/RESTBridge.pm` plugs the transport into an unmodified v2. Load
  it with `PERL5OPT=-MNicTool::RESTBridge` and set
  `NICTOOL_DATA_PROTOCOL=rest`, plus `NICTOOL_SERVER_HOST` and
  `NICTOOL_SERVER_PORT` for the api. It refuses to run if v2 ends up on any
  other transport, so a run can never pass against v2 by accident.
- `prove.sh` runs v2 server tests through the bridge from a scratch copy of
  the v2 tree. It swaps the weak passwords v2's tests create users with for
  ones v3 accepts.
- `t/` holds the bridge's own tests.

```sh
make up-legacy
make test-v2-rest    # the bridge's tests, then xt/14, xt/16 and xt/20 through it
```

The docker compose file mounts this directory into `nictool-legacy` at
`/opt/nt-bridge`.

## What the bridge papers over

Each translation is either a v2 habit v3 has no reason to copy, or a v3 gap
the bridge hides. Keep this list current, so the second kind gets fixed in v3.

| Translation | Kind |
|---|---|
| v2's 301/302 answers for missing or bad ids, before any v3 call | v2 habit |
| A date serial for a new zone sent without one | v2 habit |
| Relative record owners and `@`/`&` targets qualified against the zone | v2 habit |
| v2's packed NAPTR and SSHFP columns unpacked into RFC fields | v2 habit |
| Delegation and group listings rebuilt from several v3 calls | v2 habit |
