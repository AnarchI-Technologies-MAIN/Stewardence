# Atlas v3 update — approved transparent purple identity

All 51 design references now use the approved emblem family in shared brand placement and semantic page headers. See brand-semantic-layer.md and brand-asset-mappings.json. All availability, maturity, authority, evidence and billing boundaries from the repaired atlas remain in force. Historical logo-pause/exploration notes below are superseded by the approved direction; the production application remains unchanged.

# Stewardence implementation handoff · October 3, 2026 · atlas v2

This handoff reconciles all 51 intended designs. It is a presentation specification, not 51 operating pages, a public cutover, or production acceptance. Lyra inspected the supplied current qualification source and the 51 first-pass boards. Static review does not prove keyboard behavior, accessibility compliance, submissions, backend authority, or deployment behavior.

## Evidence and revision

Source is the selectively extracted stewardence_workspace_qualification.tar.gz package. Use `source-evidence.json` for its SHA-256 and each inspected source file fingerprint. Revision: **qbo3-workspace deployed candidate, based on server commit 4deac945e702477a6047e46f79deeae585911cbd plus qualified changes**. The base commit alone is not reproducible deployed source. No environment files, secrets, provider IDs or credentials were copied into deliverables.

195 tests and deployment PASS were reported by Alexander; this chat did not rerun them. Connect, connected display, fresh-token check, disconnect and reconnect were reported observed. Renewal remains unobserved. HTTPS, owner preview, public maintenance gate, stopped worker and disabled Automation purchases are reported runtime facts, not inferred from settings. No live infrastructure action was taken.

## Implementation increments and ownership

1. Shared tokens, navigation, state labels, forms, tables and evidence disclosure components.
2. Existing login, ordinary workspace picker and owner QuickBooks sandbox branch.
3. Existing inventory/import/policy/assessment/report/billing templates; resolve semantics before substituting unknown-value presentation.
4. Financial, evidence, ROI and action workflows only after their data and authority contracts exist.
5. Lead receipt/routing and internal operator review, then proposed funnels.

Before any application patch, agree on the candidate/package fingerprint and ownership of each shared template/CSS file with engineering. This delivery edits atlas files only. Engineering owns behavior, billing, tenancy, permissions, integration lifecycle, background jobs and deployment. Preserve Django inheritance, named URLs, CSRF, form method/name/action fields, validation, pagination and server checks. Do not introduce frontend frameworks, authentication, CDNs, analytics, font services or scripts. Review prototypes use local static HTML/CSS and supplied PNG assets only.

## Reusable design and template mapping

| Component proposal | Existing surface / contract | Presentation implementation |
|---|---|---|
| Visual tokens | static/agentledger.css | Namespace spacing (4/8/12/16/24/32/48), Segoe UI/system fonts, navy #0a1b2e, blue #1d55cf, slate #52647c, white surfaces, #d5deea borders. Review reference CSS is design-system.css; do not blindly overwrite application CSS. |
| Public header / workspace shell | templates/base.html; public_content/content blocks | Reusable include proposals, narrow205px navigation, actual active route; public maintenance availability respected. New nav targets wait for routes. |
| Workspace context | tenancy context; ordinary and sandbox choices | Workspace/role separate from subscription and provider eligibility. No customer internal-lead nav. |
| Source/result status | actual context per view | Text plus semantic cue, no color-only meaning. Separate observation, declaration, estimate, inference, verified check and unknown. |
| Form field/error row | Django bound form fields | Keep label IDs, help/error association, non_field_errors and values; 44px target. Choice fields stay native selects/checkboxes, not arbitrary text. |
| Data table | inventory/import lists | Semantic headers/caption; small-screen scroll region or stacked readable rows; preserve pagination/query parameters. |
| Evidence disclosure | snapshot/report provenance | details/summary; source, observation/receipt time, rule/model version, limits, exact receipts only when provided. |
| Action scope | existing mutations/proposed workflows | Target, effects, role, approval and execution separately. Disabled review controls never imply backend enforcement. |
| SignalMeter | proposed aggregate context | Evidence/task first; financial detail collapsed on mobile. No global health/confidence score. |

Exact template URLs and field references are in `template-mappings.json`. No new include pathname is claimed to exist. Introduce reusable includes only in a coordinated presentation patch.

## QuickBooks source-backed contract

`apps/integrations/quickbooks_services.py:sandbox_workspace_choices()` requires active authenticated allowlisted user and feature enablement; returns owned workspace choices. `authority()` checks owner role and selected UUID in its transaction. `owned()` additionally scopes management to connecting user. `quickbooks_views.py:connect()` handles POST action=select_workspace and exactly one workspace_id, sets active workspace and clears the nonce. Picker is a branch of templates/integrations/quickbooks.html, not a new route. Normal picker retains POST organizations:workspace-activate/organization_id. BillingEntitlementMiddleware exempts this sandbox prefix only; no ordinary entitlement bypass.

Persistent states in QuickBooksConnection.Status: disconnected, connected, reconnect, revoking (Disconnect pending). Current routes in apps/integrations/urls.py: quickbooks-connect, -callback, -disconnect, -disconnected, -refresh. UI conditions unavailable/selection-required/error are responses or result flags, not extra persisted statuses. Authorization in progress is a transient presentation proposal. Do not draw a linear lifecycle stepper.

