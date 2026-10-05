# Phase 19C — deterministic reconciliation and automatic rules

Verified 2026-09-04 America/Chicago / 2026-09-05 UTC, Windows Python 3.14.7 and PostgreSQL 18.6.

## Implemented boundary

- Collector product names are passed to the existing exact, verified catalog matcher. Known, review-required and unknown outcomes are stored on immutable evidence rows.
- An exact match links to an existing current inventory record for that catalog product or creates one deterministic discovered record. The stable product fingerprint prevents repeated scans and device observations from duplicating inventory.
- Latest complete scans represent previously matched software that is no longer observed on that device. Partial and unsupported coverage never claims absence, and historical scans/evidence are not changed or deleted.
- Mapping registry version 1 supports advisory review rules for ChatGPT, Claude, Gemini, Microsoft 365 Copilot and GitHub Copilot. A rule applies only to its exact catalog product ID.
- Detector-created rules retain detector/version, mapping/version, source inventory and stable generation-fingerprint provenance. Reconciliation uses create-only idempotency and never updates human-created rules. Detector rules can be disabled but cannot be edited, duplicated or deleted through the customer UI.
- `discovery.completed` is recorded for each new accepted scan. `reconciliation.accepted` records exact accepted inventory and newly created rule IDs through the existing audit append path.
- Evidence-to-inventory and detector-rule-to-inventory references have same-tenant composite foreign keys in addition to existing forced RLS. Runtime evidence remains append-only; worker write authority was not added.

## Verification

- Focused Collector, discovery, catalog and organization-rule tests: **47 passed**.
- Canonical `scripts/test.ps1` with isolated Windows temporary storage: **406 passed**, **88.53% coverage** in 257.23 seconds, including restricted application/worker roles and the new cross-tenant reference tests.
- Ruff format/lint, Django checks, migration drift and diff checks: pass.
- Production migrations `inventory.0006_detectionevidence_inventory_item_and_more` and `policies.0003_remove_organizationrule_unique_organization_rule_name_and_more` were applied before application deployment. A read-only verification confirmed current role `agentledger_owner`, both migration records and all three named provenance/same-tenant constraints.

## Remaining boundary

Phase 19D remains open: assessment/report evidence lineage, explicit Observed/Declared/Catalog-derived/Calculated/Unknown presentation, Collector profile and capability-module contract, public versioned artifact delivery, SHA-256 recording, and the real Collector-to-PDF end-to-end proof. Phase 20 remains blocked until Phase 19D closes.
