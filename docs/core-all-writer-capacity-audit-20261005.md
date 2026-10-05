# PDF writer and capacity audit — candidate source, 2026-10-05

Read-only source review during the final-source qualification freeze. No actual-role exploit, production inspection, bucket listing, deletion, or runtime qualification was executed here. These findings keep the all-writer quota/orphan release gate open.

## Proven source paths

1. `apps/reports/views.py:generate_report_action` admits schema-1 reports for write-role members, calls `create_report` and `ensure_report_generation_job`. It does not reserve review capacity. Schema-2 UI requests are rejected here.
2. `apps/jobs/core_workflows.py:dispatch` REPORT, including configured `tick` schedules, calls the same report/job helpers without a review capacity reservation. Report identity is one per snapshot; that limits duplicates, not the number of distinct snapshots/objects.
3. `apps/reviews/services.py:request_pack_artifact` stages report/job inside the existing tenant transaction, then calls the narrow SQL request issuer. Its frozen cycle has a 16MiB reservation and a 3GiB organization budget. Failure rolls back report/job effects.
4. Factory-installed `ReviewReportGenerationHandler` checks lease and, for linked review jobs, frozen projection/current authority. Unlinked jobs deliberately receive a null review target and delegate to ordinary report generation.
5. Both branches converge on `ReportGenerationHandler.persist` → `persist_pdf_artifact` → `storage.put` → artifact metadata insert. This checks a per-object 16MiB limit and per-report serialization, not organization capacity or an admitted storage reservation.
6. Local publication is non-overwriting; S3 uses `IfNoneMatch=*` plus exact-byte conflict readback. These protect object identity but do not establish quota authority. Storage credentials remain a trusted worker boundary, not a database-enforced external-object capability.

## Concrete missing guards / release limitations

- Legacy report UI and Core REPORT dispatch can create PDFs without review reservation/monthly/pending limits. A series of distinct snapshots therefore bypasses the review-specific storage budget. This is source-derived; an effective-role end-to-end probe is still required before describing an executed bypass.
- Freeze reads artifact metadata plus outstanding review reservations under the review capacity lock. Ordinary artifact persistence does not acquire that lock or perform a final capacity check. Concurrent ordinary writers can invalidate a freeze's budget observation, even though existing committed legacy artifacts are included in its sum.
- Worker INSERT on `report_artifacts` remains granted. Its identity trigger checks canonical report/tenant/snapshot/key, MIME, digest shape and positive size; it does not enforce a 16MiB SQL upper bound or storage-reservation admission. Python enforces the cap on its admitted persistence path. Do not claim a database-enforced all-writer bound from that helper alone.
- Object publication precedes transactional metadata. A failed/rolled-back persistence deliberately retains the object. For review jobs, the outstanding reservation still conservatively charges its maximum and unused-stop refuses any admitted/ambiguous report work. For unreserved legacy jobs, an orphan has neither artifact bytes in the sum nor a durable storage reservation. No object-custody/reconciliation ledger covers every writer.
- Review completion converts its existing reservation to consumed only after readback and immutable completion. Unused-stop releases positively unused reservations without deleting objects or refunding monthly allowance. Neither is authority to reclaim ambiguous or untracked objects.

## Smallest bounded candidate repair

Introduce a shared durable object-write admission used by every PDF-producing path, with exact organization/report/snapshot/object-key identity and maximum bytes. Reuse the existing review reservation for review jobs; issue a narrowly authorized legacy reservation or explicitly close legacy PDF writes at the release gate until qualified. Do not create a second customer inventory or change old snapshot semantics.

Admission must precede external publication and survive metadata rollback/crash. Acquire organization capacity serialization in the established control-before-capacity order; account for retained artifacts, outstanding write admissions and unresolved objects once each. Final persistence must consume exactly its issued admission with an actual-size upper bound; SQL must reject raw artifact insert without that authority. Existing one-object-per-report and conditional publication remain.

Record append-only publication outcomes: reserved, attempted/ambiguous, verified/adopted. Treat ambiguous external results as still charged. A bounded operator reconciliation can verify the deterministic key and bytes before adoption; this proposal does not enable deletion. Storage credentials remain trusted unless an independently authenticated storage broker is later qualified.

Required actual-role qualifications: each UI/dispatch/scheduled/review path; raw worker INSERT denial; simultaneous distinct-report writers at the quota boundary; freeze versus legacy writer; object-success/DB-rollback; upload ambiguous response; matching-object adoption; different-byte conflict; replay with no double charge; pause/entitlement/lease changes after waits. Confirm live DigitalOcean conditional-storage behavior separately. Passing source tests cannot close that live gate.