| Condition | Source / support | User action / recovery |
|---|---|---|
| Unavailable to account | authority/choices PermissionDenied; disabled boundary404 | No connect; explain only in safely reachable destination; no purchase unlock |
| Workspace selection required | connect workspace_required branch | POST owned workspace; invalid/duplicate selection rejected |
| Eligible disconnected | connection_status() no object or DISCONNECTED | Connect sandbox company; POST and CSRF |
| Authorization in progress | begin redirects to provider; no HTML callback | Brief submitting/provider-handoff cue proposed; no durable progress record |
| Connected | CONNECTED; latest runtime reported | Check token validity / disconnect; no new connection before disconnect |
| Reconnect required | refresh expiry/provider rejection commits RECONNECT | Disconnect, then connect. Direct reauthorization while non-disconnected conflicts with begin() |
| Disconnect pending | disconnect commits REVOKING before provider call | Access paused; explicit retry. Do not claim revocation complete |
| Disconnected | successful disconnect removes stored credentials | Connect again if eligible; record reported lifecycle success separately |
| Operation failed | connection_failed / refresh_failed / unavailable destination flags | Safe error, preserve state, retry or disconnect/reconnect as appropriate |

`refresh()` may return still_valid when fresh without making the renewal call; “Token validity checked” is not renewal proof. Current template does not distinguish refreshed from still_valid; a richer result requires a view-context contract. Never expose tokens, authorization codes or company identifiers. `clean_redirect()` and callback boundary keep empty bodies, no-store and callback privacy behavior. Do not design callback HTML. Current integration middleware sets no-referrer on that prefix; preserve it pending security-owner review, but do not apply it globally to ordinary form pages. Ordinary same-origin CSRF referrer requirements remain intact.

## SignalMeter input definitions

| Signal | Input/rule proposal | Required limits |
|---|---|---|
| Evidence coverage | Included source/device set versus explicit required source set | Denominator absent → Partial/unknown, no percentage |
| Software observations | Distinct source-supported observations after versioned reconciliation | Separate installations, grants and declarations; not active AI use |
| Connection health | Account eligibility + current connection state | Not collection completeness or token-renewal proof |
| Last manual import | Durable receipt/finalization event + source type/time | Observation time separate from receipt; staging versus imported distinct |
| Last successful automatic collection | Qualified success event, target/scope/source/time | None recorded while worker/pipeline not operating |
| Last authorized automatic action | Actual executed event with approving authority and target | None recorded while execution is absent; approval not execution |
| Gross total in | Sum normalized positive cash receipts in selected period/currency/basis | Transfers/refunds/reversals explicit; not necessarily revenue |
| Expenses to date | Sum reviewed expense classifications with exclusions visible | Not every cash outflow is expense; no mixed currencies/periods |
| Expenditure sinks | Distinct normalized vendor/payee IDs, categories, commitments | Separate overlapping counts; unclassified population shown |
| Observed discrepancies | Versioned comparison candidates with input references | Unresolved mismatch is not fraud/error proof; denominator defined if rate used |
| Calculated ROI | Versioned model and admitted inputs | Missing → insufficient evidence, zero-cost undefined, negative outcomes retained, causation unestablished |

The financial scenario is synthetic September2026 USD cash-basis data. It is not live QuickBooks output. Financial metrics are not default mobile content ahead of evidence review.

## ROI reconciliation blocker

The package's apps/roi/forms.py:ROIForm.clean() requires Unknown numeric inputs to be zero. apps/roi/engine.py:Assumption.__post_init__() enforces the same rule; calculate_roi() uses those numbers. apps/inventory/views.py:inventory_roi_view() initializes unknowns as0. The legacy engine AL-ROI-1 accepts hours_saved_per_month, not separate baseline/current hours, and forbids negative input hours. The current report template also presents legacy ROI and describes all unavailable percentages as zero cost. This is a substantive mismatch with product requirements, not a CSS fix.

Engineering must define absent versus explicit zero, required/admitted inputs, optional excluded benefits, comparable baseline/current periods, negative changes, currency, evidence references/conflicts and insufficient-evidence outcomes. Retain known cost outputs independently from unavailable savings/ROI. Model formula: monthly labor value = supported hours change × loaded hourly rate; monthly amortized implementation = one-time cost / chosen months; monthly value = labor + admitted incremental revenue + admitted avoided cost; monthly cost = recurring cost + amortization; net=value−cost; ROI=net/cost×100 if cost>0 and required inputs admitted. This does not establish causation. Annual display may only multiply a stated monthly scenario over a defined horizon; no mixing annual input benefits with monthly costs.

The save_snapshot POST exists and checks inventory writer authority; it creates an immutable assessment and redirects. Do not mark all persistence nonexistent. New baseline/evidence fields remain proposed. InventoryItemForm also requires numeric monthly_cost, and current import review requires cost; unknown-cost support needs model/form reconciliation. Do not change validation by hiding fields.

## Assessment, policy and report contracts

OrganizationRuleForm.structured_definition() builds all/contains conditions on data_categories and capabilities. Effects include severity floor, required control, risk points, finding and recommended review. Text fields describe messages, not executable natural language. Test/save use action=test/save. Retain actual choices/fields and write/edit gates. Software rule examples replace invented transaction policies.

Assessment template's existing “Open browser report” POST actually invokes reports:generate. generate_report_action() checks membership WRITE_ROLES, creates report, ensures a job and redirects to detail. Change the caption to “Generate browser report” when no report exists; do not imply PDF completion. Report objects, browser context, queued jobs and PDF/storage artifacts are distinct. Worker stopped means a new job is not an operating PDF pipeline. Report download handles artifact/storage checks; source route existence is not end-to-end verification. Add only supported availability context, under engineering ownership.

## Action and financial contracts

Action cards are proposed: supporting evidence/rule → recommendation → separately recorded approval → manually performed attestation or qualified executable operation → independently recorded outcome verification. These are separate fields, not a decorative success stepper. Specify target, scope/effects, responsible role, authority basis, expected measured/estimated outcome, history and recovery. No accounting writes, application revocations or enforcement are assumed.

