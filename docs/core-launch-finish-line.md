# Core launch finish line — 2026-10-04

Alexander confirmed the narrow launch brief: standard Core at $99/month,
self-service checkout, optional personal onboarding, and working delivery. Scope reduction does not
reduce tenant privacy, payment correctness, recovery or report-delivery controls.

The release journey is: signup → payment → correct workspace access → promised
assessment/report → cancellation, with renewal and expiry handled correctly.
New Enterprise purchasing, new founder acquisition, additional integrations and
cosmetic expansion stay outside this critical path. Existing founder contracts
and prepared tier quotations must remain intact. No outreach is sent by this
development work.

## Current blocking evidence

| Gate | Verified state | Required closing evidence |
| --- | --- | --- |
| Current paid entitlement | Initial Core invoice admission is implemented; durable ongoing paid coverage remains proposed | Issued payment intervals, renewal ordering, exact expiry and actual-role execution/persistence denial |
| Checkout lifecycle | Sequential replay and existing-row cancellation races have passing focused controls | Absent-row/concurrent checkout-intent qualification and final-source regression |
| Full-source qualification | `20261004T034327.930493Z`: 1325 passed, two failed, one intentional skip | Root-cause evidence and a final named-test run; preserve this failed receipt |
| Workflow identity failure | Six original cases and three new boundary controls pass in isolation | Diagnose the full-run identity rejection without weakening issuer checks |
| Actual PDF delivery | Focused real Chromium/render/recovery group: 18 passed (`20261004T035409.021263Z`) | Explain the full-run 60-second timeout; qualify delivery and safe failure under the intended resource limits |
| Payment integration | Read-only test credential authentication succeeded; offline signed fixtures exist | Real test checkout, webhook, fulfillment, cancellation and renewal evidence |
| Recovery and release | Existing operational restrictions remain | Customer-journey evidence, tenant/object restore and concrete rollback package, Lyra review, Alexander final approval |

A focused rerun does not explain an earlier failure. No timeout increase,
timestamp margin, guard relaxation or changed assertion closes these gates.
The isolated mutation campaign's 48 detections and 31 successful repetition invocations
are bounded evidence; they do not establish live checkout, capacity or release
readiness.

## Operational restrictions

Production is unchanged by this brief. Public maintenance and preview gates,
stopped production worker, disabled Automation purchases and existing provider
boundaries remain in force until explicitly changed. No production migration,
deployment, payment collection or provider write is authorized by this document.
Worker activation necessary for report delivery requires qualified configuration
and the final release approval.

Personal onboarding may help customers enter inventory and interpret a report.
It cannot substitute for paid access, privacy or delivery. A recurring assisted
review promise requires an explicit service commitment; automatic monitoring
must not be implied by Core launch copy.

