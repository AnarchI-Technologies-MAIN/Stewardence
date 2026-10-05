# Stewardence development workspace

This workspace preserves the actual deployed worktree beyond Git HEAD before local development. Production lives on the existing DigitalOcean Droplet; no production source, migrations, services or ingress have been changed by these local scripts.

- `baseline/baseline-manifest.json`: captured revision, dirty status and SHA-256 inventory.
- `baseline/deployed-source.tar.gz`: immutable source capture; excluded secret-shaped files are listed in the manifest.
- `source/`: editable candidate source, including recovered qualification tests.
- `evidence/`: local build and database-role qualification output. Tests do not establish live provider health or production readiness.
- `docs/release-gates.md`: release sequence and evidence requirements.
- `scripts/qualify_local.py`: disposable internal Docker network and PostgreSQL database; no published database port or production credentials. Cleanup removes only resources created by the invocation.
- `C:/AnarchI-CLI-Toolbelt`: CLI inventory and Stewardence operation mapping. Presence, authentication and authorization are separate facts.

Run `py -3.14 scripts/qualify_local.py` from this workspace. Docker Desktop must be running. The build uses the project's frozen dependency lock and Python 3.14.7.

Enterprise remains design backlog. Core is the first sales release; Automation requires its own qualification. Provider previews retain owner and sandbox boundaries. A release requires a reviewable image, migration/rollback package and final cutover authorization.