Financial evidence intake, normalization, sinks and discrepancy workflows are proposed. Source type, receipt/observation time, period, currency/basis, normalization version, duplicates/conflicts and exclusions are required before sums. Mock fixtures do not establish existing PDF/bank-statement imports.

## Lead contracts and internal review

Three hypotheses: visibility uncertainty → discovery discussion; comparable cost/outcome uncertainty → workflow evaluation; repeatability needs → governed-automation interest. Required contact and actual problem only; organization/role/systems/responsibility/desired next step/contact preference are optional. Allow not sure. System responsibility is not verified legal or purchasing authority. No financial files or account connections are required.

lead-submission-contract.json v2 defines separate request-contact scope and unchecked optional marketing, exact notice versions/text/time, source categories and missing values. All receipt and routing states are proposed: server durable receipt before success, idempotent same-payload retry, conflicting duplicate rejection, outcome-uncertain retry without false success. No live email, CRM, enrichment or analytics. Categories expose rule version/input reasons; no score. Internal lead review uses its own operator shell, not ordinary customer workspace navigation. Storage, retention, access and privacy require review before live intake.

## Billing and legal

Source catalog confirms Core99 standard/49 founder6months→75; Automation149 standard/75 founder6months→112, USD monthly. pricing.py validates price object contracts; source does not prove current Stripe objects. Founder eligibility/calendar and actual offer availability must use backend context, not mock arithmetic or invented slots. Enterprise exists unavailable in source; no cancellation inference from omission. Automation runtime purchases remain disabled. Core source available=True does not establish public availability while maintenance gate remains.

Billing account uses portal plus founder cancellation/undo context. Do not inline invented cards/invoices. Checkout success uses subscription.grants_access; pending return is not confirmation or workspace authority. Privacy/terms are drafting layouts only, no legal/service/storage/retention/security promises.

## Acceptance and unresolved questions

Blocking questions: current Stripe runtime price/offer verification; Core versus Automation included-feature boundary; authoritative required ROI inputs/exclusions and null semantics; approved integration scopes; financial basis/normalization rules; report artifact availability/retry context; internal operator roles; lead receipt storage/consent/privacy/retention and permitted human contact. Source/package identity is recorded, but engineering must confirm it still matches the active candidate and agree file ownership before patching.

Before accepting a presentation patch: actual Django render with production-style collectstatic and original brand PNG inclusion; forms/validation/navigation/pagination; keyboard/focus/mobile; permission-sensitive states; no accidental URL, flag, billing/OAuth/referrer/callback behavior change. Browser review of this static atlas cannot satisfy application acceptance.

## Per-screen contracts

