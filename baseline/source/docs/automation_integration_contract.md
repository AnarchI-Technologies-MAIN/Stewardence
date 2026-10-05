# Stewardence Automation integration contract

Status: implementation in progress. Billing security is deployed privately;
provider connectors and scheduled processing are not enabled for purchase.

The approved first connector set is QuickBooks Online, Xero, and Microsoft
365/Excel. Customers authorize their own accounts and specific collection
purposes. Collector evidence and business-system data feed common deterministic
assessment and reporting rules. This document describes requirements rather
than representing unimplemented provider support as available.

## Evidence and calculation

Record the provider, authorized account, source record identifiers, source
fingerprints, observation and retrieval timestamps, permission scope, completeness,
period, currency, and rule version. Tenant binding comes from the stored
connection authorization, never an organization ID supplied in an upload.

A grant establishes that an application is authorized. Exact application IDs
can be matched against a reviewed AI product catalog. Neither a grant nor an
installed product proves AI features are enabled, actual usage, financial benefit,
or causal impact. Preserve those distinctions in the finding and report.

ROI inputs require approved workflow attribution and a reconciled comparison
period. Provider records may establish actual expenses, payment activity, and
other selected observations. They do not automatically establish labor savings,
avoided costs, or attributable revenue. Preserve measured, customer-supplied,
and estimated provenance. Explicitly account for implementation costs and report
any excluded benefit categories. Never sum an invoice and its payment as separate
costs. Preserve credits/refunds during provider normalization; the analysis
module consumes reconciled, nonnegative period aggregates rather than raw lines.

The new period ROI module compares baseline and current workflow hours, values
the difference using the specified loaded rate, adds explicit attributable
benefits, and subtracts tool and allocated implementation costs. Missing required
inputs produce an insufficient-evidence result. Zero cost leaves ROI percentage
undefined. Negative time savings and net value remain negative. Currency
conversion, period allocation, and baseline comparability require explicit
reviewed rules; the module does not infer them.

Canonical hashes cover calculation inputs and outputs. They support replay and
change detection; they are not signatures or independent proof that source data
or a named approval is authentic. Connection custody, authorization receipts,
and immutable result persistence must validate those properties separately.

## Action cards

Every proposal identifies its workflow, applicable system, evidence references,
rule version, rationale, known limitations, and required approval. A card is
proposal-only until separate authorization exists for its exact action and
scope. ROI findings do not directly cancel software, change a ledger, remove an
integration, or revoke application permissions.

## Provider boundaries

- QuickBooks Online: use the Accounting API for specifically authorized
  financial observations. Its accounting scope can allow writes; enforce an
  outbound read-operation allowlist. Do not advertise tenant-wide third-party
  integration enumeration until a supported evidence source is verified.
- Xero: use current granular read scopes and separate organization connections.
  Request only the financial entities/reports needed for the approved analysis.
  Xero connection data for Stewardence does not enumerate every third-party app
  installed in a customer's organization.
- Microsoft 365: permission-grant discovery requires appropriate directory
  access. Exact service-principal application IDs identify connected products;
  display names are not authoritative AI classification. Obtain separate consent
  for selected workbook data. Graph's workbook API has delegated write-capable
  permissions, so evaluate selected-file download and bounded parsing before
  requesting workbook scopes. Do not execute macros or refresh external links.

## Remaining release work

1. OAuth app registrations, approved callbacks on www.stewardence.com, encrypted
   token custody, one-use authorization state, tenant/account binding, refresh
   rotation, disconnect, and restricted outbound requests.
2. Provider adapters with bounded pagination, throttling, completeness reporting,
   source normalization, receipt persistence, and customer-reviewed attribution.
3. Scheduled collection with owner authorization, device enrollment, revocation,
   current subscription checks, duplicate protection, and worker lease fencing.
4. Persisted calculation receipts, reviewable action cards, assessments and PDF
   reports, including failure/staleness states and cross-tenant tests.
5. Full qualification with sandbox/test accounts for all three providers. Then
   activate the Automation price contracts and worker after public TLS and
   report-storage checks pass.

## Primary provider references checked 2026-10-02

- https://help.developer.intuit.com/s/question/0D5TR00001FvXDB0A3/how-can-i-give-an-api-read-access-only
- https://developer.xero.com/documentation/guides/oauth2/scopes/
- https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-list?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/workbook-list-worksheets?view=graph-rest-1.0
