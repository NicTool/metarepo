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
make test-v2-rest    # the bridge's tests, then the v2 files it passes in full
```

The docker compose file mounts this directory into `nictool-legacy` at
`/opt/nt-bridge`.

## What the bridge papers over

Each translation is either a v2 habit v3 has no reason to copy, or a v3 gap
the bridge hides. Keep this list current, so the second kind gets fixed in v3.

| Translation | Kind |
|---|---|
| v2's 301/302 answers for missing or bad parameters, from v2's own table, before any v3 call | v2 habit |
| v3's 400 as v2's 300 sanity error, and v3's 409s in v2's codes and words | v2 habit |
| v2's words for v3's refusals of a bad TTL, record type, record name, address or username | v2 habit |
| v2's 300 for v3's refusals on a deleted object, once a lookup shows the row is deleted | v2 habit |
| v2's wording for a failed login, and an empty session after logout | v2 habit |
| A date serial for a new zone sent without one | v2 habit |
| v2's SOA timer defaults for a new zone, and trailing dots stripped from its name | v2 habit |
| `hostmaster.<zone>.` for a new zone sent without `mailaddr` | v3 gap: v3 stores NULL, then answers 500 |
| `new_zone_record` with an existing id updates that record | v2 habit |
| Record owners unqualified without regard to case | v2 habit |
| Relative record owners, CNAME and PTR targets, and `@`/`&` shortcuts qualified against the zone | v2 habit |
| Relative MX, NS and SRV targets refused, with v2's complaint about any bad character | v2 habit |
| AAAA addresses read back in full | v2 habit |
| An apex record named for its zone, with the trailing dot | v2 habit |
| v2's packed NAPTR and SSHFP columns unpacked into RFC fields | v2 habit |
| Delegation and group listings rebuilt from several v3 calls | v2 habit |

## What v2's tests still catch

Where v3 accepts what v2 refused, the bridge passes v3's answer through. v2's
test then fails. These are v3's to fix:

- A user created without a first or last name is stored with NULL. Every listing
  that holds it then answers 500.
- A second user with the same username in one group, and a second group with
  the same name under one parent, are both accepted.
- Nameserver `datadir`, `logdir` and `remote_login` take any value.
- A nameserver that zones still use can be deleted.
- PUT `/zone_record` skips its rdata checks unless the type changes.
- Records may conflict with a subzone, share a name with a CNAME, or have an
  owner outside their zone, and a TTL edit leaves the rest of the RRset alone.
- MX, NS and SRV targets aren't checked for bad characters, and an A record
  takes `0.0.0.0`.
- Deleted zones, records, nameservers and groups can still be edited.
- A password change never asks for the current password. The bridge answers
  510 rather than let the change through.
- Nameserver listings ignore search and subgroups, and the global log can't
  sort by target.