### 01-overview · Evidence coverage

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Review what is supported and what needs attention. Authorized workspace member; writer controls require actual server role.
- Primary action: Review supporting evidence; static review control only.
- Required data: Observed, Source / time, What remains unknown, Next step, Last manual import, Last successful automatic collection, Last authorized automatic action, Expenditure sinks, Observed discrepancies, Calculated ROI.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2, D3, D4, D6.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 02-home · Understand your AI adoption.

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `home.html`.
- Purpose / user: Know what the evidence supports. Prospective accounting/bookkeeping team.
- Primary action: Explore the approach; static review control only.
- Required data: Observe, Review, Document.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 03-pricing · Core and Automation

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `billing/portfolio.html`.
- Purpose / user: Source-defined prices; live Stripe configuration still needs verification. Prospective accounting/bookkeeping team.
- Primary action: Review Core terms; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 04-visibility-landing · Know which tools are present.

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Understand the access the evidence establishes. Prospective accounting/bookkeeping team.
- Primary action: Request a discovery conversation · proposed; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 05-roi-landing · Is AI paying off?

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Start with comparable costs and outcomes. Prospective accounting/bookkeeping team.
- Primary action: Describe a workflow · proposed; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D11, D5.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 06-automation-landing · Repeatable evidence.

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Clear human authority. Prospective accounting/bookkeeping team.
- Primary action: Express Automation interest · proposed; static review control only.
- Required data: Scheduled collection, Repeatable assessment, Report generation, Purchases.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D11, D4.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 07-lead-confirmation · Request receipt

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: A success state requires durable server receipt. Prospective accounting/bookkeeping team.
- Primary action: Review available information; static review control only.
- Required data: Receipt, Problem, Preferred contact, System responsibility, Marketing consent, Validation failed, Outcome uncertain, Duplicate request, Conflicting duplicate.
- Interaction/authority: Proposed durable receipt before success; same idempotency key + same payload returns same receipt; same key + different payload conflict; uncertain network retry reuses key. No automatic contact.
- Dependencies: D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 08-login · Log in

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `registration/login.html`.
- Purpose / user: Use your Stewardence account. Unauthenticated returning account user.
- Primary action: Log in; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 09-signup · Create your account

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `registration/signup.html`.
- Purpose / user: Account creation is separate from workspace and subscription access. Unauthenticated prospective account user.
- Primary action: Create account; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 10-workspace-selection · Choose your workspace

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `organizations/select_workspace.html`.
- Purpose / user: Ordinary workspace selection and sandbox testing have separate access paths. Authenticated member; sandbox branch active allowlisted owner.
- Primary action: Open selected workspace; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Normal picker POST organizations:workspace-activate with organization_id; sandbox picker POST integrations:quickbooks-connect with action=select_workspace and exactly one workspace_id. Current active workspace requires authority() checks; no new authentication.
- Dependencies: D1.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 11-workspace-setup · Create your organization workspace

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `organizations/setup.html`.
- Purpose / user: Step 1 of 3 · Organization, starting point, review. Authorized workspace member; writer controls require actual server role.
- Primary action: Continue; static review control only.
- Required data: 2 · Starting point, 3 · Review, Scope.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 12-inventory-list · Software inventory

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `inventory/list.html`.
- Purpose / user: Review records and their supporting sources. Authorized workspace member; writer controls require actual server role.
- Primary action: Add software; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 13-inventory-detail · Example Desktop Tool

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `inventory/detail.html`.
- Purpose / user: Software record · synthetic. Authorized workspace member; writer controls require actual server role.
- Primary action: Review source; static review control only.
- Required data: Observation, Source / observed time, Received, Catalog match, Authorized / enabled / actively used, Monthly cost.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 14-inventory-form · Add or edit software

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `inventory/form.html`.
- Purpose / user: Customer declaration · preserve the existing form contract. Authorized workspace member; writer controls require actual server role.
- Primary action: Save software; static review control only.
- Required data: Context, Access and capability.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D5.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 15-discovery · StewardSensors collection

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `inventory/discovery.html`.
- Purpose / user: Manual, one-shot Windows installed-program observations. Authorized workspace member; writer controls require actual server role.
- Primary action: Upload bundle; static review control only.
- Required data: Observed / received, Scope, Coverage, Unknown.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 16-download · Download StewardSensors

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `downloads/detail.html`.
- Purpose / user: Run locally, review the result, and upload manually. Authorized workspace member; writer controls require actual server role.
- Primary action: Download Windows release; static review control only.
- Required data: Source release metadata, 1 · Download, 2 · Run locally, 3 · Review, 4 · Upload.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D1.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 17-import-upload · Upload software inventory CSV

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `imports/upload.html`.
- Purpose / user: Step 1 of 3 · Upload, check and correct, final approval. Authorized workspace member; writer controls require actual server role.
- Primary action: Upload for review; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 18-import-review · Check imported software

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `imports/review.html`.
- Purpose / user: Step 2 of 3 · No inventory has been written. Authorized workspace member; writer controls require actual server role.
- Primary action: Continue to final review; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 19-import-final · Approve software import

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `imports/final.html`.
- Purpose / user: Step 3 of 3 · Final approval. Authorized workspace member; writer controls require actual server role.
- Primary action: Save and finish setup; static review control only.
- Required data: Workspace, Effect, Authority, Source.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 20-integrations · Integrations and collection

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Connection health and evidence collection are separate. Authorized workspace member; writer controls require actual server role.
- Primary action: Review QuickBooks connection; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2, D3.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 21-quickbooks · QuickBooks sandbox

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `integrations/quickbooks.html`.
- Purpose / user: Example Sandbox · connecting owner · allowlisted example. Active allowlisted owner of selected workspace and connecting owner for management.
- Primary action: Check token validity; static review control only.
- Required data: Persistent state, Environment, Token check, Production access, Accounting records, Last provider collection, Live normalization / ROI, External financial actions, Unavailable to this account, Workspace selection required, Eligible and disconnected, Authorization in progress, Reconnect required, Disconnect pending, Operation failed.
- Interaction/authority: Connect/refresh/disconnect POST named URLs with CSRF. callback and disconnected remain empty redirects. Models store disconnected, connected, reconnect, revoking. Authorization progress is transient proposed UI. No account-wide sandbox availability.
- Dependencies: D1, D3.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 22-xero · Xero integration

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed adapter · not connected. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Adapter, Exact approved scopes, Data collected, Last provider collection, Next step.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D3.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 23-microsoft · Microsoft integration

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed adapter · not connected. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Adapter, Exact approved scopes, Data collected, Last provider collection, Next step.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D3.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 24-collection-history · Collection history

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed history over supported manual sources. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2, D4.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 25-assessments-list · Assessments

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed list · existing snapshot detail surface. Authorized workspace member; writer controls require actual server role.
- Primary action: Open snapshot; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 26-assessment-detail · Assessment detail

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `assessments/detail.html`.
- Purpose / user: Captured snapshot · synthetic example. Authorized workspace member; writer controls require actual server role.
- Primary action: Generate browser report; static review control only.
- Required data: Captured, Rule set, Input, Limits.
- Interaction/authority: Generate report POST reports:generate(snapshot.id), hashes_valid template branch, WRITE_ROLES server check. Creates report object + generation job, redirects report detail. Caption changes from Open browser report to Generate browser report; not a new generation contract.
- Dependencies: D8.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 27-policies-list · Policies and rules

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `policies/list.html`.
- Purpose / user: Rules create findings and recommendations; they do not enforce provider changes. Authorized workspace member; writer controls require actual server role.
- Primary action: Create a rule; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 28-policy-detail · Review external transfer

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `policies/detail.html`.
- Purpose / user: Organization rule · demo-v1 · synthetic. Authorized workspace member; writer controls require actual server role.
- Primary action: Edit and test; static review control only.
- Required data: When, And, Effect, Outcome limit.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 29-policy-editor · Organization rule editor

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `policies/form.html`.
- Purpose / user: Structured deterministic conditions and effects. Authorized workspace member; writer controls require actual server role.
- Primary action: Test without saving; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: OrganizationRuleForm structured_definition: all/contains data_categories AND capabilities; configurable effects. POST action=test or save. Preserve all current fields and choice validation; text fields describe effects, never execute prose.
- Dependencies: Shared source/ownership acceptance (D1).
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 30-roi-overview · ROI and outcomes

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed evidence model · financial collection unfinished. Authorized workspace member; writer controls require actual server role.
- Primary action: Review required inputs; static review control only.
- Required data: Baseline / comparison periods, Labor hours and loaded rate, One-time costs / amortization, Additional revenue / avoided cost, Model.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D5, D6.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 31-roi-calculator · ROI calculator

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `inventory/roi.html`.
- Purpose / user: Existing estimate form; missing-input semantics require engineering changes. Authorized workspace member; writer controls require actual server role.
- Primary action: Calculate ROI; static review control only.
- Required data: Known recurring cost, Savings, ROI, Persistence.
- Interaction/authority: Existing ROIForm and calculate_roi(AL-ROI-1) treat Unknown as zero and reject nonzero Unknown; desired missing-input behavior is blocked. POST calculate / save_snapshot contract exists. New baseline/comparison evidence fields and null semantics need coordinated backend change.
- Dependencies: D5.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 32-financial-evidence · Financial evidence

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed intake and normalization · synthetic scenario. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D3, D6.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 33-expenditure-sinks · Expenditure sinks

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed breakdown · synthetic data. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D6.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 34-discrepancies · Discrepancy review

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed comparisons, not proof of error or fraud. Authorized workspace member; writer controls require actual server role.
- Primary action: Review supporting entries; static review control only.
- Required data: Authority, Effects, Accounting changes, Resolution.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D6.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 35-actions-list · Action review queue

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Recommendations are distinct from approval, execution and verification. Authorized workspace member; writer controls require actual server role.
- Primary action: Open recommendation; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D7.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 36-action-detail · Review application grant

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed action detail · synthetic evidence. Authorized workspace member; writer controls require actual server role.
- Primary action: Record review note · proposed; static review control only.
- Required data: Observed, Rule, Unknown, Suggested action, Mode, Responsible role, Approval, Execution, Verification.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D7.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 37-reports-list · Reports

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed list · existing browser report detail. Authorized workspace member; writer controls require actual server role.
- Primary action: Open browser report; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D8, D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 38-report-detail · Software assessment report

