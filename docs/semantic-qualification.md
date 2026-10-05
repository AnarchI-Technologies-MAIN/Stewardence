# Offline semantic foundation — scoped qualification

Persistent Lyra was consulted before implementation. Her final disposition closes
the offline semantic source review and accepts the supplied qualification result
within that scope. She did not independently reproduce the execution chain.
This is not Core production approval or authorization for live admission/writes.

The implemented foundation is a closed JSON Schema 2020-12 input/output contract,
OpenAPI 3.1.1 components, RFC 8785 canonical bytes, exact decimal strings and a
versioned entity-descriptor profile. Two offline adapters handle QuickBooks sandbox
CompanyInfo and Microsoft organization descriptors. Namespaces, declarations,
missing/null/empty values, capture/effective times and partial coverage stay explicit.

`prepare_read_request` freezes source and interpretation pins; `normalize_request`
rejects changed pins. Exact-source replay can reject fabricated output even when
its digest is self-consistent. Neither operation authenticates a capture or issues
authority. Existing provider routes, permissions and credentials remain unchanged.

## Exact accepted candidate

- Registry artifact: `29f2a2e08845bb7bdc35595eddb691627dc157391daf431938fff6a717e95e3c`.
- Linux qualification: `20261003T202337.730419Z`, exit 0.
- Image: `sha256:8927f8248d414e593361a5d6d02922342d0a696a68d2aa3f6cea8cb6182b45ac`.
- Full suite: 1,100 passed, 1 skipped, 120 warnings, 188.79 seconds.
- Focused semantic tests: 131 passed on Python 3.14.7.
- Skip: Xero remote-disconnection case is intentionally inapplicable to the
  other provider parameter; see `test_provider_lifecycle.py`.
- Warnings identify missing collected staticfiles in the test environment; this
  run does not qualify production static asset delivery.

The retained evidence directory includes frozen build context, per-file source
manifest, build log, complete qualification log and summary. PostgreSQL 18.6
restricted-role probes, actual Chromium rendering and Linux SIGKILL tests ran
locally. No live providers were tested and production was not touched.

Failures remain preserved: the earlier 1,080-pass run had one failed test; its
successor had 1,097 passes and one fixture teardown error. Neither is reclassified
as passing. The final cleanup selects only the two fresh fixture organization IDs.

Review evidence:

- `evidence/lyra-semantic-contract-consultation-20261003.txt`
- `evidence/lyra-semantic-boundary-review-1-20261003.txt`
- `evidence/lyra-semantic-boundary-review-2-20261003.txt`
- `evidence/lyra-semantic-boundary-review-3-20261003.txt`
- `evidence/lyra-semantic-final-qualification-packet-20261003.txt`
- `evidence/lyra-semantic-final-disposition-20261003.txt`

## Next integration gates

Before live use: authenticated capture, immutable source-receipt/account/tenant
binding, retention, atomic admission, supersession validation and version selection.
Before distribution: qualified signing/provenance, operator release approval,
tenant impact preview/acceptance and revocation/drain/rollback rules. Hosted SaaS
updates are installed in the existing Droplet's containers; tenant capability
selection ordinarily needs no client reboot. No installer or notice UI is shipped.

Provider writes need separately authorized exact actions and qualified outcome
reconciliation. No production keys are required for this offline foundation.

Core authority successor migration 0012 was written after this source freeze.
These full-suite counts do not qualify that later source; it has separate probes
and needs a new complete run and review. Core release, UI, report-object restore
and Automation admission gates remain open.
