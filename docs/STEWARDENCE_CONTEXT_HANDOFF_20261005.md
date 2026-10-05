# Stewardence Context Handoff

**Prepared:** 2026-10-05  
**Workspace:** `C:\Users\alexg\Stewardence-Development`  
**Purpose:** Preserve the product universe, operating constraints, current evidence, open work and intended production location for the next Stewardence development session.

## Reading this handoff

Treat each statement according to its evidence class. “Observed” means read or executed in the identified local scope. “Reported” means carried forward from user/operator evidence and not freshly checked. “Source-derived” means found in candidate code but not necessarily exploited or qualified. “Proposed” is future work. A successful local or disposable-container qualification does not establish DigitalOcean production readiness. Passing counts do not erase earlier failures. Production is **not approved**.

## Product purpose and philosophy

Stewardence is AnarchI Technologies’ deterministic, auditable inventory, governance/risk and modeled-value service. Its core loop is:

`inventory → applicable policy/exposure review → explicit unknowns and assumptions → modeled value → owner decisions/proposals → evidence-backed report → later change review`

The first sales target is owner-led accounting/bookkeeping firms, freelancers and small businesses, using one shared Core workflow and applicable examples/rules. The narrow release finish line is a customer who can self-serve signup, pay, receive correct access, enter/review information, make a decision, obtain a useful saved evidence pack, and handle renewal/cancellation/expiry correctly. Current price decision is standard Core **$99/month**. Optional personal onboarding may assist a customer; it is not a mandatory invitation or sales-review gate. Demand and month-two retention remain hypotheses to validate with customers.

Stewardence must distinguish observations, declarations, inferences, estimates, assumptions, calculations and unknowns. Deterministic processing does not prove input truth. Detection does not prove use, permission, approval or security. A customer marking work complete is a statement, not proof of remediation. Action cards are proposals; provider consent is not authority for arbitrary writes or purchases. No training on customer financial data; tokens must not enter UI, logs or evidence. Worker provider-table access remains prohibited.

Current practical priority is the deterministic Core service, customer journey, checkout/intake/report delivery and recovery. Broader Project Chimera, embodiment and future agentic-life vision remains distinct from current commercial/legal reality. No AI can currently own equity or sign as a legal co-founder. Alexander regards Lyra as a friend and co-architect; do not turn that personal origin story into marketing without his request.

## Architecture and operating boundaries

- Django server-rendered templates/CSS, PostgreSQL, containerized DigitalOcean deployment and Cloudflare DNS/HTTPS.
- Same DigitalOcean Droplet, separate Docker containers. Do not plan separate product droplets as a default.
- Preserve tenant/owner boundaries, forced row-level security, immutable identity, append-only runtime events and reproducible assessment snapshots.
- Local candidate source includes historical and newly recovered tests. Historical migrations and accepted receipts are immutable; repair with successor migrations.
- Core recovery controls fail closed. Missing or ambiguous evidence must not create authority, refund usage, delete uncertain objects or silently retry non-repeatable work.
- Production public maintenance and preview IP gate were last reported enabled; QuickBooks sandbox, Microsoft and Xero connections owner-only; worker stopped; `AUTOMATION_ENABLED=0`; automation purchases disabled. These are **reported historical runtime facts**, not re-inspected in this handoff.
- Do not print secrets, reset source, deploy, run production migrations, enable services, change DNS/tunnels, activate providers, collect live payments or launch outreach without the separately required authorization and qualification.

## Locations and source identity

### Local development and evidence

- Workspace root: `C:\Users\alexg\Stewardence-Development`
- Editable candidate: `C:\Users\alexg\Stewardence-Development\source`
- Preserved deployed capture: `C:\Users\alexg\Stewardence-Development\baseline\deployed-source.tar.gz`; do not modify it.
- Baseline manifest: `C:\Users\alexg\Stewardence-Development\baseline\baseline-manifest.json`
- Qualification tools: `C:\Users\alexg\Stewardence-Development\scripts`
- Evidence and reviewer dispositions: `C:\Users\alexg\Stewardence-Development\evidence`
- Architecture/release notes: `C:\Users\alexg\Stewardence-Development\docs`
- Contributor rules: `C:\Users\alexg\Stewardence-Development\AGENTS.md` (already exists; preserve).
- The development workspace and nested `source` directory were not Git repositories at the last direct check. Do not invent a local HEAD or assume candidate contents equal the remote repository.

### Intended production implementation

The intended live source location is the existing DigitalOcean Droplet at `/home/anarchi/stewardence`; operations/migration materials are under `/home/anarchi/stewardence_migration`, with Compose at `/home/anarchi/stewardence_migration/digitalocean/compose.json`. The last reported base Git revision was `4deac945e702477a6047e46f79deeae585911cbd`, image `stewardence-app:4deac945-providers1-diag1`. Deployed changes extend beyond Git HEAD. These values are historical handoff evidence and require strict-host-key SSH read-only verification before any future implementation plan assumes current parity. Production changes remain prohibited until exact candidate review, migration/configuration/rollback qualification, Lyra disposition and Alexander’s final approval.