- Maturity: **partially implemented**. Existing source surface; redesigned expansions require contracts.
- Template: `reports/detail.html`.
- Purpose / user: Existing report detail · synthetic selected snapshot. Authorized workspace member; writer controls require actual server role.
- Primary action: Read methodology; static review control only.
- Required data: Assessment date, Rule / engine basis, Software costs, ROI.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D5, D8.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 39-evidence-library · Evidence library

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed browsing interface over evidence foundations. Authorized workspace member; writer controls require actual server role.
- Primary action: Open source; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 40-evidence-detail · Evidence detail

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed lineage interface · synthetic grant source. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Finding, Source, Observed / received, Match, Establishes, Unknown.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 41-audit · Audit history

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed expanded interface · scoped recorded activity. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D9.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 42-workspace-admin · Workspace administration

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Expanded controls are proposed. Authorized workspace member; writer controls require actual server role.
- Primary action: Save settings · proposed; static review control only.
- Required data: Workspace, Your organization role, Subscription entitlement, Provider authority.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D10.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 43-members-authority · Members and authority

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed expanded member-management interface. Authorized workspace member; writer controls require actual server role.
- Primary action: Invite member · proposed; static review control only.
- Required data: Purchasing authority, Provider authorization, Invitation / role change, Action approval.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D10.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 44-billing · Subscription and billing

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `billing/account.html`.
- Purpose / user: Existing account surface · synthetic subscription example. Subscription account user; exact billing authority checks.
- Primary action: Manage billing; static review control only.
- Required data: Portfolio, Status, Current monthly price, Paid period end, Product entitlement, Available action, Undo action, Calendar.
- Interaction/authority: Keep billing:portal route plus founder-cancel and founder-cancel-undo POST/CSRF and exact context gates. No UI-only entitlement checks; do not copy Stripe card or invoice data.
- Dependencies: D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 45-checkout-confirmation · Confirming your subscription

- Maturity: **existing**. Existing template/view foundation; no public qualification claim.
- Template: `billing/success.html`.
- Purpose / user: Pending example · a checkout return is not payment confirmation. Returning checkout account user.
- Primary action: Check subscription status; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Pending versus confirmed based on subscription.grants_access; preserve existing billing:portfolio and organizations:setup routes. Redirect alone is not a verified payment.
- Dependencies: D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 46-privacy · Privacy

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Layout proposal · content not approved. Prospective accounting/bookkeeping team.
- Primary action: Review available information; static review control only.
- Required data: Information collected, Purposes and lawful basis, Sources and sharing, Consent and contact, Retention and deletion, Rights and requests, Operator contact.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 47-terms · Terms

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Layout proposal · content not approved. Prospective accounting/bookkeeping team.
- Primary action: Review available information; static review control only.
- Required data: Service scope, Accounts and authority, Subscriptions and cancellation, Current and planned capabilities, Responsibilities, Limitations, Contact.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 48-contact · Start a conversation

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed request form · no active submission workflow. Prospective accounting/bookkeeping team.
- Primary action: Send request · proposed; static review control only.
- Required data: Actual bound form/list context; see corrected HTML and source mapping.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 49-states · General operating states

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed reusable state specification. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Report, Lead.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D2, D8, D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 50-authority-states · Authority and connection states

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Proposed presentation specification over source-backed QuickBooks conditions. Authorized workspace member; writer controls require actual server role.
- Primary action: Review available information; static review control only.
- Required data: Unavailable, Workspace needed, Disconnected, Connected, Reconnect required, Disconnect pending, Operation failed.
- Interaction/authority: Preserve existing form/view/URL contract where mapped. New controls and persistence are proposed until implemented.
- Dependencies: D3, D7, D12.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

### 51-lead-review · Lead review

