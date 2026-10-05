# Historical Core qualification failures: evidence and bounded closure

Read-only diagnosis on 2026-10-04. This document adds no product changes or release authorization. Historical failures remain retained. Proposed closure criteria below distinguish current stability from retrospective causation.

## Request identity

The oldest retained qualification log matching `Workflow request identity invalid` is `evidence/20261004T034327.930493Z/qualification.log`. Its full suite had 1,325 passes, two failures and one intentional skip. `test_reassessment_count_type_cannot_poison_honest_retry[quoted]` rejected the honest retry at `app_private.issue_workflow_run`, after deliberately rejecting an invalid proposal count. The trace records the application timestamp `2026-10-04 03:49:00.582133+00:00`, but not the database clock, every identity discriminant, or the failing guard. It does not establish precision loss, clock skew, corrupted identity, or a poisoning exploit.

Subsequent evidence:

| Receipt | Scope and result |
| --- | --- |
| `20261004T040301.745650Z` | Original six count-type cases pass in isolation. |
| `20261004T185653.599161Z` | 61 cases pass: request-identity boundary module plus authority successor module; image `6ba8b567776a49ece185a6b73fba55abc5c791788a8504037edb9c382c1f4db2`. |
| `20261004T192706.940742Z` | Both historical failing cases pass in a later full suite; the suite still fails elsewhere and is not a release receipt. |

The identity module proves equal instants with differing offsets produce identical request bytes/digests; actual app-role PostgreSQL round trips retain microseconds 0, 1, 582133 and 999999 across UTC, -05:00 and +05:30. It records timestamp equality, nonfuture database time, UTC suffix, profile/organization/operation equality and request field count at admission. Its deliberate one-hour application clock skew is rejected without issuance. This demonstrates a preserved database authority boundary, not the cause of the old rejection.

**Disposition:** original cause unknown; current targeted boundary qualified on named snapshots. Do not weaken UTC identity, future-time rejection, payload hash or count-type validation to close it.

## Actual Chromium timeout

The same oldest matching log, `20261004T034327.930493Z`, failed `test_actual_chromium_pdf_preserves_unknowns_and_known_cost`. The exception came from the renderer's elapsed-time check after Playwright rendering and browser cleanup, exceeding the unchanged 60-second budget. It was not logged as a particular Playwright operation timing out. No per-stage timings or contemporaneous resource/process census exists; browser startup, cleanup, host contention and orphan accumulation cannot be retrospectively distinguished.

`20261004T035409.021263Z` passes 18 real-render/renderer/recovery cases, including the originally failing render. The original test checks PDF bytes, extracted unknown-assumption/known-cost text, absence of `$None`, and identical repeated normalized bytes. The later full suite `20261004T192706.940742Z` also passes that case but fails unrelated tests.

The controlled comparison `evidence/renderer-init-comparison/20261004T190126.366155Z` uses identical image `6999e54b4cb3df3db88893d79d2274b885f046e90b7c988333448217e229c772`, four synthetic renders per container, 1 GiB memory, 512 PID limit and unchanged 60-second timeout. Without Docker init: eight Chromium zombies remain. With init: zero remain. Both containers exit successfully. The retained earlier comparison `20261004T190037.036202Z` has the same bounded result. Init causally fixes orphan reaping in this fixture; it does not prove zombies caused the historical timeout. The current local qualifier uses `--init`, 1 GiB and 512 PIDs.

**Disposition:** demonstrated reaping defect mitigated in the qualification container; historical timeout cause unknown. No timeout increase is justified by this evidence. Deployment renderer topology, init, resource limits and concurrent load still require exact-candidate qualification.

## Crash recovery, for related historical accounting

`20261003T182905.355058Z` recorded recovery count zero after a fixed 1.2-second delay at SIGKILL before-commit. It lacks backend-disappearance and database-clock expiry observations. This is not an observed multi-job overcount.

Strengthened `20261004T201001.794794Z` passes five actual worker-role SIGKILL stages: backend disappears; committed running claim survives; uncommitted report metadata/completion receipt disappear; original lease expires by database clock; recovery creates one receipt and a queued attempt-one job; another recovery returns zero; drain processes one job and leaves one artifact plus two verified receipts. `20261004T201156.344092Z` separately passes rollback/receipt atomicity and overlapping recoverers with a deterministic stale-candidate advisory barrier. Global recovery transition count, per-job receipt count and drain count are distinct. Historical timing cause remains unproven.

## Proposed bounded release closure

These are finite candidate acceptance criteria, not completed evidence or substitutes for the wider launch gates:

1. Freeze one final candidate image/source manifest and intended runtime configuration. Pass the complete suite without unexpected failures or errors, retaining the explicit intentional skip; include all original failing cases and identity controls. A run on an earlier image does not qualify later edits.
2. On that same candidate, run the 61-case identity/authority group in a clean invocation and in a deliberately reordered invocation after the renderer/crash group. Preserve all admission checks. Any rejection must record each identity discriminant and application/database time before further diagnosis; do not move the timestamp backward to force admission.
3. Run 20 sequential actual render requests at the intended maximum admitted pack size under intended resource limits and init, plus the intended maximum concurrent render count. Require verified stored/access-controlled packs, unchanged 60-second budget, extracted semantic content, stable same-input normalization, no accumulating zombies and retained stage/resource timings. Explicitly state the supported concurrency; zero additional capacity claims follow.
4. Force render deadline/process loss through the real delivery boundary. Verify bounded safe failure, no completed-pack/baseline advancement, preserved prior baseline/browser preview and a recovery receipt; demonstrate one admitted retry without duplicate artifacts. A post-hoc elapsed check alone is not proof a hung subprocess is terminated within budget.
5. Repeat the five crash cases on that frozen candidate with explicit backend/expiry observations and the two rollback/concurrent-recovery controls. Do not rewrite real leases in SIGKILL cases. Preserve failed receipts and stop on any new unexplained failure.

After these pass and Lyra accepts the evidence, the two old intermittent cases may be classified **historical cause unknown; current candidate stability gate satisfied** rather than kept as an impossible demand to reconstruct absent telemetry. That disposition must retain residual uncertainty and exact tested limits. It does not authorize production or close payment-provider qualification, private object recovery, UI delivery, tenant restore, rollback, or Alexander's final release approval.
