# Core Clock and Proposal Wait Qualification — 2026-10-05

## Scope and boundary

This note records isolated candidate qualification only. No production system, live Stripe account, deployment, or production database was touched. Results do not establish production readiness. The candidate source is a copied qualification tree without Git metadata; retain its source manifest and immutable evidence receipts when comparing later candidates.

## Clock-discontinuity diagnostic

Evidence: `evidence/20261005T082528.470566Z` (image `sha256:523c89107cb157fa4be454aab62c82d0c5476e7a5086372e68cebf04411d3bbd`). Eight diagnostic batches exercised 1,024 proposal submissions. One request was denied with HTTP 409 and zero persisted workflow/revision/receipt effects. That denial coincided with a backward wall-clock step of 1,303,407 microseconds and `effective_future=true`; monotonic time advanced. A second backward step of 744,234 microseconds did not cause a denial. No denial with stable chronology was observed. This supports clock discontinuity as the trigger in this campaign, but does not identify the clock setter or establish the operational impact. The diagnostic test intentionally remains red because it asserts zero denials; preserve that result.

## Proposal authority after a real database wait

Evidence: `evidence/20261005T083649.493584Z` (image `sha256:64a4e4c60c7aef59352c9a4f9f4356ec3c683315363d4c732aed8e36e3f43fe4`). One hundred actual-role PostgreSQL lock-wait cases passed:

- 50 stable-authority cases: the target waited on a genuine conflicting issued revision, then admitted once after the competing transaction rolled back; replay reused the same issuance and left exactly one target revision and receipt.
- 50 revoked-authority cases: after the same real wait, authority was revoked; the target was denied and left no target revision or receipt.

The test verified an actual database blocker rather than relying only on timing. The suite completed with 100 passed, zero failures, errors, or skips. A separate two-case smoke run also passed (`evidence/20261005T083422.586420Z`).

## Qualification interpretation and next work

The wait/revocation behavior is qualified for these tested candidate paths and role conditions; it does not close other database authority, worker, restore, billing, or production gates. Keep the host clock/root-cause gate open. Next, qualify the authorized Stripe sandbox checkout and signed webhook lifecycle using only the rotated sandbox credentials, with a disposable database and local candidate endpoints. Reconfirm no live-mode or production endpoint is selected before any Stripe CLI listener is started.