- Maturity: **proposed**. No implemented route is established for this designed surface.
- Template: `Proposed; no route/template established`.
- Purpose / user: Internal operator workflow · proposed. Authorized internal Stewardence operator; proposed.
- Primary action: Record human review · proposed; static review control only.
- Required data: Category, Rule version, Reasons, Self-reported problem, System responsibility, Observed receipt, Unknown, Request-related preference, Request notice, Optional marketing, Campaign attribution.
- Interaction/authority: Internal operator permission scope separate from customer tenancy; categories and review actions require backend contracts and recorded consent/time/rule inputs.
- Dependencies: D10, D11.
- Responsive: 390px mobile: evidence/task first, stacked forms, accessible horizontally scrollable tables; SignalMeter financial detail collapsed. Desktop1440px: narrow205px navigation and clear content hierarchy.
- States: empty, loading, partial, stale, denied, error, success per common contract; adapt to actual source-supported response.

## Common state contract

- **empty**: Name the missing object/source and a supported next step. No result is not evidence of absence.
- **loading**: Preserve scope and existing values; mark request in progress. Do not fabricate background jobs.
- **partial**: Identify included sources and missing inputs; suppress unsupported conclusions.
- **stale**: Show source observation time and applicable freshness rule; no global unconfigured stale threshold.
- **denied**: Keep entitlement, organization role, and provider authority distinct; enforce on server.
- **error**: Preserve entered data where safe; name recoverable operation without secrets; do not claim success.
- **success**: Show only the server-confirmed result and scope; downstream collection/approval/outcome remain independent.

## Backend dependencies

- **D1**: Current deployed candidate/package fingerprint, shared-file ownership and runtime context acceptance before application patch.
- **D2**: Aggregate overview/evidence coverage denominator, source-time model, freshness thresholds, and presentation context.
- **D3**: Production provider approval and adapters: QuickBooks accounting collection/normalization; Xero and Microsoft scopes and adapters.
- **D4**: Worker startup/qualification and scheduled collection pipeline; last successful automatic collection and authorized automatic action records.
- **D5**: ROI semantic reconciliation: null/unknown inputs, insufficient-evidence outcomes, comparable periods, negative labor changes and evidence references.
- **D6**: Financial evidence intake/normalization, currency and accounting basis, duplicate/conflict resolution, sink/discrepancy rules.
- **D7**: Action recommendation, approval, manual attestation, optional execution and verification contracts. No provider writes assumed.
- **D8**: Report artifact storage/renderer/job end-to-end qualification; worker stopped; availability/retry context for downloads.
- **D9**: Expanded evidence/audit list and detail routes, permission scopes, pagination and result completeness.
- **D10**: Workspace administration/member invitation/role-change and approval-policy contracts; internal operator permissions separate.
- **D11**: Durable lead receipt/idempotency, validation, consent record, authorized human routing, internal review and factual privacy content.
- **D12**: Stripe runtime prices, founder eligibility/calendar, Core feature boundary, public maintenance gate and launch qualification.

## Screen-specific operating states and authority


### 01-overview

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No source received; review manual intake options. Connection may exist independently.
- **loading**: Evidence coverage: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Evidence coverage: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Evidence coverage: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Evidence coverage: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Evidence coverage: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 02-home

Source: `src/agentledger/urls.py` — `home_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: Product preview absent: retain factual approach and maintenance availability.
- **loading**: Understand your AI adoption.: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Understand your AI adoption.: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Understand your AI adoption.: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Understand your AI adoption.: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Understand your AI adoption.: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 03-pricing

Source: `apps/billing/views.py` — `portfolio_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No qualified offer: show pricing under review; no enabled checkout.
- **loading**: Core and Automation: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Core and Automation: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Core and Automation: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Core and Automation: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Core and Automation: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 04-visibility-landing

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No answers: contact and problem required; qualification optional.
- **loading**: Know which tools are present.: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Know which tools are present.: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Know which tools are present.: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Know which tools are present.: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Know which tools are present.: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 05-roi-landing

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No workflow stated: request a concrete workflow, not financial records.
- **loading**: Is AI paying off?: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Is AI paying off?: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Is AI paying off?: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Is AI paying off?: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Is AI paying off?: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 06-automation-landing

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No recurring need stated: ask desired workflow; no Automation checkout.
- **loading**: Repeatable evidence.: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Repeatable evidence.: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Repeatable evidence.: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Repeatable evidence.: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Repeatable evidence.: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 07-lead-confirmation

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No committed receipt: never show successful request confirmation.
- **loading**: Request receipt: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Request receipt: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Request receipt: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Request receipt: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Committed receipt with original answers and consent; synthetic success example only.

### 08-login

Source: `apps/accounts/urls.py` — `Django LoginView route`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: Blank credentials: display bound form requirements.
- **loading**: Log in: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Log in: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Log in: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Log in: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Existing authenticated destination, safe next preserved.

### 09-signup

Source: `apps/accounts/views.py` — `signup_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: Blank account form: preserve actual signup required/optional fields.
- **loading**: Create your account: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Create your account: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Create your account: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Create your account: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Account created by source view; workspace authority separate.

### 10-workspace-selection

Source: `apps/organizations/views.py` — `workspace_selection_view / activate_workspace_action; sandbox quickbooks_views.connect`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No ordinary memberships / no sandbox owned workspace: separate empty messages.
- **loading**: Choose your workspace: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Choose your workspace: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Choose your workspace: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Choose your workspace: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Selected authorized workspace in session; sandbox grants no subscription.

### 11-workspace-setup

Source: `apps/organizations/views.py` — `setup_organization_view / setup_organization_start_view / setup_organization_review_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No organization details: name and industry form errors.
- **loading**: Create your organization workspace: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Create your organization workspace: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Create your organization workspace: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Create your organization workspace: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Source-reviewed setup completes, then chosen supported starting point.

