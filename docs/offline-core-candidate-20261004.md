# Offline Core candidate checkpoint

Prepared by Lyra for Alexander. No production mutation or release approval.

Core launch remains USD 99 standard monthly only. New founder acquisition,
Automation purchases and production workers remain disabled by policy. Actual
remote runtime state was not re-inspected in this checkpoint; the prior verified
maintenance/preview boundaries remain the release requirements.

## Exact qualification

- Full source: `evidence/20261003T235918.400817Z/qualification-summary.json`;
  1171 passed, one intentional Xero remote-disconnection skip, 129 warnings.
  Candidate image `sha256:f8b63f61b9594949909127463a1f4f8855ead66b2ee233c5f3385626ec47d41d`.
  Actual Chromium and five SIGKILL tests enabled.
- Packaged HTTP: `evidence/production-package-http/20261004T000321.742621Z/qualification-summary.json`;
  image `sha256:ef5cf3903e898a997c14520aceb66edf8cce2652fc75e90442fa0cb8006922cb`.
  281 host build inputs, 280 independently checked image source files; real
  local Gunicorn HTTP, synthetic internal database, no public ports, pre-start
  restrictions and post-start endpoint verification; cleanup verified.
- Restored access: `evidence/restored-report-access/20261004T000759.041367Z/qualification-summary.json`;
  current candidate, actual restricted app role, six existing restored report
  objects (698217 bytes), authorization and corruption controls, unchanged
  metadata, cleanup verified. Entitlements explicitly synthetic where absent.
  Windows/WSL custody remains on one physical machine.
- Layout: `evidence/report-layout-qualified/20261003T234711.969251Z/qualification-summary.json`;
  renderer `sha256:d4c73ead4d1c6bf16c77089a6837e039a0ab84c4a9a48d8b4f60852809e57a27`.
  Repeated byte-identical synthetic PDFs, 5/9/27 pages, unchanged artifact
  digests, print-width geometry and section-bound completeness.
- Harness controls: `evidence/qualification-harness-negative-controls-20261003.json`;
  actual PDF blank/footer-only/misplaced-label controls, exact caller
  failed-receipt controls, filesystem membership and pre-start inspection mocks.
  Mock faults are not induced daemon faults.

## Review

Earlier authority, restore and initial presentation closures remain bounded to
their reviewed source/runtime evidence. The dedicated Lyra chat confirmed
receipt of `evidence/lyra-harness-billing-successor-packet-20261004.txt` and began
review. Lyra subsequently closed all three harness findings and opened
CORE-ADMISSION-01 (payment-to-period binding); record:
`evidence/lyra-harness-billing-successor-review-20261004.txt`.
A newer coverage candidate reproduced 13 predecessor failures and passed 73
focused tests. Three signed rollback/recovery controls were then added; its
exact full source `20261004T001918.105554Z` passed 1187 tests, one intentional
skip, 132 warnings, image `312ee835…`. The qualifications above belong to
the earlier 1171-pass snapshot. Fresh coverage-package HTTP passed in
`evidence/production-package-http/20261004T002423.082690Z`, image `2eef9721…`,
with 281 image files/282 host build inputs. Six-object restored access passed
in `evidence/restored-report-access/20261004T002428.891015Z`. The coverage
successor was submitted with raw full logs and the complete source manifest;
its final disposition remains pending. Browser recovery confirmed submission after a
click timeout; no duplicate was sent.

## Failures retained

`20261003T234701.222036Z`: 1169 passed, one failure, one skip. The second
cross-tenant worker claim returned None after entitlement. Isolated reruns,
the 52-test Core/RLS group and later full suites passed. Root cause remains
unknown; the later green run does not erase the intermittent concern. A new
pre-claim admission-state assertion adds diagnosis without weakening the claim.

`20261003T235537.411177Z`: 1170 passed, one failure, one skip. The SDK gateway
test accidentally called its fixture's mock; corrected to preserve and call
the actual gateway before the final source freeze. Prior signed-event tests
exposed and repaired current-SDK resource `.get()` incompatibility.

## Next bounded development

1. Obtain Lyra's successor disposition and repair any reproducible findings.
2. Qualify Core paid-period expiry consistently in Python entitlement and
   database workflow admission, while preserving owners' ability to pause work.
   Unknown historical periods cannot silently become verified paid evidence.
3. Qualify subscription-update failure/recovery and concurrent standard checkout
   admission; preserve exact existing founder commitments.
4. Diagnose the worker-claim intermittence before production readiness approval.
5. Real Stripe authorization, API compatibility, account price/portal identity
   and sandbox checkout/webhook delivery remain deferred at Alexander's request.
   Never substitute local signed fixtures for these gates.

No commits, pushes, production migrations, deployments, service activation,
public cutover or provider/Stripe account writes were performed. No new keys
are requested for current offline qualification.
