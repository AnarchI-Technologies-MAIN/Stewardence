# Phase 21 checkpoint — production demonstration data

**State:** Complete on 2026-09-05 America/Chicago.

## Deployed source

- Commit: `e6e04836b3a8e6ff61caec78bceef0ba73899767`
- Web deployment: `18867048-5819-40a5-b077-02e21ab23cf3`
- Worker deployment: `22e91144-ee36-47d0-8827-872d1d9102d3`
- Renderer deployment: `9a2a4dc5-1824-438a-9b63-a8389254d8a7`
- All three services reported `SUCCESS` on the exact commit.

## Production demo workspace

- Organization: `Demo Bookkeeping Company`
- Organization ID: `8ac036f1-657c-45ec-9318-c45cec4d2997`
- Inventory: 10 manually entered items; every item deliberately has no linked
  catalog product and therefore does not imply a live connector.
- Named inventory: ChatGPT, Microsoft Copilot, Google Gemini, QuickBooks,
  Grammarly, Canva, Otter, Zapier, LedgerWise AI Bookkeeping Assistant, and
  Unknown AI Tool.
- Scenarios include payroll, banking, external transfer, financial transaction,
  absent human approval, unknown access/retention, low-risk reviewed content,
  client-information analysis, poor ROI, and strong ROI.
- Manual organization rules: 2.

## Immutable assessment and report evidence

- Poor-ROI assessment: `3a2f98b9-71ad-404b-bb38-13223b57811b`
- Poor ROI: `-88.24%`
- Strong-ROI assessment: `eb459e3d-af76-4aed-8fbb-f43385c3d5a5`
- Strong ROI: `488.24%`
- Risk bands present: Low, Moderate, High, Critical.
- Finding severities present: LOW, MODERATE, HIGH, CRITICAL.
- Report: `AL-2026-000004`
- Report ID: `6d84223c-a3d4-43c5-b35c-260a314fb201`
- Report-generation job: `5a22a1be-5a37-4db7-a54f-f3600cd54b87`
- Worker result: `completed` on the first attempt.
- Stored PDF: 137,001 bytes.
- Stored PDF SHA-256:
  `6dd9902ba6703c2e65ad79948cf2d619dd81aba273cec1b42a5619b8280277de`

The result is production-generated data, not a fixture-only test. The demo
account was created through self-service signup, and the workspace remained
empty until the bounded seed command ran under the application role.
