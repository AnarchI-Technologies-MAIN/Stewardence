# Phase 22 Checkpoint - Production UX Walkthrough

Date: 2026-09-06
Product name: Stewardence MVP v1.8
Production URL: recorded in the local full evidence manifest; public checkpoint intentionally omits deploy URL details.

## Status

Phase 22 is complete.

Closed:

- Production journey through anonymous visitor, signup, organization setup, Collector download page, controlled evidence ingestion, reconciliation, inventory, automatic rule provenance, custom rule creation, assessment snapshot, browser report, PDF download, manual inventory, and CSV import alternative.
- Under-30-minute first useful assessment gate, proven by the captured walkthrough path and 167.966667 second rendered video.

Logout/login retrieval proof:

- The disposable walkthrough account password was reset for this controlled account only.
- The generated credential was stored locally with Windows user-scope encryption.
- Temporary plaintext and hash bridge files were deleted after use.
- After logout and login, the owner workspace was reopened and report `AL-2026-000005` was retrieved from production.
- Local proof frames retained:
  - `049-login-filled-after-ssh-reset.png` SHA-256 48e753d1aa64e5206b788bf068f71c549148e07acb9353ec98fd8497c58f61fc
  - `051-workspaces-after-login.png` SHA-256 d1a99b0118f0841577ef20d3cef0d1f2d83427aa11618a56eb1fddf3189db7d2
  - `053-report-retrieved-after-workspace-restore.png` SHA-256 913f9c739b0d2c6bedf0fa485de72e98371eda66b8769bf29ab86347e9037244

## Production deployment evidence

- Repository: stewardence-mvp-v1.8
- Branch: main
- Commit: 552f66f45ad4a7d6aad75b35e2e7458521a23772
- Tree: 3c087bf60622075454d629ede33ffd496d0dcb51
- Worktree: clean at capture time.

Railway production services were verified running with sleep disabled. Exact deployment IDs, service IDs, image digests, and environment details are retained in the local full evidence manifest and intentionally omitted from this public checkpoint.

## Controlled demo evidence

- Disposable user: recorded in the local full evidence manifest; omitted from public docs.
- Organization: controlled bookkeeping demo organization; exact identifier retained locally.
- Controlled Collector evidence bundle: retained locally.
- Controlled bundle SHA-256: 3f3b0483299646dc74a7540f1b30a214f795e0be761e48f0f4eb5a2946c0a41f
- CSV import fixture: retained locally.
- CSV fixture SHA-256: 1d3df504bfa98502bad34954c55ede2c9d4899d3f5525f5c52cab887747374f3
- Post-repair scan ID: retained in the local full evidence manifest.

The controlled evidence used synthetic registry facts inside a disposable virtual environment. No host inventory was uploaded.

## Scenario outcomes

- Catalog reconciliation: ChatGPT, Microsoft 365 Copilot, and QuickBooks Online reconciled as exact catalog matches; Payroll Shadow Assistant and Unapproved Transfer Agent remained Unknown from the controlled upload.
- Custom rule: `Investigate unapproved banking transfers`, Critical floor for banking information plus external transfer capability.
- Low-risk ROI snapshot: Public Content Assistant, monthly net value $426.00, ROI 968.18%.
- Critical-risk ROI snapshot: Unapproved Transfer Agent, monthly net value $-1270.00, ROI -94.07%.
- Browser report: AL-2026-000005, exact URL retained locally.
- PDF: retained locally.
- PDF SHA-256: d16931184cf84ed9d4794a890b42c1441fa9c637f73c3f37da151278ca6bea97

## Video evidence

- Video: retained locally as `Stewardence-MVP-Production-Walkthrough.mp4`
- Video SHA-256: a3de41efcb6483ab5e89be74d121e3a4694b560aca5feeb5dae39a21d105a60a
- Codec: H.264
- Resolution: 1920x1080
- Duration: 167.966667 seconds
- Narrated video: retained locally as `Stewardence-MVP-Production-Walkthrough-Narrated.mp4`
- Narrated video SHA-256: 13f36bb086de398d09eddafd1db0fb7551e4526f9ee19b5529d3d9457dcb2ebe
- Narration audio SHA-256: 659f38a5240c5d5c9f03b7a4db75463d3798435fdfda449ea414c5bd87d5425e
- Narration script SHA-256: e0a430ce725cfc733acdd19a2a825d9e6785902f70d651f9745b0238e29c795c
- Narrated stream verification: H.264 video stream and AAC audio stream verified with ffprobe.
- Source frames: 41 production screenshots
- Manifest: retained locally as `PRODUCTION_DEMO_MANIFEST.json`
- Evidence note: retained locally as `PRODUCTION_DEMO_EVIDENCE.md`
- Watermark: DEMONSTRATION ONLY - NO REAL-WORLD TRANSACTIONS - CONTROLLED SCENARIOS - TRUTHFUL ENGINE DISCOVERY

## Defect and reconciliation note

The first controlled Collector upload showed all five observations as Unknown because the production catalog had not been seeded. This was a production data omission, not a parser failure. The fail-closed behavior was correct. The catalog was seeded under bounded database owner authority, producing 40 product records, 40 vendors, and 80 identifiers. A second controlled upload then produced the expected three exact matches plus two Unknown controlled records.

## Truth boundary

This walkthrough proves production UI, account, organization, import, reconciliation, rule, ROI, report, and PDF behavior using controlled synthetic evidence. It does not claim real-world transaction forensics or autonomous employee theft attribution. The theft-risk scenario demonstrates configurable rule detection for a declared workflow that can access banking information and transmit externally without recorded approval.
