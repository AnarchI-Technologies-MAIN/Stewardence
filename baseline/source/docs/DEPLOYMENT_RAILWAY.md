# Stewardence Railway Deployment Runbook

**Status:** Web, worker, renderer, PostgreSQL and private storage have been deployed. Phase 20 remains open: the founder's Phases 19A–19D amendments, production customer-flow verification, backups and restore evidence are not yet complete. The working product name is Stewardence; existing runtime identifiers remain compatible with the original AgentLedger baseline.
**Production authority:** The owner-approved Railway amendment supersedes SPEC v1.8 self-hosting, Docker Compose edge, Caddy, `flock`, and home-network production material where they conflict.

## Production topology

```text
Railway project: stewardence-production

public Internet
      |
      v
web — Django + Gunicorn — only public application domain
  |                 \
  | private DB       \ authorized short-lived report GET
  v                   v
PostgreSQL         private reports bucket
  ^                   ^
  | private DB        | upload generated PDF
worker ----------------
  |
  | validated structured payload over Railway private networking
  v
renderer — isolated PDF service — no public domain and no useful app secrets
```

Do not deploy Caddy, Redis, Celery, RabbitMQ, Kafka, Kubernetes, Elasticsearch, a Node backend, or a React SPA. Production must not depend on the founder's computer, WSL2, home router, home Internet, or presence.

## Current Railway documentation findings

Verified against official Railway documentation on 2026-09-04:

1. **Config as Code conflict:** Railway documents `railway.toml`/`railway.json` Config as Code as deprecated. New services cannot opt in, and existing use has a 2026-12-01 cutoff. Railway directs new projects to Infrastructure as Code under `.railway/railway.ts`. The handoff's requested `railway/web.toml`, `worker.toml`, and `renderer.toml` therefore cannot silently remain the executable deployment mechanism. Phase 1 must present and record a controlled amendment before selecting `.railway/railway.ts` or bounded dashboard configuration.
2. **Private service networking:** Each service receives a `<service>.railway.internal` name and private traffic stays inside its environment. Use the actual service name and port. Private networking is a runtime facility, not a build-time facility.
3. **Outbound traffic remains possible:** A service without a public domain can still initiate Internet traffic. Renderer isolation therefore requires request abortion, JavaScript/service-worker denial, fixed templates, escaped data, and absence of secrets; private networking alone is insufficient.
4. **Deployment healthchecks are not continuous monitoring:** Railway queries the configured path while activating a deployment. `/readyz` remains the deployment gate, but a successful activation check must not be reported as ongoing availability proof. Railway requests use `healthcheck.railway.app`, which must be handled safely by host validation.
5. **Buckets:** Railway Buckets are private, S3-compatible, and support presigned URLs. Public bucket mode is unavailable. Current documentation also lists API server-side-encryption controls, object versioning, object locks, and lifecycle rules as unsupported. Sensitive-report storage requires a documented owner-approved disposition before customer data.
6. **Backups:** Current Railway guidance distinguishes volume backups, PITR, and portable logical dumps. The production plan uses scheduled volume backups, PITR if available for the selected service/plan, and encrypted off-platform logical dumps with a real restore drill.

## Deployment prerequisites

All must be true before Railway project creation:

- Phase 23 automated and local integration gates pass on the candidate commit.
- A private GitHub repository contains the candidate; `main` force-push protection is enabled.
- No secret is present in Git history, the lockfile is current, and candidate images/dependencies are reproducible.
- Migrations follow expand/contract compatibility so the prior application release can run against the new schema.
- The database-role provisioning procedure and bounded owner-credential migration procedure are reviewed.
- The object-storage security disposition is approved.
- Release evidence has named owners and storage locations.

## Project and service creation

1. Create one Railway project named **Stewardence Production** and a production environment.
2. Add Railway PostgreSQL without a public TCP proxy.
3. Add the private `reports` Storage Bucket in the intended region; bucket region cannot be changed later.
4. Add `web`, `worker`, and `renderer` from the private GitHub source.
5. Generate a Railway public domain only for `web`.
6. Confirm `worker`, `renderer`, and PostgreSQL have no public domain or public TCP proxy.
7. Confirm private DNS names and actual internal ports from the deployed environment; do not guess them.

## Database roles and migrations

Provision separate credentials:

- `agentledger_owner`: provisioning and migrations only; never injected into a long-running service.
- `agentledger_app`: web runtime; NOSUPERUSER, NOBYPASSRLS, non-owner of tenant tables.
- `agentledger_worker`: worker runtime; NOSUPERUSER, NOBYPASSRLS, non-owner of tenant business tables.

The reviewed provisioner is `scripts/provision_database_roles.py`. It requires `DATABASE_ADMIN_URL` plus `AGENTLEDGER_OWNER_DB_PASSWORD`, `AGENTLEDGER_APP_DB_PASSWORD`, and `AGENTLEDGER_WORKER_DB_PASSWORD` from the deployment secret plane. It validates password length, creates or hardens the three fixed role names, and does not print credential values. The administrator connection is a bounded bootstrap authority, not a runtime variable.

