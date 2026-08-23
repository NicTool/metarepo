# architecture first principles

Engineering doctrine for NicTool, distilled from fifteen years of maintainer
decisions. When a design question isn't settled by the code around it, settle it
here. Style and prose rules live in `AGENTS-elements-of-style.md`; workspace
mechanics in `AGENTS.md`.

## define things once

The definition of a domain object — what a zone record is, which fields exist,
what's valid — lives in exactly one place and every layer imports it: web UI for
real-time feedback, API layer for enforcement, server side for storage. If two
layers each implement their own notion of validity, one of them is wrong; move
the definition down into a shared library instead.

## decouple everything

The API is its own thing: runnable as a separate process on a separate host,
embeddable in another service, or (aspirationally) running entirely in the
browser. Parts communicate over narrow interfaces so any part can be swapped or
dropped. Prefer independent packages over monorepo workspaces — libraries like
the RR types are useful to people who run no NicTool at all.

## brokers over backends

Storage sits behind broker interfaces. The domain objects are plain data all the
way through the stack, so what "create user" means in SQL is embodied in one
class and what it means in a document store is another. New backends extend by
adding a broker, not by touching the core. Denormalizing into a document store
is fine; the data is small and speed wins arguments.

In the v3 api this is the `lib/<entity>/store/` layout: a `base.js` interface,
per-backend implementations, and import-time selection via `storeType()`. The
mechanics — and the hard rule against reaching past the seam — live in
`AGENTS.md`.

## small data fits in ram

Tens of thousands of zones fit in a few megabytes. Design serving on the
assumption that everything hot is in memory: real-time availability (a record
created via API answers on the next query) is a feature, not a stretch goal.
Latency between "accepted" and "served" is the enemy; batch-export delays are
why v2 couldn't do dns-01 challenges cleanly.

## the upgrade path is sacred

A new version should bolt onto an existing install without scary migration.
This outranks elegance:

- avoid schema changes when a workaround exists
- new config keys get defaults so old configs keep working
- changing shared behavior (serial bumping, export formats) requires preserving
  what existing users depend on, even when the old way was accidental
- v2 is maintenance-only; features route to v3 and say so ("this is a 3.x
  feature" is a complete answer)

## optional means optional

An integration must not become an install requirement. Feature-detect the
dependency (`eval { require Module }`), fall back to built-in behavior, gate on
a preference. In manifests, recommended-and-optional beats required. Same for
test burden: every new mandatory test gates maintenance forever, so add tests to
v2 reluctantly.

## rfc adherence is the default; looseness is opt-in

The tool exists to prevent human-induced errors in zones, so invalid or
dangerous records are rejected unless explicitly permitted. Non-standard input
gets accepted only behind an explicit option (a `postel: true` style flag), and
only after asking: what does a stricter downstream nameserver do with this
record? A tolerated record that makes an export target refuse to serve the zone
is worse than an early rejection. Read the actual RFC before asserting what it
says — SHOULD is not MUST, and the character limits have precise definitions
worth checking twice.

## fail loud and early

During imports and batch operations, the first unexpected record should stop the
run. A fatal error plus a fix beats 1,500 warnings of failed imports — odds are
good there are plenty more like the first one. Warnings are for things the user
can safely ignore; nothing in a zone import qualifies.

## model the domain without assumptions

Zones exist at every level: TLDs, two-label public suffixes, subdomains, even
`_domainkey.example.com`. The data model has no conception of zone levels and
shouldn't acquire one casually. Store canonical forms (expanded AAAA, fully
qualified names) so comparisons are bulletproof. Name things precisely —
overloaded words like `type` cause years of confusion.

## security posture

Never echo network-received data back without sanitization and encoding, even
when upstream validation "has happened". One commit elsewhere can silently lift
a protection; assume the guard is absent. Delegation is authority: permitting a
party to create zones inside yours permits them to override anything in it.
Choose crypto by dependency weight as much as algorithm — a hash from an
already-present module beats the fashionable one that drags in a tree.

## licensing discipline

Permissive licenses only (BSD, MIT). No GPL dependencies — the bigger risk to
the project is that nobody adopts it.

## code style

- expression over ceremony: inline the single-use variable, return directly
- delete redundant checks; if line 139 already validated, don't re-validate
- anchor regexes; prefer positive matches (`eq`) over negative chains
- readability over cleverness: a long line that must be parsed twice loses to
  three short ones
- match the repo's existing idioms; don't introduce constructs the codebase
  doesn't use
- the formatter owns formatting (perltidy, prettier); never argue whitespace by
  hand
- namespace env vars (`NICTOOL_*`); keep the repo root clean — dist stuff goes
  under `dist/`, containers under `docker/`

Comments follow the rule in `AGENTS.md`: a better name beats a comment, keep
only WHY comments, delete rather than update stale ones.

## testing

Tests are the merge condition: no test, no merge, however obviously correct the
change. Write the test first, watch it fail against current code, then fix —
this order matters more now that agents write most of the code. An issue without
a reproducible test case gets closed pending one; adding the regression test
yourself and reporting "cannot reproduce" is a perfectly good outcome.

## git and release hygiene

Branch per change, off a clean default branch; never work in the default branch
itself. Squash-ready commit series; force-push rebases freely. Releases follow
the standing checklist: one-line changelog entry (PR # optional), bump the patch
version, merge — CI publishes from the default branch tag. A merged commit on
main is not a release until tagged.

## docs

README is for users: install, configure, run. Developer-oriented material
migrates to DEVELOP.md or this metarepo. Docs written from a fresh-clone
perspective are better docs — if getting it running required tribal knowledge,
that knowledge is the missing doc.