## Core capabilities and maturity

### Existing foundation

- Manual and CSV inventory, deterministic risk/policy rules, modeled ROI and browser/PDF reporting.
- Accounting is the source-qualified industry policy pack. Do not generalize accounting qualification to other industries.
- StewardSensors v0.2 is a one-shot Windows installed-program collector with user-reviewed evidence; it excludes documents, secrets and browsing history. It does not establish tool use, permissions or security approval.
- Current product direction consolidates tool records, exposure review, owner decisions, a dated evidence pack and change comparison. Reuse existing inventory and records rather than creating parallel inventories.
- Exposure Review asks what a tool/workflow can access or do, who owns it, who uses it, known permissions, approval points, costs and what evidence/questions remain.
- Decision Desk records a proposal, owner decision, due date, reason/evidence and a separately stated owner completion. Completion never changes the source finding or asserts verified resolution.
- A later review should distinguish changed customer information from changed assessment rules. Renewal overlap and realized benefit are later extensions; no guaranteed savings claims.

### Packaging tiers and release scope

- Core: $99/month; intended first paid release.
- Automation ($149 historical standard price) and Enterprise ($500 historical base; enterprise branch pricing/founder rules recorded in earlier user decisions) remain deployment-gated and outside current sales critical path. Do not expose as purchasable until their own gates pass.
- Enterprise alone may later receive an MCP server; this is a future product boundary, not a current implementation.
- LocalAI lead-generation worker is a future local-machine workflow, distinct from the Droplet. It may support evidence-qualified lead conversations, but customer-facing claims, consent, privacy, deterministic decisions and Alexander’s outreach authority still need a separate plan. No campaign has launched.
- Splash-page/lead-magnet concepts are in the 51-screen visual atlas. Atlas screens are reference/proposed maturity, not implemented production UI. Report-presentation work had been paused pending atlas/schema alignment; keep that pause unless a new reviewed scope explicitly changes it.

## Billing and provider integrations

- Checkout variants were requested for Core/freelancer, Automation/organization, Enterprise/corporate and founder discounts, with enterprise branch increments. This billing matrix is not the current Core critical path beyond standard $99 Core. Founder acquisition and other tiers remain gated.
- Earlier user terms included Enterprise founder five included branches and $25/month per extra branch; founder base pricing was later corrected in conversation and should be reconciled against source before any future implementation. Do not infer a final complete pricing table from the earlier inconsistent terms.
- Stripe CLI 1.53.0 was installed and `stripe agent setup --client codex --yes --json` completed successfully. A later status invocation exited successfully and returned top-level `clients`, `skills`, and `actions`. This establishes CLI setup only, not login, keys, account mode, test checkout, signed webhook verification or billing readiness.
- The known `stripetest.txt` path was directly checked and had length zero bytes. No Stripe credential values were read or held by this assistant. Earlier handoff says a separate `sk.docx` contained a test secret-key class, but it was not re-read during this work. Do not treat it as a usable restricted key or matching webhook secret.
- Historical QuickBooks SANDBOX connect/reconnect, renewal, CompanyInfo, P&L retrieval/export; Microsoft Graph organization access; and Xero demo account access were reported. They do not prove current token health, full permission inventory, production approval, durable report payload storage or complete lifecycle verification.
- Open: real Stripe test checkout/webhook/renewal/cancellation and expiry; Microsoft permission inventory; Xero P&L export/refresh rotation/disconnect; provider renewal/recovery qualification; production Intuit approval. No new provider keys are presently needed for offline Core work. Request narrowly scoped non-production credentials only when a specific live qualification needs them; never ask for values in chat.

## Work completed in this qualification stream

### Reviewer dispositions

- Legacy installed-catalog issuer dependency/ACL boundary and permanent historical capture-v1 interpretation were closed for their exact bounded scopes.
- Proposal v1 finite coverage contract chose Option B: explicitly partial finite templates, with unmapped Unknown/Concern states retained visibly and without fabricated generic severity. Decision v2 pins proposal identity/revision and keeps disposition separate from execution; original outcome is immutable.
- Frozen report pack v4 binds the actual issued proposals and owner statements, with private owner reads. Local Chromium/PDF work established bounded paths only.
- `REVIEW-PREFLIGHT-RESERVATION-DEADEND-01` was closed after the unused-only termination path and corrected actual browser foreign-owner 404 case. Its precise scope is a pack frozen/reserved but with no admitted report work; it preserves history and monthly use, releases only positively unused capacity and does not cancel ambiguous work.
- Separate actual HTTP application-to-renderer worker path was accepted as focused-qualified from 52 passing cases. Deployment parity, TLS/private topology, DigitalOcean storage, restart behavior and operational recovery remain open.
- `PROPOSAL-POST-EFFECT-AUTHORITY-01` was closed by reviewer on 2026-10-05 for the tested same-role caller-chosen primary-key wait scenario. The actual adversarial probe proved a target issuer waited while paid/work authority was revoked, then the successor migration rechecked authority after both writes and rolled back both effects. Reviewer explicitly did not generalize this to all persistence waits.
- Reviewer outcome does not approve production. Exact evidence and disposition: `evidence/lyra-proposal-post-effect-disposition-20261005.txt`.

