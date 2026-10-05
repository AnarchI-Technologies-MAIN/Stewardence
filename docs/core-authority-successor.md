# Core authority successor — undeployed candidate

Migration `jobs.0012_core_authority_successor` replaces narrow functions while
preserving their existing grants and control-before-job lock order. Historical
migration files and deployed source remain unchanged. No production migration,
service activation or cutover is authorized by this document.

Implemented locally:

- READ COMMITTED is required before authority reads in workflow/card issuance,
  direct Core record admission and worker claim/finish/persistence/recovery.
  A transaction waiting on an advisory lock cannot rely on an older repeatable
  snapshot for these decisions. Both REPEATABLE READ and SERIALIZABLE are rejected.
- Null worker/lease/token and null completion identity/action are explicit failures.
  Tests require the claim, expiry and receipt state to remain unchanged.
- Workflow result bytes must equal the database-derived closed canonical encoding;
  a hash of parse-equivalent whitespace, reordered keys, escaped text or numeric
  spelling is insufficient. Financial values remain outside this queue domain.
- Result keys are closed per operation. Health results must equal the private
  database observation rather than caller assertions. Observation uses the latest
  50 recovery receipts, tenant review-hold count and current owner control.

Health is recorded state, not a live provider/service probe. The database checks
receipt column/job bindings and the immutable admission digest. Historical job
inputs retain their original admission digests; this helper does not claim general
database RFC 8785 canonicalization of arbitrary historical financial JSON.
The Python read verifier independently checks current job payload bytes.
Administrative corruption and actual restore reconciliation remain separate gates.

Actual restricted-role probes include a T1 repeatable snapshot followed by a
committed T2 owner pause or entitlement lapse; subsequent issuance/insertion fails
before new effects. They also cover forged health, canonical encoding, null fields,
worker isolation, and completed/retried/review-held receipt observations.

Focused run `20261003T203850.250100Z`: 67 passed, three test-staticfiles warnings,
25.29 seconds, exit 0. Image:
`sha256:79cb5ae1145befaf32baae51ddfdd76eda79f8cf8fee4e535b7c403007fe8886`.
Frozen source, logs and summary are retained. Earlier failed runs are retained,
including syntax/setup errors and an intermittent existing-test claim failure.
One passing follow-up does not establish absence of that intermittent condition.

New full-suite qualification and persistent Lyra review are required separately.
This successor does not establish overall Core readiness, actual report-object
restore, final atlas/PDF fidelity, live provider lifecycle, or checkout release.
Automation collection remains a disabled port with no live broker admission.

## Second successor repairs

Reassessment proposal counts now require a JSON number in the admitted integer
domain; a quoted count cannot poison a run that Python replay would reject.
Malformed/missing/null/boolean/fractional/unsafe counts are rejected before run
insertion, and the same input identity remains usable by honest dispatch.

Recovery freezes at most 100 candidate IDs, acquires the complete tenant control
lock set in global UUID order, then rechecks each job. Controlled workers with
different A1/B1/A2 candidate sets prove neither retains B before waiting for A;
stale candidates cannot reorder locks or produce duplicate receipts. A separate
rollback/retry probe checks atomic state and receipt recovery.

The stricter isolation fence exposed a genuine audit-handler regression in full
run `20261003T204039.962062Z` (1,136 passed, two failed, one skipped). Audit job
persistence now uses READ COMMITTED with its existing exclusive chain-head lock,
immutable selected rows, conditional event binding and head advancement. No
hashing algorithm, canonicalization version or historical blocks changed.

Expanded group `20261003T205026.145459Z`: 126 passed, three test-staticfiles
warnings, 33.63 seconds, exit 0. Image:
`sha256:033d7cb28c2e7b671166496913eeeb83095d7ecf60983d43dbe7ca248b6eee15`.
The new full-suite result and second review must be recorded before treating
these repairs as fully qualified.

## Final bounded acceptance

Persistent Lyra accepted the authority successor regression for frozen run
`20261003T205521.426662Z`: exit 0, 1,146 passed, one intentionally inapplicable
skip, 120 test-staticfiles warnings, 217.54 seconds. Image:
`sha256:3aada76bfe0a0cb72fc4f57ad28ab67326bb60fe46b2b96bb9f3299228db4ace`.

The actual audit persistence path recorded `agentledger_worker`, READ COMMITTED,
and an active atomic transaction before calling the original handler method.
Actual-role event-content immutability tests ran in the complete suite. The raw
logs, source manifest, probe and full review packet are preserved. Lyra reviewed
that supplied evidence; she did not independently rerun execution.

This closes the reviewed authority/count/lock-order/audit-integration findings
within that named regression scope. Overall Core release remains open. Missing
staticfiles warnings require final release-image/UI serving qualification.
