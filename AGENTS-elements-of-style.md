# elements of style

House style for every written artifact in this project: code comments, commit
messages, PR titles and bodies, issue text, review replies, and docs. The
audience is clueful — maintainers, contributors, and future sessions of coding
agents. Nobody needs the diff narrated back at them.

See also: `AGENTS.md` (workspace rules), `AGENTS-architecture-first-principles.md`
(engineering doctrine), and the "Comments in member-repository code" section of
`AGENTS.md`, which this file extends to prose generally.

## brevity is the default

The most common correct length for a review comment is one line. Answer the
thing and stop. If a draft opens with a greeting or a restatement of the
question, delete the opening and re-read.

Explanations belong in commit and PR notes, not in files. When a file genuinely
needs context, one sentence plus a link to the PR or issue is enough.

## verdict first

State the conclusion in the first clause, then justify. Never build up to it.
"Yes." and "No." are complete answers when they are the answer.

## hedge claims, never instructions

Flag guesses as guesses: "my best guess", "I think", "going from memory",
"untested, but this might fix it". Precision about confidence builds trust;
false certainty destroys it.

But when directing work — naming an artifact and its required end state — drop
the hedges entirely. "The README table indicates RR support; assure it is up to
date." No rationale paragraph unless asked.

That covers work you are directing, not a procedure you are describing. An
instruction you have not run is a claim: run it, hedge it, or delete it. Prose in
a migration file gets read by someone repairing a database under time pressure,
and it will be followed exactly.

## own mistakes fast

"I was wrong, fixed in <commit>." No apology spiral, no post-mortem nobody asked
for. Move on with the point intact.

## refuse with a reason

A decline pairs with a cause, an alternative, or an acknowledgement that the
idea isn't stupid. Own preference as preference: "I don't like changing the API
for this" lands better than "this is wrong", and "you're not wrong, but there
are other issues" is often the whole truth.

## ask, don't order — until it's an order

When inviting justification, interrogate: "any reason to instantiate this vs
inlining it?", "why keep this line?". Questions let the author defend or concede
without losing face. When actually directing (especially steering an agent),
switch to flat imperative and name the deliverable.

## show, don't describe

Paste the artifact: the diff, the shell session, the query output, the RFC
block, the config file. Evidence beats narration. An empty diff output is a
complete argument.

## lists earn their place

Never bullet-point prose. Lists appear when there are genuinely N alternatives,
N steps, or checkbox items. Otherwise write sentences.

## mechanics

- contractions throughout; direct second person
- deliberate sentence fragments for emphasis are fine
- parentheticals for asides and evidence: "(yes, I tested)"
- em-dashes are rare; prefer comma, parenthesis, or full stop
- lower-case tool names in prose (`docker`, `perl`, `node`, `db`) — see
  "Documentation voice" in `AGENTS.md`
- bold the pivotal word, not the whole clause; `_underscores_` for italics
- dry humor welcome, aimed at the situation, tooling, or yourself — never at a
  contributor; emoji sparse, if at all

## commits and PRs

Subjects: short (aim under 50 chars), lower-case opening word. Either
`area: description` (`export/tinydns: regexp optimization`) or conventional
prefixes (`fix:`, `feat:`, `ci:`); append the PR number `( #NNN)` on squash.
Usually no body — the subject carries the change. Vivid verbs for deletions are
a feature: "ripped out", "exorcise". Release commits are literally
`Release vX.Y.Z`.

One branch per change. Small batches — review is serial human time, and a big
pile 'o changes takes a bigger while. Whitespace-only changes go in their own
noop PR. Link the issue (`fixes #NNN`). Rebase and force-push freely; PRs are
not immutable.

## never do these

| anti-pattern | instead |
|---|---|
| wall-of-text explanation in a file | one line + link to PR/issue |
| narrating the diff in the PR body | capture the *why*; the diff shows the what |
| restating the code in a comment | better name, or delete the comment |
| "trust me" as an argument | paste evidence, or add the workflow_dispatch trigger |
| 180 granular issues | a handful of grouped issues with markdown checkboxes |
| mixed-concern mega PR | tidy, focused PR per feature |
| signature block at the end of a PR or comment | just stop writing |
| rhetorical question as a closer | state the next step plainly, or stop |

No sign-offs. The repo owner's name is already on the commit; agents must never
sign anyone's name to anything.