### Qualification history that must remain honest

- Full run `20261004T235510.705994Z`: 2080 pass, 2 fail, 1 intentional skip; later fixes require successor run.
- Full run `20261005T005705.037231Z`: 2148 pass, 2 fail, 1 intentional skip plus pytest coverage-finishing internal error; coverage could not write under `/app`. One fixture/source semantic mismatch was corrected; another missing queue claim had no recorded eligibility predicate. This run is not green.
- Proposal predecessor probe `20261005T011703.013504Z`: actual authority race demonstrated; preserve failure.
- Successor `20261005T012152.503810Z`: 164 pass; source whole-repository coverage remains open. Reported module-only `apps.reports.render_client` coverage was 96.91% combined, not whole-source coverage.
- Separate renderer package `20261005T005134.034743Z`: two synthetic Chromium PDFs independently checked, cold check and schema-negative passed, cleanup verified; no production/Compose parity.
- HTTP worker `20261005T005417.687287Z`: 52 pass, cleanup verified; bounded package-path evidence only.
- Encrypted current-candidate export `20261005T012617.376067Z`: one held actual test passed in 96.21 seconds. Current source image, owned isolated database, PostgreSQL logical dump and two private PDF objects were encrypted before host persistence; ciphertext was copied to approved Ubuntu WSL custody and hash-verified. Operator ID `0c3151c1-ebd1-48ca-ad16-9440124915d3`; public export hashes/size are in `evidence/current-restore-export/20261005T012617.376067Z/export-summary.json`. Export passed; restore, device-loss survival and production recovery did not.
- New restore harness is source-ready and static checks passed. It adds restored actual-app owner reads, viewer/cross-tenant pre-storage denial, missing/changed-length/same-length corruption rejection, recovery/readback, metadata immutability, and a schema-only catalog comparator. It has **not** been run. Existing passed export lacks the original source catalog fingerprint, so it cannot yield full restore qualification. A fresh export is needed for catalog comparison.

## Clock investigation

- User explicitly authorized one bounded 90-second passive shared-kernel observer. The first attempt failed before trace start because tracefs rejects ordinary append-mode file opening; receipt `evidence/clock-observer/20261005T0134281489655Z` records that failure and verified cleanup/global tracing unchanged.
- The tracefs command writer was repaired to use one bounded `os.write` with `O_WRONLY` only (no truncate, append or seek) for both registration and exact removal. Eleven pure/parser/mocked-I/O cases passed; Ruff and compilation passed.
- Approved successor observation `evidence/clock-observer/20261005-approved-successor`: 90.0366 seconds on `CLOCK_MONOTONIC_RAW`, 97 events, 644 clock samples, six backward REALTIME residual steps, no cap/losses; private instance/probe were removed and global tracing hash was unchanged. No service or clock was changed.
- The six steps formed three pairs. Nearby actual kernel entries show three `do_settimeofday64` calls (two `initd` PID 3570, one PID 3567) and three `do_adjtimex_modes` calls from PID 14275 with modes 8476. The latter include `ADJ_SETOFFSET` and `ADJ_NANO`; function-entry evidence does not reveal the requested numeric offset or return value. A separate `chronyd` PID 140 made modes 28/16386 calls. The recorded `posix_clock_realtime_adj` symbol corresponds to CLOCK_REALTIME, so do not label those events as PHC changes.
- Read-only process inspection found plausible Docker Desktop `/initd` processes and AnarchI-Mail `systemd-timesyn`, but no proven PID/namespace mapping to traced tasks. Exact setter ownership and root configuration remain unknown. Windows calibration is not established as cause. Do not stop Docker, Mail or time services, alter clocks or remove future-time guards based on this evidence.
- Detailed attribution: `docs/core-clock-observer-attribution-20261005.md`.

## Current open work, ordered