### 12-inventory-list

Source: `apps/inventory/views.py` — `inventory_list_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No inventory records: add software or supported manual intake if writer.
- **loading**: Software inventory: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Software inventory: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Software inventory: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Software inventory: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Software inventory: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 13-inventory-detail

Source: `apps/inventory/views.py` — `inventory_detail_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No supporting observation: declaration only, unknown source attributes.
- **loading**: Example Desktop Tool: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Example Desktop Tool: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Example Desktop Tool: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Example Desktop Tool: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Example Desktop Tool: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 14-inventory-form

Source: `apps/inventory/views.py` — `create_inventory_item_view / edit_inventory_item_view`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: New blank record: do not default unknown cost to zero.
- **loading**: Add or edit software: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Add or edit software: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Add or edit software: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Add or edit software: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Inventory record durably saved under writer role; declaration provenance retained.

### 15-discovery

Source: `apps/inventory/discovery_views.py` — `discovery_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No scans: upload supported Windows bundle; no continuous enrollment.
- **loading**: StewardSensors collection: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: StewardSensors collection: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: StewardSensors collection: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: StewardSensors collection: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Validated source received; catalog observation distinct from actual usage.

### 16-download

Source: `src/agentledger/downloads.py` — `download_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: Release unavailable: no active download promise; verify source artifact.
- **loading**: Download StewardSensors: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Download StewardSensors: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Download StewardSensors: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Download StewardSensors: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Download StewardSensors: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 17-import-upload

Source: `apps/imports/views.py` — `upload_csv_view`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No selected CSV: field error; no staging receipt.
- **loading**: Upload software inventory CSV: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Upload software inventory CSV: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Upload software inventory CSV: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Upload software inventory CSV: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Import batch staged only.

### 18-import-review

Source: `apps/imports/views.py` — `review_import_view`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No editable rows: reflect batch lifecycle; no inventory write.
- **loading**: Check imported software: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Check imported software: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Check imported software: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Check imported software: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Corrections validated and stage advanced; no inventory records yet.

### 19-import-final

Source: `apps/imports/views.py` — `final_review_view / confirm_import_action`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No valid final batch: do not offer confirmation against nonexistent items.
- **loading**: Approve software import: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Approve software import: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Approve software import: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Approve software import: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Confirm import transaction adds validated software records, not accounting entries.

### 20-integrations

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No connection: manual sources still separate; ineligible sandbox stays unavailable.
- **loading**: Integrations and collection: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Integrations and collection: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Integrations and collection: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Integrations and collection: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Integrations and collection: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 21-quickbooks

Source: `apps/integrations/quickbooks_views.py` — `connect / refresh / disconnect / callback`. Active authenticated allowlisted user + sandbox enablement + selected workspace owner; connection management additionally connected_by. Denied responses source-backed.

- **empty**: No active workspace: eligible owned-workspace picker; no connection object means disconnected.
- **loading**: QuickBooks sandbox: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: QuickBooks sandbox: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: QuickBooks sandbox: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Active authenticated allowlisted user + sandbox enablement + selected workspace owner; connection management additionally connected_by. Denied responses source-backed.
- **error**: QuickBooks sandbox: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Persistent connection condition and transient result are distinct; fresh check is not renewal proof.

### 22-xero

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No adapter: show pending, not disconnected operational integration.
- **loading**: Xero integration: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Xero integration: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Xero integration: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Xero integration: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Xero integration: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 23-microsoft

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No adapter: exact registration/scopes require review.
- **loading**: Microsoft integration: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Microsoft integration: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Microsoft integration: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Microsoft integration: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Microsoft integration: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 24-collection-history

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No collection runs: no timestamps; connection alone creates no collection.
- **loading**: Collection history: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Collection history: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Collection history: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Collection history: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Collection history: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 25-assessments-list

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No snapshots: no assessed outcome or report claimed.
- **loading**: Assessments: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Assessments: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Assessments: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Assessments: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Assessments: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 26-assessment-detail

Source: `apps/assessments/views.py` — `assessment_snapshot_detail_view; reports.views.generate_report_action`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No report object: Generate browser report; no Open report.
- **loading**: Assessment detail: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Assessment detail: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Assessment detail: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Assessment detail: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Report object created and job ensured; PDF completion not asserted.

### 27-policies-list

Source: `apps/policies/views.py` — `list_rules_view`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No rules: create only when can_write.
- **loading**: Policies and rules: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Policies and rules: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Policies and rules: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Policies and rules: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Policies and rules: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 28-policy-detail

Source: `apps/policies/views.py` — `detail_rule_view`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No history: expanded history proposed; current definition still available.
- **loading**: Review external transfer: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Review external transfer: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Review external transfer: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Review external transfer: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Review external transfer: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 29-policy-editor

Source: `apps/policies/views.py` — `_render_rule_form`. Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.

- **empty**: No test item: Choose software to test this rule against.
- **loading**: Organization rule editor: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Organization rule editor: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Organization rule editor: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source writer roles: owner, admin, assessor. Read-only viewer cannot mutate. Import batch also belongs to creator and organization. Policy detector-derived editing follows can_edit restrictions.
- **error**: Organization rule editor: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Test returns evaluation without save; save writes rule version and audit event.

### 30-roi-overview

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No comparable labor: costs may remain known; ROI insufficient.
- **loading**: ROI and outcomes: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: ROI and outcomes: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: ROI and outcomes: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: ROI and outcomes: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: ROI and outcomes: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 31-roi-calculator

