# Actual report recovery qualification

The immutable database backup (ciphertext SHA-256
`0b20cd7ede2d1218e210af325f3ee19fa98a6d2cacff895728468c58981e1dbc`)
and six actual private PDF objects were recovered from encrypted Ubuntu WSL
custody. The Windows recovery key was not copied to WSL or a container. The
698,217 recovered PDF bytes matched archived artifact ownership, report and
assessment bindings, sizes and SHA-256 values. The byte-restore receipt is
`evidence/report-object-restore/20261003T212039.504272Z/restore-summary.json`.

The request successor is recorded in
`evidence/restored-report-access/20261003T221725.466960Z/qualification-summary.json`.
It runs the same exact image as the 1,146-pass full-suite run:
`sha256:95b24d4215bb6cec845a42ee8061504b95d62ba11e4c6f53c7d596c354680946`.
All six objects passed authorized retrieval, anonymous login-redirect rejection,
cross-tenant rejection, missing-object rejection, changed-length corruption
rejection, same-length hash corruption rejection, restored-copy retrieval and
post-request immutable artifact metadata comparison. Failure responses were
private/no-store and did not attach a PDF.

The real Django middleware/views used `agentledger_app` at READ COMMITTED.
Absent subscriptions were explicitly fabricated in the disposable clone for
positive controls, after unentitled denials. These are not original-snapshot or
production entitlement facts. No HTTP listener, provider request or production
write occurred. Candidate migrations ran only on the disposable clone.

The final request harness used exhaustive cleanup, verified all three named
containers and the internal network absent, and withheld success until cleanup
completed. The injected first-target deletion failure exercise proved that later
targets and the network are still attempted and cleanup success is withheld.
The byte-restore harness now shares that helper; its earlier successful execution
does not constitute a fresh execution of that successor.

The new Lyra-Stewardence consultation closed all five bounded restore
qualifications for the exact request runner and ownership-enforced cleanup
successor, using supplied restore execution and independent mock regressions.
The accepted request run is `20261003T223502.982651Z`, verified 22:35:39 UTC.
Network creation carries a full UUID run marker; cleanup resolves an untruncated
ID, inspects that ID's name/label/identity, removes only that verified ID, and
checks name absence independently. Replacement, foreign ownership and unreadable
ownership prevent success. The independent reviewer reports 27 helper and 18
caller mock scenarios; those are not independent Docker or restore runs.

Evidence: `evidence/lyra-cleanup-exact-id-packet-20261003.txt` and
`evidence/lyra-cleanup-exact-id-review-20261003.txt`. Acceptance excludes the
helper's optional no-owner path, other callers, container replacement/ownership,
future source/images and overall Core production readiness.

Windows and Ubuntu WSL share one physical machine. These results do not establish
device-loss survival, production HTTP delivery, complete credential recovery or
full-system tenant replay. A later product image requires explicit source
comparison or another restored request run before combining release evidence.
