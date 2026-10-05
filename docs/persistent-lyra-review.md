# Persistent Lyra/DOT review

Requested by Alexander on 2026-10-03. Sent through the persistent Lyra agent in ChatGPT using the Chrome browser-control skill. This is the persistent agent reached through the sidebar Lyra button, distinct from the older pinned Lyra conversation.

Scope: current candidate baseline and qualification summary; actual selected source excerpts for recovery policy, worker persistence/failure sequence, receipt recording/verification, migration 0004 admission, persistence fencing, failure transitions and expired lease recovery. No credentials, private keys, database row contents or customer documents were supplied. The complete candidate repository was not supplied.

Requested outputs: prioritized concrete defects versus unverified architectural risks, attack/reproduction tests, safe fixes, and a Core release sequence preserving tenant/owner boundaries, the single-Droplet container architecture, paused adjacent site, disabled purchases and deferred Enterprise.

Review returned and preserved in evidence/persistent-lyra-review-20261003.txt. No deployment or task execution was requested from her. Model review is advice to reproduce against source, not independent runtime qualification or release authority.

Source cross-check already confirms exhausted-retry messaging can promise another retry on attempt five while the state transition stops the job. Additional review targets include wrapped authority failures, compromised-worker receipt admission, absent receipts for lease recovery, effective restored privileges and actual crash qualifications.

Returned priorities: stronger complete-schema receipt admission; permanent/authority veto throughout supported exception chains; atomic receipts for expired lease transitions; outcome-derived exhausted-retry messaging. Reviewer found no demonstrated stale-worker database-persistence defect in the supplied transactional fence, while requesting separate-process race/crash evidence and handler/storage source.

Cross-check: locally executed the existing qualified candidate image with network disabled. RuntimeError -> PermissionDenied -> httpx.ReadTimeout via __cause__ returned permits_retry=True. This confirms incorrect retry classification, not a provider write or production effect. Reviewer called this user-reported execution; precise provenance is execution by the development assistant through the local Docker CLI, supplied to the reviewer.

Migration 0004 source confirms shape-only digest checks and no complete payload-key/type/outcome validation at admission. Python read-time verification is stricter. Real-worker-role attack tests are still required to prove admission and dashboard effects; this review does not establish a silent verifier bypass. Lease recovery source confirms missing receipts. These findings remain open; no repair or new qualification is claimed by this record.