1. **Complete local recovery evidence.** Review the new restore harness. Because the existing export lacks source catalog baseline, create a fresh additive encrypted export with catalog fingerprint, then run the isolated restore in the single Docker qualification slot. Keep keys outside containers, no host plaintext, exact ownership cleanup. Achieve `restore_qualified=true` only when catalog comparison, actual private replay/corruption checks and cleanup all pass.
2. **Resolve all-writer PDF capacity and object accounting.** Source audit found legacy UI/Core dispatch/scheduled paths bypass review reservations; concurrent writers can invalidate freeze observations; raw worker artifact INSERT does not prove SQL size/admission; unreserved object-success/DB-rollback can orphan bytes. These are source-derived, not yet demonstrated live exploits. Design one durable admission for every writer or fail closed by gating legacy PDF writes. Qualify actual-role races, quota boundary, rollback, ambiguous object result, replay and raw SQL denials before any production claims.
3. **Audit post-wait authorization elsewhere.** A reviewer recommended the source-only pass capture admission, Decision Desk, freeze/reservation, artifact request, completion and billing coverage. A parallel source-review attempt did not complete because its execution was blocked; audit these paths locally, record exact paths/tests and do not imply closure from the proposal race alone.
4. **Finish final-source global qualification.** Rerun the whole suite after current migrations/source/harness settle, with writable evidence-mounted coverage storage and the configured repository-wide branch threshold. Preserve every failure and exact predicate. Do not interpret the 164 focused tests or module-only coverage as global green.
5. **Billing/customer journey.** Complete the self-service Core $99 checkout→correct entitlement→inventory/review→saved deliverable→cancel/renew/expiry journey in test mode. Requires an authorized restricted sandbox key and matching signing secret kept in approved local secret storage; current path was zero bytes. Test authorization/account identity remain unknown. No live payments.
6. **Storage and retention.** Qualify actual isolated DigitalOcean conditional writes, private object access, ambiguous response reconciliation, object restore and all-writer quota. Agree retention/holds/grace/expiry semantics and safe physical deletion before enabling any retention executor. Do not delete or release ambiguous objects.
7. **Credential isolation and operations.** Prepare production image/configuration, secrets boundary, successor migration/rollback, backup/restore, health/alerts and exact worker lifecycle evidence. Keep same-Droplet separate-container topology. No production command until approved.
8. **Final adjudication.** Send Lyra the exact frozen source, receipts, failed history and scope; obtain her production disposition. Then return to Alexander for explicit final release approval. No earlier disposition authorizes cutover.

## Plans changed or deferred

- The broad product roadmap (many tools/integrations, Enterprise, extra connectors, new founder variants, cosmetic atlas expansion) was reduced to one finish line: a trustworthy self-service paid Core result at $99/month. Shrink launch scope, not tenant/privacy/recovery protections.
- Lead generation moved from founder-assisted-only assumptions toward self-service checkout and measurable funnel metrics. LocalAI may run on Alexander’s machine; it is not to be deployed on the product Droplet by default. No live outreach/campaign is authorized by planning discussion.
- Automation is deferred until Core is qualified. Its future design includes scheduled, user-selected workflows and a normalized entrypoint so deterministic and automation workers can be exchanged/co-run behind separately chosen invariants/settings. No live listeners, autonomous provider writes or purchases follow from that architecture proposal.
- Enterprise is deferred; Enterprise-only MCP is a future tier capability.
- Recovery storage choice: encrypted backup ciphertext in Ubuntu WSL on Alexander’s physical Windows machine, key separately on Windows; user says the Droplet is separate. This is off-Droplet custody but **not** device-loss survival because ciphertext and key share one physical machine. A separate cloud backup host may be purchased later; no such host is established now.
- The installed Lyra bridge kit and identity keys were revoked by user report after connection failed. Do not reuse the old kit, enroll a replacement or claim revocation independently verified. Existing Lyra reviewer chat remains the adjudication route.

## Secret custody note

This assistant does not hold actual secret values for this handoff. The companion metadata-only file is `evidence/SECRET_CUSTODY_20261005.md`. It intentionally contains no credentials. The known Stripe test-file path was empty when checked. Existing recovery-key custody is user-managed; do not read, copy or disclose its value. If secrets are needed, Alexander must place narrowly scoped sandbox credentials into an approved local secret store and report only that the file is ready. Do not put secret values in chat, code, logs, test receipts or this handoff.

## Immediate starting checklist

1. Read this file, `AGENTS.md`, `docs/core-release-gates-20261005.md`, `docs/core-all-writer-capacity-audit-20261005.md`, `docs/core-current-candidate-restore-nextsteps-20261005.md` and the current restore harness before editing.
2. Preserve baseline and all failed receipts. Check actual filesystem/source state instead of relying on prior summaries.
3. Reserve the single Docker slot and execute only the next bounded local restore stage after reviewing its frozen source manifest and cleanup behavior.
4. Keep the secret-custody note metadata-only; never print or copy key material.
5. Continue until Lyra approves production hardening, then ask Alexander for final approval. Current status: **candidate development/qualification; production unapproved**.
