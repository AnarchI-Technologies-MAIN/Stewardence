# Stewardence Collector — version 0.1.0

The one-shot Collector observes supported Windows installed-program registry
entries. The existing Django application receives and interprets bundles. No
additional Railway service is required.

## Evidence boundary

Only `DisplayName`, `DisplayVersion` and `Publisher` are read under the HKLM/HKCU
uninstall registry roots, in 32-bit and 64-bit views. The bundle contains these
bounded values and their source locator. There is no browser-history, cookie,
password, credential, project-content or recursive filesystem reader.

Records preserve detector ID/version, observation time, source type/locator,
identifier, version, publisher and a SHA-256 over RFC8785 canonical content.
The enclosing versioned bundle also has a canonical SHA-256. Strict validation
rejects additional fields, unsupported versions, duplicate fields/observations,
tampering, malformed dates, nested values and bundles over 2 MB or 2,000 records.
Coverage is complete, partial or unsupported. Partial/unsupported scans must never
be used as evidence of absence.

Device IDs are stable pseudonymous UUIDs selected in the installation profile or
provided explicitly. They contain no hostname or Windows username. Use the same
UUID for rescans of the same device. Observation time changes across runs; source
fingerprints remain stable. Hashes detect content changes, not device authenticity.
An uploaded bundle is Collector-reported evidence, not remotely attested truth.

## Release and execution

The canonical `/download/` page points to the versioned GitHub Release. Version
0.1.0 contains one standalone Windows executable, one PowerShell bootstrapper,
one signed installation profile, one versioned module manifest and the public
verification key. The bootstrapper verifies the RSA-SHA256 profile signature,
executable SHA-256 and manifest SHA-256 before execution. It persists only a
pseudonymous device UUID in the current user's Local AppData folder.

The 0.1.0 archive SHA-256 is
`fe7239402a29aa2bf4e732b2de4f9533ba240ddd0d7d46386d0d659926b57b3a`.
The executable is not Authenticode-signed; the Download page states that Windows
may show an unknown-publisher warning. This is not represented as publisher
attestation.

The signed manifest enables only Windows Installed Programs. Microsoft 365,
Google Workspace, GitHub, Accounting, Browser, Developer Tooling, Continuous
Observation and Desktop Portal identities are reserved and explicitly marked
`post_mvp_not_available`.

Scans and observations are stored in `discovery_scans` and `detection_evidence`.
Repeated identical bundles return the existing scan. Historical rows remain when
subsequent scans omit observations. Exact verified product-name matches use the
existing server catalog matcher and can create one idempotent discovered inventory
item. Unknown matches remain unknown; conflicting exact matches require review.
The latest complete scan for each device can show prior matched inventory that is
no longer observed without changing or deleting the historical rows.

Supported detected AI products can create one versioned advisory organization rule.
The rule records detector, mapping, inventory and generation-fingerprint provenance.
It recommends human review and does not claim observed use, subscription cost,
permissions or access. Automatic reconciliation never updates a human-created rule.

The evidence tables force RLS; app has SELECT/INSERT and worker SELECT only. Runtime
UPDATE/DELETE are absent. Composite foreign keys prevent evidence and detector rules
from referencing another tenant's scan or inventory. Policy and cost decisions do
not execute in the Collector.

## Phase 19B proof

Verified 2026-09-05 UTC / 2026-09-04 America/Chicago:

- Collector/ingestion tests: 13 passed.
- Collector/ingestion plus actual restricted-role evidence tests: 19 passed.
- Ruff format/lint and migration drift: clean.
- Real Windows scan: 222 observations, complete coverage.
- Two reads at the same supplied observation timestamp returned identical records;
  canonical observations hash `6ac60e5a5fec89c49b1e49d1157ff16677b00e99196ebab78dd2bf3141ad8e8e`.
- Raw real-device bundle retained only under ignored local `work/`; file hash
  `B273CCEF8FF9F0EF153DCBB5FBB71AEC9426FD1D5645D89773E31CD097F386DC`.
  No real device inventory was committed to the public repository.

## Phase 19D proof

The packaged release generated a complete real Windows scan with 222 bounded
observations. The unchanged bundle passed ingestion; two observations matched the
verified GitHub Copilot catalog entry, producing one discovered inventory item and
one deterministic detector rule. A snapshot retained the Collector evidence hash,
scan hash and reconciliation lineage; its report preserved automatic-rule
provenance and all five provenance labels. The exact context rendered to a
visually inspected four-page PDF. Proof data was rolled back and the raw local
software inventory remains only under ignored `work/`.
