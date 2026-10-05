# Stewardence visual source contract

Alexander selected `C:/Users/alexg/Stewardence-Migration/stewardence-design-atlas-v3.zip` as the current visual DNA. Its SHA-256 is `de20edbfda30e959813bc27dc835122547c3912ff0646b5e4694671b0422f516`. A local extracted reference is preserved under `design/atlas-v3`; archive build scripts are reference material and have not been executed.

## Design requirements

- Use the atlas's approved transparent purple continuity emblem family, calm navy navigation, blue controls, white surfaces and light-blue state panels. Purple is brand identity, not risk severity.
- Use local supplied assets and Segoe UI/system typography. No external font, analytics, CDN or provider script is needed.
- Shared identity uses the Overview emblem. Page headings use the mapped semantic variant: Reports for reports, Evidence for receipts/history, Admin for setup/authority. Decorative heading imagery remains hidden from assistive technology; visible page labels carry meaning.
- Follow the atlas's responsive desktop sidebar and mobile workspace menu, table overflow, visible focus states and reduced-motion fallback. Do not replace functional mobile navigation with a hidden sidebar alone.
- Keep sources, evidence coverage, declaration versus observation, connection versus collection, and browser report versus stored PDF distinct.
- Preserve current Django routes, CSRF, membership/owner checks, forced RLS and server-rendered architecture. Atlas references supply visuals; they cannot confer authority or create backend capabilities.

## Source mapping for current work

| Candidate surface | Visual reference | Data boundary |
| --- | --- | --- |
| Core operations and metrics | 01 Overview; 24 Collection history; 41 Audit | Stored jobs and verified recovery receipts; show as-of time and coverage; no live-health claim |
| Client workflow setup | 11 Workspace setup; 42 Workspace admin; 43 Members/authority | Selected versioned business/development/registered profile; relevant settings only; owner authority |
| Report history and schedules | 37 Reports list; 38 Report detail | Immutable assessment/report identities; client-selected admitted artifacts/receipts; artifact availability separate |
| Risk-triggered reassessment | 35 Actions list; 36 Action detail; 50 Authority states | Versioned substantial-risk criteria and admitted signals; proposals remain proposals |
| Recovery states and alerts | 49 States; 50 Authority states | Known retry, review hold, unavailable dependency and integrity failure remain distinct |

The archive contains 51 references. Its maturity labels describe underlying functionality, not production-qualified redesigns. Historical provider failures in reference copy must be reconciled with newer evidence rather than copied into the product as current facts.

## Implementation status

Reference archive inspected; Overview and Reports list mockups opened at full resolution; brand semantics, mappings and shared CSS read. Current operations/history templates remain functional candidates and have not yet been visually reconciled with the atlas. No visual-fidelity, accessibility or production-readiness claim is made.

Successor browser qualification uses the full-tested `a3b11cb5…` image with
synthetic fixtures: report widths 390/768/1280 had no document overflow; tables
scroll within their wrappers; the phone workspace menu opened and Recovery
receipts navigation reached Core operations. The four-page single-tool PDF
specimen was inspected on every page. See report-presentation-qualification.md.
These bounded observations do not establish all-screen atlas fidelity, long-table
coverage, accessibility compliance or production static-serving behavior.

Before visual handoff, compare actual Django desktop/mobile screenshots with the matching atlas viewport and state, exercise keyboard/navigation/forms, and record the resulting QA. Backend qualification alone cannot close this gate.
