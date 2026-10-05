# Stewardence Founder-Assisted Customer Pilot Runbook

**Activation gate:** Do not use this runbook with customer data until the Sellable MVP release gate, Railway production smoke test, report-storage disposition, and backup restore drill are verified.

## Offer

Sell the result as an **AI Risk & ROI Review powered by Stewardence**, not an abstract governance platform or continuous-monitoring service.

The initial consistent price experiment is **$350** for setup help, inventory assistance, risk review, ROI review, professional PDF, and founder walkthrough. Payment is validation; do not call it a donation or default to a free beta.

Do not claim compliance certification, continuous monitoring, real-time detection, automated blocking, connector-based discovery, or third-party enforcement.

## Pilot qualification

A strong pilot is a 2–30 person, owner-led bookkeeping/accounting firm that uses several AI/software tools, handles client or financial data, lacks a strong centralized inventory, includes a decision maker, will share enough truthful data, and can pay.

Before offering the pilot, learn:

1. Which AI/software tools are used today and whether a written inventory exists.
2. Whether staff subscribe independently.
3. Whether tools touch payroll, tax, client documents, email, bookkeeping records, or banking.
4. Who decides whether use is safe enough and where human approval is required.
5. How the firm judges whether subscriptions justify their cost.
6. What the firm would do with an inventory/risk/ROI report.
7. Whether this is something the firm will pay to review.

Record the prospect's exact language. Do not defend the product during discovery.

## Payment and trusted provisioning

After the customer accepts and pays:

1. Record price offered, price paid, payment method, date, organization, and buyer.
2. Create the user and organization through the trusted invite-only provisioning path.
3. Assign the minimum required organization role.
4. Send secure login instructions through an approved channel; never send passwords or secrets in ordinary notes.
5. Schedule a 30–45 minute onboarding session.
6. Confirm the customer understands the assessment is advisory and based on supplied evidence.

Public self-service signup and guided workspace setup are required. Founder-assisted onboarding remains available; automated subscription billing remains outside MVP.

## Intake

For each tool collect, in plain language:

- Software/AI name and vendor
- Department and business owner
- Purpose, users/seats, monthly subscription cost, and implementation cost if relevant
- Connected systems
- Data categories: public, internal, client, financial, banking, payroll, tax, health, legal, credentials, and PII
- What it can read, change, send externally, communicate, or do autonomously
- Whether a person approves actions
- Operational status and evidence/source
- Retention, model-training behavior, and vendor-review status, including “unknown” when not known
- Hours saved, loaded labor cost, attributable revenue, avoided cost, and the provenance of each ROI assumption

Do not ask customers to interpret raw OAuth scopes. Translate capabilities into business questions.

## Assessment session

1. Inventory all known tools.
2. Preserve unknown products as unknown; do not force a catalog match.
3. Complete sensitive-data, connected-system, permission, autonomy, and approval facts.
4. Enter costs, hours saved, labor assumptions, attributable revenue, and avoided cost with provenance.
5. Run the deterministic assessment.
6. Review every finding and score explanation with the customer.
7. Correct factual input errors. Do not edit a rule merely because a customer dislikes its result.
8. If a rule appears noisy or wrong, record the issue for later investigation/versioning.
9. Rerun after factual corrections and generate the final immutable assessment and report.

## Report delivery

Walk through the executive summary, top three risks, spend, ROI, tools requiring review, human-approval gaps, and recommended actions.

For each material finding record one of:

- Useful
- Already knew
- Not relevant
- Incorrect
- Do not understand

Ask which finding surprised the customer, which is wrong, which is obvious but useful to document, which would cause a change, and who else should receive the report. Target at least 70% of material findings rated useful or valid.

Then ask: **If Stewardence stopped existing tomorrow, what part would you actually miss?** Record the answer without steering it.

Ask how quickly the information becomes outdated and what change—new tool, permissions, cost, or risk—would make the customer return. This is evidence for or against post-MVP monitoring; it is not permission to build it yet.

## Security and data handling

- Use only the production Railway environment after its release gates pass.
- Give each customer a separate organization and verify tenant context before every data operation.
- Never place customer data in the demo organization.
- Never move production data into development fixtures.
- Send reports only through the authenticated application or an authorized short-lived download.
- Do not email raw report objects or expose object keys as authorization.
- Keep credentials and sensitive evidence out of support notes and logs.
- Correct errors by creating accurate new assessments/reports; do not rewrite historical evidence.
- Follow the approved retention/deletion policy once established; do not invent one during onboarding.

## Founder-time and outcome ledger

Track prospecting, sales call, onboarding, data cleanup, assessment assistance, support, report walkthrough, and technical-fix time separately. Record prospects contacted, responses, calls, offers, acceptance, payment, activation, inventory completion, assessment completion, report generation, time to first useful assessment, finding usefulness, incorrect findings, referrals, and repeat use.

Track cash separately: revenue, Railway cost, domain, payment fees, other SaaS, and refunds.

Distinguish “the product worked” from “the founder manually rescued the workflow.” Repeated manual explanations are UX defects; repeated manual operations identify a possible post-validation automation target.

## Pilot completion

A pilot completes only when a real target customer has paid, used real data, received the final report and walkthrough, provided finding-level feedback, and had founder time/outcome recorded.

After customer one, fix only blockers to security, correctness, onboarding, assessment, reporting, payment, or customer use, plus major misunderstanding, clearly incorrect rules, or report defects. Return to selling; do not reopen broad feature development.
