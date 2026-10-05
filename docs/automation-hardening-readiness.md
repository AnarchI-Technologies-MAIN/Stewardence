# Automation hardening preparation

Core and Automation share deterministic snapshot, report, action-card, workflow-receipt and recovery admission. The disabled collector port in apps/jobs/automation_contracts.py admits only versioned read operations and bound organization/connection/generation/nonce identities. It carries no credentials, raw financial payloads, arbitrary endpoint or provider-write operation. Shape checks do not resolve artifact authority.

Current qualification scope: local contract attacks for cross-tenant/connection substitution, stale generation, replay response, unavailable evidence fabrication and unsupported writes. No broker, signed workload identity, live collection, scheduled provider access, production activation or Automation readiness follows from these checks.

## Next executable qualification lanes

1. Same-Droplet private credential broker container: adopted workload identity and operation allowlist, tenant binding, credential isolation, revocation generation, nonce/replay rejection, bounded request/body/time limits. Main app/renderer/scheduler receive no provider credentials. Worker has no provider-table grants.
2. Lifecycle: live read-only renewal, concurrent refresh rotation, disconnect versus in-flight collection, stale callback/generation rejection, provider outage, exact requested scope and partial evidence. Microsoft permission inventory and Xero P&L/lifecycle remain explicit open gates. No paid Xero plan authorized.
3. Artifact admission: private retention-bounded raw evidence, immutable normalized observations, source receipt resolution, conflicting declarations/observations, unknown coverage, ambiguous account matches and stale data. No model training on customer financial data.
4. Shared pipeline: entitled client schedule → broker read capability → admitted observation receipt → deterministic validation/snapshot → proposed reassessment/report. Automation cannot replace deterministic validation, self-authorize writes, or convert collection into comprehensive inventory.
5. Recovery: credential-broker crash, DB outage, lost provider acknowledgement, orphan storage, duplicate delivery, revocation races and bounded queue pressure. Preserve uncertainty; reconcile before replaying ambiguous effects.
6. Capacity: one-Droplet container budgets, renderer peak memory, queue fairness, bounded batches/coalescing, measured load and backpressure. No asserted fixed customer ceiling. Additional paid capacity requires cost approval.
7. Separate release: final exact-source qualification and Lyra pre-adjudication review, then Alexander's explicit production approval. Keep AUTOMATION_ENABLED=0 and Automation purchases disabled until that release.

Enterprise listeners, event-driven monitoring and adjacent company/editorial systems remain deferred.
