# Agent Instructions — Fello Pulse

Read in this order before doing anything: this file, then `HANDOFF.md` (current
status and environment setup), then `specs/001-renewal-risk-prioritisation/tasks.md`
(what's next), then `.specify/memory/constitution.md` (the non-negotiables).

## Test-driven development is mandatory, starting Phase 5

Phases 1–4 were test-*required* but not test-*first* (code landed, then tests were
added to verify it). That was a mistake to repeat. From Phase 5 onward:

1. **Write the test first.** One behavior, naming the production change that would
   make it fail.
2. **Run it and watch it fail for the right reason** (missing feature, not a typo).
   Never skip this step.
3. **Write the minimal code to pass it.** No speculative generality, no untested
   extras.
4. **Run it and watch it pass**, then run the full suite — not just the new test
   file — before calling the task done.
5. Refactor only with the suite green, and don't add behavior while refactoring.

No production code without a failing test that was watched to fail first. Tests
written after the code they test prove nothing — they pass immediately and verify
only what the author remembered, not what the spec requires. See
`superpowers:test-driven-development` for the full rationale and the rationalization
table if a session catches itself reaching for "I'll test after."

This applies to every task in `tasks.md` from T028 onward, and to bug fixes:
reproduce with a failing test first, then fix.

## Delivery workflow (from the constitution, restated for the agent)

- `spec.md` states behavior, `plan.md` states how, `tasks.md` is derived from both.
  Don't improvise structure that isn't traceable to one of these.
- Ambiguity goes in `clarifications.md` with the reasoning, not silently resolved
  in code.
- A non-negotiable in `constitution.md` is never traded off for convenience. A
  genuinely necessary exception goes in `plan.md`'s Complexity Tracking table with
  the simpler alternative rejected and why.
- Scope deliberately dropped is written down as dropped. Silence about a gap is a
  worse failure than the gap.

## Mirroring and pushing

- `~/Documents/fello-pulse` on the Mac is the durable copy; a cloud sandbox working
  copy, if one exists, is ephemeral and reclaimed on session end — never treat it as
  source of truth.
- Sync mechanics (bundle, not tarball; the stale-copy gotcha; the lock-permission
  requirement) are documented in `HANDOFF.md` — read it before touching the mirror.
- `origin` is `https://github.com/akhilpdas/fello-pulse.git`. Push with a normal
  `git push origin main` once commits are mirrored to the Mac; don't attempt to
  create or reconfigure the remote repo from a sandbox session (it's repo-scoped and
  will 403).

## Keeping this file and HANDOFF.md current

Update `HANDOFF.md`'s Status section at the end of every phase (what's done, what's
verified, what's next, any bug found and fixed). Update this file only when a
process rule itself changes — not with per-phase status, which belongs in
`HANDOFF.md`.
