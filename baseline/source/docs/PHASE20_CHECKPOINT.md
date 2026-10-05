# Phase 20 checkpoint — Railway production deployment

**State:** Production and recovery controls verified under the founder-approved
MVP backup amendment. Final release tagging remains part of the freeze gate.
Railway scheduled-volume backups are unavailable on the current trial plan and
are deferred until first paying-client revenue funds the required Railway plan
upgrade. They are not claimed enabled.

## Frozen source under test

- Commit: `7819b56dcce5fc82dafd562437ca7d99c4246560`
- Repository: `AnarchI-Technologies-MAIN/stewardence-mvp-v1.8`
- Branch: `main`
- GitHub force pushes on `main`: disabled
- GitHub secret-scanning alerts observed: zero
- Working product name: Stewardence. Compatibility package names, database
  roles, migrations, and historical identifiers remain AgentLedger.

## Production deployment

- Railway project: `19870d7e-c1c8-4662-ae99-e53354deb53c`
- Environment: production (`b53305bd-f679-4275-b231-500c5974bafa`)
- Public application: `https://web-production-ef568.up.railway.app`
- Web deployment: `c4a4e1be-10d8-4f75-9dee-32d420527003`
- Worker deployment: `636306a5-af20-420e-ae73-6dbe67c0d72f`
- Renderer deployment: `f1241f20-824a-4214-929e-712a86b315dc`
- All three deployments reported `SUCCESS`, `RUNNING`, and commit `7819b56`.
- `web` is the only application service with a public domain. `worker` and
  `renderer` have no public domains. All three have application sleep disabled.
- Web readiness returned HTTP 200 with `{"status": "ready"}`. Gunicorn bound to
  Railway's injected port with one bounded `gthread` worker and four threads.

The web process connects as `agentledger_app`; the worker connects as
`agentledger_worker`. Neither long-running service receives the owner database
credential. The renderer has no database connection, report-bucket credential,
or Django secret. It is reachable only through Railway's private service DNS.

The private `reports` object-storage bucket is configured only for web and
worker. Production rendering was proven through the private renderer and the
result was persisted to and retrieved from that bucket through an authenticated,
tenant-authorized application route.

## Production release smoke

The local release runner completed against the public Railway deployment:

- Run marker: `local-20260905152155-c4a14b0b`
- Result: `PASS`
- Downloaded PDF: 108,923 bytes
- PDF SHA-256: `15a4fe92de794bb2db30adc15f1b7c08bdf8824f6c0c655c2715e285e1f70525`

The independent GitHub-hosted release gate also completed:

- Run: `https://github.com/AnarchI-Technologies-MAIN/stewardence-mvp-v1.8/actions/runs/33989922685`
- Head: `7819b56dcce5fc82dafd562437ca7d99c4246560`
- Conclusion: `success`
- Run marker: `33989922685-1-34a45f16`
- Downloaded PDF: 109,196 bytes
- PDF SHA-256: `786be513e054a37a8389f13b259f4c26a892bf0f7ab602f25d95d24c15de9af2`

Both journeys verified HTTPS/security headers, self-service signup and login,
guided workspace creation, manual inventory and risk explanations, three-step
CSV approval, no-code rule test/save, ROI arithmetic, immutable assessment,
browser report, real private PDF, logout/login historical retrieval, and denial
of cross-tenant inventory, report download, and workspace activation.

The production smoke exposed and then verified the repair of a restricted-worker
artifact persistence defect. The worker remains unable to read workspace
identity rows; PostgreSQL enforces the artifact foreign key, while the model and
database enforce report/snapshot/tenant identity. The focused restricted-role
suite passed 20 tests after the repair.

## Migration and backup evidence

- Production migrations were applied in a bounded operation using the owner
  credential before application traffic used the resulting schema.
- Production migration head contains 42 applied migrations.
- Point-in-time recovery is active and current.
- An encrypted custom-format logical backup is stored off-platform under
  `C:\Users\alexg\Documents\Stewardence Backups\production`.
- Encrypted backup SHA-256:
  `fe505021459084e84cd2b26116b2ac953bac08768e545f28920ea3f673fa5df3`
- Decrypted custom-format SHA-256:
  `b85cabd60b9b38eaa0c8fa13c58d39c8d07c2e7c3acbe3dc80a0e7c385860b09`
- A clean restore drill passed with all 42 migrations, roles, RLS policies,
  grants, and smoke queries verified.

## Founder-approved MVP backup amendment

Approved 2026-09-06 America/Chicago.

For the founder-assisted Stewardence MVP on the current Railway trial plan,
scheduled Railway volume backups are deferred because that provider-specific
control requires a paid plan. The pre-customer MVP recovery gate is satisfied
by the controls already proven in this checkpoint:

- point-in-time recovery is active and current;
- a custom-format logical database backup is encrypted and stored off-platform;
- the encrypted and decrypted backup artifacts have recorded SHA-256 values;
- an actual clean restore drill passed with all 42 migrations, database roles,
  RLS policies, grants, and smoke queries verified.

The founder intends to upgrade Railway and enable scheduled volume backups using
revenue from the first paying client. Until that upgrade occurs, Stewardence
must not claim that Railway scheduled volume backups are enabled.

This amendment changes only the provider-specific backup-mechanism requirement.
It does not waive PITR, encrypted off-platform backup, restore testing, tenant
isolation, or any other security/recovery requirement.

## Remaining Phase 20 release action

- Create the final `v0.1.0` release tag only after the final release record is
  complete and the intended frozen commit is verified.
- No custom domain has been attached. The Railway domain is fully verified and
  is the only current outreach-safe URL. Domain purchase and any DNS/proxy
  change remain separate founder-authorized actions.
## Final v0.1.0 release closeout

Verified 2026-09-06 America/Chicago after the release tag existed remotely.

- Release tag: 0.1.0
- Annotated tag object: $tagObject
- Frozen release commit: $releaseCommit
- Remote main matched the frozen release commit before administrative closeout.
- The annotated tag peeled exactly to the frozen release commit.
- The release-accounting commit contains only release/checkpoint documentation above the already-tested runtime lineage.
- No substantive MVP feature work remains authorized.
- Post-freeze code changes are limited to defects preventing security, correctness, onboarding, assessment, reporting, payment, or customer use.
- BUILD MODE is closed.
- SELL MODE is active.
- The next task is customer validation.