Source: `apps/inventory/views.py` — `inventory_roi_view; apps.roi.forms.ROIForm; apps.roi.engine.calculate_roi`. Source membership scopes calculation; save_snapshot requires inventory writer (owner/admin/assessor). New missing-input model remains blocked.

- **empty**: Unknown required inputs: target insufficient; current zero-encoding blocker explicit.
- **loading**: ROI calculator: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: ROI calculator: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: ROI calculator: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Source membership scopes calculation; save_snapshot requires inventory writer (owner/admin/assessor). New missing-input model remains blocked.
- **error**: ROI calculator: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Existing calculate/save_snapshot contracts only after valid inputs; target semantic blocker not hidden.

### 32-financial-evidence

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No financial evidence: no normalized totals; connected QBO is not a source receipt.
- **loading**: Financial evidence: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Financial evidence: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Financial evidence: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Financial evidence: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Financial evidence: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 33-expenditure-sinks

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No classified expenditure: no vendor count or recurrence claim.
- **loading**: Expenditure sinks: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Expenditure sinks: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Expenditure sinks: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Expenditure sinks: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Expenditure sinks: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 34-discrepancies

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No candidates: no discrepancy in compared evidence only; coverage limit shown.
- **loading**: Discrepancy review: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Discrepancy review: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Discrepancy review: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Discrepancy review: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Discrepancy review: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 35-actions-list

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No recommendations: no approved/executed actions inferred.
- **loading**: Action review queue: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Action review queue: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Action review queue: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Action review queue: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Action review queue: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 36-action-detail

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No approval or execution: fields stay not requested/not supported.
- **loading**: Review application grant: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Review application grant: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Review application grant: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Review application grant: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Review application grant: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 37-reports-list

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No report objects: assessments are not reports.
- **loading**: Reports: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Reports: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Reports: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Reports: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Reports: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 38-report-detail

Source: `apps/reports/views.py` — `report_detail_view / report_download_view`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No PDF artifact: keep browser report separate; download unavailable.
- **loading**: Software assessment report: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Software assessment report: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Software assessment report: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Software assessment report: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Verified ready PDF only when actual artifact/storage lookup succeeds; browser availability independent.

### 39-evidence-library

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No evidence records: scoped intake suggestion only.
- **loading**: Evidence library: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Evidence library: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Evidence library: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Evidence library: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Evidence library: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 40-evidence-detail

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No related report: not generated; do not fabricate lineage.
- **loading**: Evidence detail: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Evidence detail: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Evidence detail: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Evidence detail: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Evidence detail: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 41-audit

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No recorded audit events: not proof no external activity.
- **loading**: Audit history: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Audit history: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Audit history: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Audit history: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Audit history: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 42-workspace-admin

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No editable administration contract: read-only context.
- **loading**: Workspace administration: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Workspace administration: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Workspace administration: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Workspace administration: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Workspace administration: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 43-members-authority

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No invitation implementation: no operative invite control.
- **loading**: Members and authority: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Members and authority: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Members and authority: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Members and authority: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Members and authority: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 44-billing

Source: `apps/billing/views.py` — `billing_account / founder_cancel / founder_cancel_undo / billing_portal`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No subscription record: existing View subscription options branch.
- **loading**: Subscription and billing: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Subscription and billing: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Subscription and billing: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Subscription and billing: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Actual provider-backed subscription/cancellation fields; no invented future dates.

### 45-checkout-confirmation

Source: `apps/billing/views.py` — `checkout_success`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No grants_access: existing pending branch, not confirmed.
- **loading**: Confirming your subscription: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Confirming your subscription: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Confirming your subscription: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Confirming your subscription: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: subscription.grants_access confirmed; does not grant workspace role.

### 46-privacy

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No approved legal text: layout drafting topics only.
- **loading**: Privacy: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Privacy: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Privacy: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Privacy: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Privacy: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 47-terms

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No approved terms: no agreement or guarantees.
- **loading**: Terms: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Terms: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Terms: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Terms: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Terms: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 48-contact

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No request answers: contact and problem only required.
- **loading**: Start a conversation: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Start a conversation: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Start a conversation: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Start a conversation: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Start a conversation: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 49-states

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No source state: do not infer healthy condition.
- **loading**: General operating states: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: General operating states: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: General operating states: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: General operating states: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: General operating states: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 50-authority-states

Source: `Proposed; no route verified` — `Contract pending`. Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.

- **empty**: No entitlement/membership/provider scope: independent unavailable fields.
- **loading**: Authority and connection states: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Authority and connection states: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Authority and connection states: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Use actual source role/context where mapped; proposed mutation needs an explicit server authority contract. Subscription never establishes organizational/provider authority.
- **error**: Authority and connection states: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Authority and connection states: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.

### 51-lead-review

Source: `Proposed; no route verified` — `Contract pending`. Proposed internal operator permission; not ordinary customer membership or subscription.

- **empty**: No leads: no routing or contact action; internal scope only.
- **loading**: Lead review: request pending only; preserve scope/current safe data. For server-rendered pages this is a proposed submitting cue, not a background worker state.
- **partial**: Lead review: identify unavailable source/field/operation before conclusions; do not conflate missing evidence with no finding.
- **stale**: Lead review: show actual observation/receipt or captured-object time; freshness policy required before stale badges. Snapshot history does not auto-update.
- **denied**: Proposed internal operator permission; not ordinary customer membership or subscription.
- **error**: Lead review: retain safe entered values; show current source validation or operation result. No durable result before commit; secrets/query authorization data omitted.
- **success**: Lead review: only actual scoped result or clearly labeled synthetic proposed state; no downstream approval, execution or data import inferred.
