# Next development work

These are open improvements, not claims about completed features. Pick a small slice, add a failing behavior test, implement it, and record the decision in a pull request.

| Priority | Work | Acceptance criteria |
|---|---|---|
| 1 | Versioned labeling guidelines | Managers publish guidance; review form displays it; votes retain the guidance version used; changes are audited |
| 2 | Audited reassignment | Manager can release an unfinished slot and assign another active reviewer; completed votes are preserved; races cannot overallocate |
| 3 | SQL-based metric aggregation | Same outputs as the tested reference implementation; query count stays bounded as records grow; benchmark on a declared synthetic dataset |
| 4 | Frozen export manifests | Export records schema version, record versions, row count, and SHA-256; replay produces the same release; later vote edits do not mutate a release |
| 5 | Background imports | Job progress, cancellation before commit, bounded batches, and retry keys; failed jobs cannot leave partial datasets |
| 6 | Account operations | Rate limiting, invitations, password reset, and optional external identity; permission tests cover enrollment and revocation |
| 7 | Reviewer calibration | Managers provide a separate gold set; accuracy is reported separately from agreement; no leakage of gold labels before review |

## Suggested first contribution

Add a `guidelines` field to datasets, display it in the review panel, and test HTML escaping and role permissions. Then decide whether guidance can change once votes exist. Explain that trade-off before implementing history or versioning. Keep the PR small enough that another engineer can review it in one sitting.

## Engineering questions worth investigating

- At what dataset size does the current Python metric scan become too slow? Measure latency and query count before changing it.
- Should a manager who already voted be allowed to adjudicate? The current system permits it and records the actor; some workflows may require an uninvolved adjudicator.
- Should an agreed record be frozen or editable? It currently allows assigned reviewers to revise until adjudication; frozen export versions would give consumers a stable release boundary.
- Should normalized duplicate text with a different ID be skipped or retained as separate observations? The current behavior prioritizes a unique text corpus. A source-level observation model would support different semantics.
