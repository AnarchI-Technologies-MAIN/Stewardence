# Core worker release setup

The Core worker is a bounded, one-shot deterministic queue drain. It uses the
same candidate application image as the web service, the separately provisioned
`agentledger_worker` database role, the private renderer network and private
report storage. It does not receive Stripe, OAuth-provider or automation
credentials. `run_core_worker` refuses to start unless Core workflows are
explicitly enabled and `WORKER_DATABASE_URL` is configured.

## Candidate container contract

The prepared Compose overlay is
`deployment/digitalocean/core-worker.compose.yaml`; the timer drafts are under
`deployment/systemd/`. Install the overlay beside the existing `compose.json`,
and the unit files under `/etc/systemd/system/`, only after the candidate image
and database-role qualification are approved. Set `STEWARDENCE_CORE_IMAGE` to
the exact same immutable image as `web`. Production settings require
`WORKER_DATABASE_URL` to use `agentledger_worker` and target the same database
as `DATABASE_URL`. Mount a separate mode-0600 worker environment file containing
`DJANGO_SETTINGS_MODULE=agentledger.settings.production`, the worker role as both
`DATABASE_URL` and `WORKER_DATABASE_URL`, `CORE_WORKFLOWS_ENABLED=1`, and only
the renderer and private report-storage settings required by the report handler.
Keep `AUTOMATION_ENABLED=0` and omit Stripe and provider credentials.
The overlay keeps the existing event-driven `worker` behind a separate
`legacy-worker` profile so normal Compose startup cannot launch both workers.

Run `manage.py run_core_worker --worker-id stewardence-core-01 --max-jobs 10` as
a one-shot container with `restart: "no"`, no published ports, no writable host
mounts, a read-only root filesystem, bounded memory/PIDs, dropped capabilities,
and `no-new-privileges`. Attach only the database, renderer and required
object-storage egress networks. The web service remains unable to execute
scheduled work unless its own Core-workflow gate is deliberately enabled.

Use a systemd timer on the Droplet to start the one-shot container on a bounded
interval. Keep worker activation independently switchable from public web
traffic. The timer must not use Compose's `up` against the worker service,
because that would turn a bounded drain into a persistent service. Record every
run's exit state, processed count and recovery receipts; alerts must not include
tokens, report contents or provider payloads.

## Qualification gates

Before deployment, verify the worker database role against the production
schema: it can claim and transition admitted jobs, read only handler-required
tables, insert append-only receipts, and cannot read provider token tables or
write billing entitlement. Run the same immutable image and exact environment
shape in a disposable database. Prove real report rendering, private object
write/read, tenant isolation, pause behavior, retry review, SIGKILL recovery and
duplicate-run safety. Confirm the timer's timezone, interval, overlap lock,
failure alerts and rollback procedure.

The current Droplet manifest defines an event-driven `worker` using image
`stewardence-app:4deac945-qbo2`, while `web` uses
`stewardence-app:4deac945-providers1-diag1`. The worker container was absent at
inspection. Its separate `worker.env` is mode 0600, but does not currently set
`WORKER_DATABASE_URL` or `CORE_WORKFLOWS_ENABLED`; its database credential could
not be attributed to a named role from the manifest template. Do not start or
replace that service until the actual effective database role, image/source
parity and runtime gates are qualified.

## Current candidate evidence

The isolated billing/worker group passed 85 tests, including actual PostgreSQL
role tests and five process-kill/recovery stages. A separate end-to-end worker
test passed using the isolated HTTP renderer and private report storage. The
crash tests use an injected handler and do not qualify renderer behavior. These
are local candidate results; they do not qualify the Droplet's image, database
grants, object store or timer.
