# Phase 23 Checkpoint - Final MVP Release Gate

Date: 2026-09-06
Product name: Stewardence MVP v1.8
Commit under test: a012afca25edc90161e24299320819659cc8c3d4
Tree under test: 66a05a28cf7ad806d63ebb8f4ffb6d10f65b1056

## Status

Phase 23 is complete.

## Local release-gate evidence

- Full canonical restricted-role suite: 413 passed in 94.49 seconds.
- Coverage: 88.43%, above the required 80% threshold.
- Initial full-suite attempt reached 398 passed with 15 setup errors caused by a Windows temp-directory permission problem at `C:\Users\alexg\AppData\Local\Temp\pytest-of-alexg`.
- The suite was rerun with an isolated accessible temp root and all 413 tests passed.
- Ruff lint: passed.
- Ruff format check: 206 files already formatted.
- Django deploy check: passed with only security.W021, the accepted HSTS preload ramp-up warning.
- Control-file verifier: `CONTROL FILE VERIFICATION: PASS`.

## Production evidence

Production smoke test passed against the deployed Railway URL.

- Run marker: `local-bd005292`
- Status: PASS
- PDF SHA-256: `16f2a9407b76fd0f543af2609d4598ba9b013d7080034018132b9f778f201c6c`
- PDF size: 108600 bytes

Smoke coverage:

- HTTPS and security headers.
- Signup and login.
- Guided workspace setup.
- Manual inventory and risk explanation.
- CSV three-step approval.
- Rule test and save.
- ROI arithmetic and immutable assessment.
- Browser report and private PDF.
- Logout/login and historical retrieval.
- Cross-tenant inventory, report-download, and workspace-activation denials.

Current Railway production services were verified running at commit `a012afca25edc90161e24299320819659cc8c3d4` with application sleep disabled for web, worker, renderer, and Postgres.

## Backup evidence

Phase 20 already records PITR active/current, encrypted off-platform logical backup, and a clean restore drill. Scheduled Railway volume backups remain plan-gated on the current trial plan and are not claimed enabled.

## Freeze disposition

Phase 23 is complete.

On 2026-09-06 America/Chicago, the founder approved an MVP backup amendment:
Railway scheduled-volume backups are deferred while unavailable on the current
trial plan and will be enabled after first paying-client revenue funds the
required Railway plan upgrade. The MVP recovery gate remains satisfied by the
already-verified active/current PITR, encrypted off-platform custom-format
logical backup, and successful clean restore drill.

This checkpoint does not claim Railway scheduled-volume backups are enabled.

The remaining freeze work is release accounting: complete the final release
record, create and verify `v0.1.0`, then close BUILD MODE and enter SELL MODE.
