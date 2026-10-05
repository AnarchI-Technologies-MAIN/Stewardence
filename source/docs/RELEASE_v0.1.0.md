# Stewardence MVP v0.1.0 Release Record

**Release date:** 2026-09-06 America/Chicago
**Product:** Stewardence MVP v1.8
**Release tag:** `v0.1.0`
**Repository:** `AnarchI-Technologies-MAIN/stewardence-mvp-v1.8`
**Branch:** `main`

## Frozen runtime source

The production application exercised by the final Phase 23 release gate is:

- Runtime commit: `a012afca25edc90161e24299320819659cc8c3d4`
- Runtime Git tree: `66a05a28cf7ad806d63ebb8f4ffb6d10f65b1056`
- Phase 23 checkpoint: `docs/PHASE23_CHECKPOINT.md`
- Canonical suite: 413 passed
- Coverage: 88.43%
- Production smoke: PASS
- Django deployment check: PASS with only the accepted HSTS preload ramp-up warning
- Ruff lint and format checks: PASS

The next repository commit, `f4d4e11137d05a483697d995cc0116ecfc38ed8d`, changes only release-control
documentation: `docs/MVP_CHECKLIST.md` and `docs/PHASE23_CHECKPOINT.md`.
It is the documentation checkpoint directly above the tested/deployed runtime
commit and does not represent a different application runtime.

The final `v0.1.0` tag is created only after this release record and the
founder-approved backup amendment are committed. Documentation-only release
accounting does not imply that Railway is running a different application
runtime than `a012afca25edc90161e24299320819659cc8c3d4`.

## Dependency identity

- Canonical lockfile: `uv.lock`
- `uv.lock` SHA-256: `d6b94174f653ada3225770bd9db28a0d86e67fde91cc487ef630be8a6ab28268`

## Database migration state

Production recovery evidence records 42 applied migrations.

Frozen-source Django migration leaf set:

- `accounts.0001_initial`
- `assessments.0002_snapshot_security`
- `audit.0002_audit_security`
- `auth.0012_alter_user_first_name_max_length`
- `catalog.0002_catalog_security`
- `contenttypes.0002_remove_content_type_name`
- `imports.0002_import_staging_security`
- `inventory.0007_inventoryitem_declared_fields`
- `jobs.0002_job_security`
- `organizations.0002_public_onboarding`
- `policies.0003_remove_organizationrule_unique_organization_rule_name_and_more`
- `reports.0004_reportartifact_security`
- `sessions.0001_initial`

The clean restore drill verified the complete applied migration set together
with database roles, PostgreSQL RLS policies, grants, and smoke queries.

## Railway production identity

- Railway project ID: `19870d7e-c1c8-4662-ae99-e53354deb53c`
- Railway environment ID: `b53305bd-f679-4275-b231-500c5974bafa`
- Production URL: `https://web-production-ef568.up.railway.app`

GitHub commit-status evidence for runtime commit
`a012afca25edc90161e24299320819659cc8c3d4` records successful Railway deployments:

### Web

- Service ID: `ada57439-307b-4c34-8614-33bdd8b53189`
- Deployment ID: `82bcca02-0058-4578-b11b-cdf0bf77bbf8`
- Status: success

### Worker

- Service ID: `092b5f3a-8943-4e87-84bd-685997c8a01f`
- Deployment ID: `7d7e6342-ff75-48cd-bbdb-ae464464024d`
- Status: success

### Renderer

- Service ID: `781b77d1-d54a-4b4a-b6c9-eb402d521e60`
- Deployment ID: `2ba3af2e-0166-47d5-b1a3-399c67305b4d`
- Status: success

GitHub deployment object:

- GitHub deployment ID: `6294354720`
- Environment: `stewardence-production / production`
- Ref/commit: `a012afca25edc90161e24299320819659cc8c3d4`

The GitHub deployment object and all three Railway service statuses are
explicitly bound to the frozen runtime commit. Older deployment IDs recorded in
Phase 20, Phase 21, and the earlier production-demo manifest remain historical
evidence and are not represented as the Phase 23 runtime deployments.

## Backup and recovery disposition

Verified before MVP freeze:

- Point-in-time recovery is active and current.
- Encrypted custom-format logical backup is stored off-platform.
- Encrypted backup SHA-256:
  `fe505021459084e84cd2b26116b2ac953bac08768e545f28920ea3f673fa5df3`
- Decrypted custom-format SHA-256:
  `b85cabd60b9b38eaa0c8fa13c58d39c8d07c2e7c3acbe3dc80a0e7c385860b09`
- A clean restore drill passed with all 42 migrations, database roles, RLS
  policies, grants, and smoke queries verified.

### Founder-approved MVP backup amendment

Approved 2026-09-06 America/Chicago.

Railway scheduled-volume backups are unavailable on the current trial plan and
are therefore deferred for the founder-assisted MVP. The founder will upgrade
Railway and enable scheduled volume backups using revenue from the first paying
client.

Until that upgrade occurs, Stewardence does **not** claim Railway
scheduled-volume backups are enabled.

This amendment does not waive PITR, encrypted off-platform backup, clean restore
testing, tenant isolation, or any other verified recovery/security requirement.

## Customer-path evidence

Phase 22 verified the complete customer journey through the deployed product,
including signup, guided organization setup, controlled Collector evidence,
reconciliation, manual/CSV alternatives, assessments, reports, private PDF
storage and retrieval, and historical retrieval after logout/login.

Production walkthrough artifacts include:

- `Stewardence-MVP-Production-Walkthrough.mp4`
  SHA-256:
  `a3de41efcb6483ab5e89be74d121e3a4694b560aca5feeb5dae39a21d105a60a`
- `Stewardence-MVP-Production-Walkthrough-Narrated.mp4`
  SHA-256:
  `13f36bb086de398d09eddafd1db0fb7551e4526f9ee19b5529d3d9457dcb2ebe`
- Downloaded production report PDF SHA-256:
  `d16931184cf84ed9d4794a890b42c1441fa9c637f73c3f37da151278ca6bea97`

Sensitive account identifiers, raw proof frames, and other controlled-demo
details remain outside the public repository.

## Release boundary

No substantive MVP feature work is authorized beyond this release.

After final tag verification, development is limited to defects preventing:

- security;
- correctness;
- onboarding;
- assessment;
- reporting;
- payment; or
- customer use.

New product capability belongs after customer validation and must not reopen the
MVP merely because an improvement is desirable.

## Final disposition

The release record is complete when:

1. this record and the founder-approved backup amendment are committed;
2. `v0.1.0` is created on the resulting release-accounting commit;
3. the tag is pushed and independently verified against the expected commit;
4. the remaining freeze-gate ledger items are closed administratively; and
5. Stewardence moves from BUILD MODE to SELL MODE.
