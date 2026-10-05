# Phase 19D checkpoint

Verified 2026-09-04 America/Chicago / 2026-09-05 UTC.

## Closure evidence

- Assessment snapshots retain Collector evidence and scan hashes, bounded source
  observations, exact-reconciliation lineage and automatic-rule provenance.
- Browser and PDF reports use canonical context version `AL-REPORT-CONTEXT-2`
  and distinguish Observed, Declared, Catalog-derived, Calculated and Unknown.
- Installation never implies use, paid subscription, granted permissions, data
  access or capabilities. Unknown discovered cost is not silently totaled as zero.
- `/download/` is the canonical delivery entry. GitHub Release
  `collector-v0.1.0` carries one bootstrapper, one standalone executable, a signed
  versioned profile and a versioned manifest. No Railway service was added.
- Release archive: `Stewardence-Collector-Windows-x64-v0.1.0.zip`.
- Archive SHA-256:
  `fe7239402a29aa2bf4e732b2de4f9533ba240ddd0d7d46386d0d659926b57b3a`.
- Executable SHA-256:
  `e8228a6cccd79c47f427be3f01ef7973b94a5a0ab71d87c27ba7abf3df1ef00c`.
- Signing public-key SHA-256:
  `c6208fe13ee170ca940752100c053625b82c6b63bdad1f3a660ff7e7e841ae4f`.
- The packaged bootstrapper verified the signature/hashes and produced a complete
  real Windows scan containing 222 observations.
- The unchanged real bundle passed scan -> ingest -> exact GitHub Copilot catalog
  match -> discovered inventory -> detector rule -> immutable assessment ->
  canonical report -> PDF. Two source observations reconciled to one inventory
  item and one automatic rule. The four-page PDF was visually inspected; the
  proof transaction was rolled back and raw local inventory remains ignored.
- The selected Helix Orbit board is preserved byte-for-byte at SHA-256
  `6B9CCC46EA2851A85443CDC703724FB43C34DF3E7EB5D0BA565DEC6C62B71400`.

## Verification

- Ruff lint and format: passed.
- Migration drift and Django system checks: passed.
- Canonical restricted-role suite: 410 passed, 88.46% branch coverage.
- Production migration `inventory.0007_inventoryitem_declared_fields`: applied
  under the owner role before deployment.
