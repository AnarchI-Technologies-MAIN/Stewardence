# Candidate staging review record — 2026-10-05

## Disposition and scope

The prior staging-architecture review disposition was **REVISE**. This record summarizes the candidate webhook qualification plan and preserves its open gates. It does not approve staging, production, or customer sales. The exact operational configuration bundle remains local; this public record contains configuration hashes only.

The Stewardence GitHub repository is public. This file is an evidence-only derivative for the `development` branch. It contains no application changes, credentials, active routing configuration, internal service names, ports, hostnames, or allowlist values. No production deployment, database migration, Caddy or DNS change, Docker change, or Stripe provider write occurred as part of this review.

## Candidate identity and configuration evidence

- Intended candidate application image for a future isolated sandbox run: `stewardence-candidate-app@sha256:5fbea431eb74ef89c3a7019fe862e67ed870289ea03c9af42f20ffd5ba5ae4a9`. This identifies the intended candidate image only; it does not establish that the image is staged on the Droplet or bind that image to the broad-suite result below.
- Configured-coverage broad qualification source manifest: `51f90f3c4849b14d3957a66124b9c4df5c16e2758177482eb35d0e53458701aa`; qualification image: `sha256:516413412b898cae66d7b1e6a59c9d3e9b43b431b500fd037f0162ae770e41b6`.
- Exact Droplet candidate Compose file SHA-256: `98c8e7f7ee0f003975458bd2f35070f6d1e25c70ec70606eb57dc56095f5f14b`. The full file is retained locally and is not included in this public repository.
- Redacted local copy of the active Caddy configuration SHA-256: `7c8197730593cc800cea20c66ef1f72ad58432c0b7864fe51ebb1cc85256f208`.
- Redacted local copy of the current customer-host routing section SHA-256: `882b0cc266a91fe716465c9dc2b3711bf524a91e8d4a1f8a113f85986d277396`.
- A proposed sandbox routing sketch is retained locally only. It has not been installed or validated.

The configuration hashes identify retained review artifacts; they are not claims that those configurations have passed a deployment or security qualification.

## Qualification results and unresolved failures

The exact-source broad run with configured branch coverage completed with **2,168 passed, 2 failed, and 3 skipped**. Combined branch coverage was **85.15%**, above the 80% threshold, but the suite remains **RED** because two tests failed:

1. The proposal-identity failure matches the recorded backward wall-clock discontinuity signature. The exact clock setter/root cause remains unknown.
2. The deliberate capture-admission failure remains unresolved. A targeted rerun passed, but that does not close the broad-run failure.

The separate no-coverage run (2,170 passed, 3 skipped) does not replace the configured-coverage result. The focused checkout/settings lane passed 56 tests, but provider creation was mocked. No real Checkout Session, signed webhook delivery, paid-access effect, cancellation, renewal, or expiry was qualified.

Read-only sandbox account inspection confirmed the configured standard monthly sandbox price and enabled test webhook endpoints. No test Checkout or webhook lifecycle was executed. Production and live-provider activity were untouched.

## Proposed boundary and remaining gates

The intended experiment uses a distinct sandbox ingress name, routes only the required signed webhook requests to candidate-only services and data, keeps any checkout UI owner-only, verifies event signature/account/mode before candidate state changes, and leaves customer traffic on its existing maintenance gate. Those are design requirements, not implemented or qualified behavior.

Before staging, the review still requires:

- a digest-pinned candidate image set and proof the intended application image is the one loaded on the Droplet;
- narrowly bounded Stripe API egress for candidate checkout and admission processes;
- explicit account and test-mode binding for the general webhook path;
- an owner-only checkout UI access method separate from public webhook ingress;
- a candidate-only database/object snapshot and restore qualification, plus migration rollback analysis;
- a bounded test window, retained secret-free evidence, and cleanup of temporary routing and credentials;
- explicit Lyra staging approval after reviewing the exact private operational files.

The two configured-coverage failures remain open release blockers. A sandbox diagnostic exception, if later approved, will not count as a green suite or production readiness.