Local and CI isolation verification runs through `scripts/test.ps1`, which delegates to `scripts/verify_rls.py`. That verifier generates high-entropy role passwords in memory, rotates the isolated test roles, applies migrations, and runs Django tests through distinct owner, app, and worker connections. Those ephemeral credentials are neither written to disk nor suitable for production.

The web receives only the app runtime connection. The worker receives only the worker runtime connection. Use a bounded release job or explicit founder-controlled release operation for owner-role migrations. A Railway pre-deploy command runs with the service's variables, so it must not be placed on a normal service if doing so would require permanently giving that service the owner credential.

Before migration:

- Acquire the chosen release lock.
- Record current commit/deployment ID, migration head, and dependency-lock hash.
- Capture and validate the pre-deploy logical backup.
- Review the migration plan for expand/contract compatibility.

If new application health fails after a forward-compatible migration, roll back the application release. Do not automatically restore the database. Database recovery requires evidence of data/schema corruption and explicit owner approval.

## Service contracts

### web

- Django + Gunicorn, binding to `0.0.0.0` and Railway's injected `PORT`.
- Only service with public networking.
- `/readyz` is the Railway deployment healthcheck.
- Runtime role: `agentledger_app` only.
- Bucket access only as needed to authorize and issue short-lived presigned GETs or proxy downloads.
- Explicit production host and CSRF-origin lists; no wildcard hosts.

### worker

- Start contract: `python manage.py run_worker` once implemented.
- No public domain.
- Runtime role: `agentledger_worker` only.
- Private PostgreSQL connectivity.
- Calls the renderer by its verified private DNS name.
- Uploads renderer-returned PDF bytes to the reports bucket and persists metadata.

### renderer

- Separate image and service; no public domain.
- Private HTTP application port only.
- Receives validated report payloads, not arbitrary HTML.
- Returns PDF bytes/result to worker; receives no bucket credentials under the preferred flow.
- Receives no database URL, Django secret, OAuth credential, or KEK.
- Runs non-root sandboxed Chromium with JavaScript disabled, service workers blocked, all browser requests aborted, fixed templates, escaped strings, fixed output handling, and resource/time/size limits.

### PostgreSQL

- Private connectivity only.
- Owner/app/worker credentials are distinct.
- RLS is enabled and forced on every tenant business table.
- Scheduled volume backups and approved PITR configuration are enabled before customer data.

### reports bucket

- Private bucket only.
- Worker writes; web reads only as required for authorized delivery; renderer has no credentials in the preferred flow.
- Object key: `organizations/<organization_uuid>/assessments/<assessment_uuid>/reports/<report_uuid>.pdf`.
- Database metadata: key, content type, SHA-256, size, report ID, created time, snapshot ID.
- A short-lived presigned GET may be generated only after authentication, membership validation, RLS, and report ownership checks.

## Variables and secrets

Expected variable names are documented in `.env.example` during Phase 1, with no values. Production values live in Railway's secret/configuration plane.

Required categories include Django settings module and secret key, explicit hosts and trusted origins, base URL, app/worker database connections, renderer private URL, and only the bucket credentials each service requires. Never copy production secrets into repository `.env` files or diagnostic output.

## Backups and restore proof

Before any customer data:

1. Enable scheduled Railway volume backups with documented retention.
2. Enable and verify PITR if available and approved; record the actual recoverable time window.
3. Create a PostgreSQL custom-format logical dump.
4. Encrypt and store a copy outside the live Railway database/project failure domain.
5. Restore into a clean temporary database.
6. Run migrations/schema checks, row counts, tenant-isolation fixtures, and an application smoke test against the restored copy.
7. Record the dump hash, encryption method/key custody (without secret material), restore target, commands/procedure, results, date, and reviewer.

A successful dump or archive listing is not a verified restore.

## Production smoke test

From a network unrelated to development, verify HTTPS, login, valid/invalid workspace activation, manual inventory, CSV staging/correction/confirmation, deterministic assessment and “why,” ROI arithmetic, custom rule testing, browser report, PDF generation, authenticated report download, logout/login, historical assessment retrieval, and cross-tenant denials.

Record the Railway deployment IDs, commit, migration head, lock hash, hostname, date, tester, results, and evidence links. Attach the approved custom domain only after the Railway domain passes. No prospect outreach uses a local address.

## Rollback and recovery

- Application regression with compatible schema: redeploy the previous known-good release; retain the database.
- Migration failure before activation: deployment remains blocked; investigate without exposing the failed release.
- Proven data corruption: stop affected writes, preserve evidence, obtain explicit owner approval, restore to a separate target/PITR sibling, validate, then perform a controlled cutover.
- Never treat application rollback as authority for database restore.

## Production stop gate

Deployment is not verified until the external-network smoke test, restricted-role tenant checks, renderer boundary checks, authorized report download, scheduled backups, and a clean restore drill all pass. At MVP acceptance, record the release and stop product-feature development.
