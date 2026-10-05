# Core hardening acceptance criteria

Automation implementation starts only after the required Core criteria have recorded evidence. Passing local tests is necessary but cannot close live-system requirements. "World class" is an aspiration, not a test result or release claim.

## Required local evidence

- Reproducible source and dependency/image identity; changes beyond original Git HEAD preserved.
- Tenant isolation, forced RLS, effective application/worker privileges, immutable identities and append-only events.
- Unknowns never become asserted zero; negative modeled outcomes preserved; compatible historical snapshots and explicit engine versions.
- Deterministic replay of admitted inputs; provenance, assumptions and coverage limitations visible in browser/PDF reports.
- Report history and downloads require current membership; private/no-store responses; stored PDF hash/size verified.
- Concurrent artifact creation cannot overwrite an existing report; database/object-store crash recovery does not destroy published artifacts.
- Checkout/webhook signature validation, duplicate and out-of-order handling, concurrent founder reservation, entitlement cancellation/recovery.
- Actual Chromium-generated PDF specimens, accessible navigation/forms/errors, bounded pagination and input/upload limits.
- Full current-source qualification and focused regression evidence; skips and remaining limits stated explicitly.

## Required live/operational evidence

- Actual private object storage and anonymous access denial; conditional object creation support verified for the configured S3-compatible endpoint.
- Isolated Stripe test-mode checkout and verified webhook fulfillment; no production charges during qualification.
- Encrypted database backup, offline restore rehearsal and report artifact recovery; approved offsite destination and key custody.
- Existing Droplet resource/load checks, request timeouts, queue backpressure and useful operational alerts.
- Reviewed immutable release, exact migrations, reversible ingress changes, rollback/recovery runbook and final cutover authorization.
- Customer terms, retention and billing disclosure reconcile with implemented behavior.

## Latest implemented fix

Local report storage writes and fsyncs a private temporary file, then atomically links it to the destination without overwriting. Concurrent losers receive an explicit error and temporary files are cleaned up. S3 creation sends `IfNoneMatch="*"`; conflicts accept only an identical winning object, otherwise fail closed. There is no unconditional-upload fallback for an endpoint that does not support conditional creation.

24 artifact/storage/job checks initially passed, including concurrent file creation and S3 conflict cases. Subsequent recovery qualification passed 53 checks, including stale lease rejection, review-hold enforcement, private client status and preservation/reconciliation after a metadata-write failure. The unsafe compensating object deletion was removed. Live endpoint compatibility and process-level crash injection remain open. See core-recovery-contract.md for implemented behavior and remaining gates.

Reference: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html

Production remains unchanged. Automation remains disabled. Enterprise remains deferred.
