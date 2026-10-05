# Core standard-only launch

Alexander selected Core at $99 per month, standard only, on 2026-10-03.
This supersedes the proposed founder offer for new Core launch checkouts.

`FOUNDER_OFFER_ENABLED` defaults to false and is enabled only by an explicit
environment value of `1`. Launch configuration must retain `0`. With it off,
the portfolio hides founder pricing and checkout never calls founder allocation,
regardless of submitted price, portfolio or founder fields. Core selects only
the server-configured standard price. Missing standard price returns 503 before
Stripe access or customer creation. Existing founder contracts retain their
verified lifecycle handling; this offer switch does not rewrite contracts.

Required launch configuration: a securely configured Stripe key, webhook signing
secret, Core standard price ID and standard billing portal configuration. The
Core price must independently verify as USD 9900, recurring monthly, on the
intended Stripe account. Founder price IDs and founder portal configuration are
not requirements for new standard-only customers. Live-prefix presence alone
does not verify a key or account. No credential values belong in this document.

Open qualification: isolated test-mode checkout, signed webhook processing,
payment failure/recovery, cancellation, duplicate delivery and durable
subscription-to-workspace fulfillment; final-source regressions and Lyra review.
No production Stripe objects, settings or customer subscriptions have been
created or modified by this decision. Automation purchases remain disabled.

## Offline admission successor

The candidate requires a completed, paid subscription session and an
authoritatively retrieved active subscription bound to the same stored customer,
owner metadata, Core portfolio and registered USD 9900 monthly price. A future
paid-period timestamp is required before issuance. Client-supplied price or plan
fields cannot select the contract. Existing admitted founder reservations use
their separately verified contract; no new founder allocation is enabled.

The candidate uses Stripe Python 16.0.0 and converts verified SDK event and
subscription resources to plain nested dictionaries at the boundary. Locally
signed raw webhook events exercise current-SDK signature verification,
tampering, timestamp expiry, invalid price rollback and duplicate fulfillment.
These events use synthetic local secrets and mocked subscription retrieval;
they are not evidence of a real Stripe checkout or account integration.

Alexander explicitly deferred Stripe authorization and requested offline
qualification on 2026-10-03. Do not request keys again until that scope changes.
Remaining product checks include paid-period expiry in ongoing Core entitlement,
subscription update failure/recovery and concurrent standard checkout admission.
The new admission code is a candidate pending exact final qualification and
Lyra review; production remains unchanged.

## Payment coverage successor

Lyra closed the three harness findings on 2026-10-04 and identified
CORE-ADMISSION-01: a historically paid checkout did not prove payment of the
current subscription period. The prior candidate reproduced 13 coverage
counterexamples in `20261004T001650.468788Z`.

The working successor expands the authoritative latest invoice and requires
the Checkout invoice reference, customer, subscription, subscription item,
registered price and exact service-period boundaries to agree. It admits a
provider-observed paid invoice with complete collection and one complete,
non-prorated USD subscription line. Payment time must fall within the current
bounded service interval. Unknown shapes and incomplete pagination require
review. CORE-CHECKOUT-COVERAGE-1 is a narrow supported read-shape contract;
provider invoice state does not prove bank settlement finality.

The implementation follows current Stripe invoice/line field definitions:
[Invoice object](https://docs.stripe.com/api/invoices/object),
[Invoice line item](https://docs.stripe.com/api/invoice-line-item/object).
Invoice billing-summary `period_end` is not substituted for line service
coverage. No deprecated `paid` boolean is required by this current read shape.

The focused 73-test group passed after the repair. Signed-event rollback and
same-event recovery controls were then added; a new full qualification is
complete: `20261004T001918.105554Z` passed 1187 tests with one intentional skip
(132 warnings). Candidate `312ee835…`, packaged web `2eef9721…`; fresh local
HTTP/source-image comparison and six-object restored access also passed.
The successor has been submitted to Lyra; final coverage disposition is pending.
The previous 1171-pass snapshot predates this successor. Coverage
evidence is checked at admission; durable invoice evidence and ongoing renewal,
expiry, unsupported adjustments and event ordering remain separate gates.

## Shape successor

Lyra closed CORE-ADMISSION-01 and opened CORE-COVERAGE-SHAPE-01. Six locally
signed predecessor counterexamples committed unsupported item/alias/line
identities. The repair requires nonempty string item identities without
coercion, typed integer non-null period aliases, and consistency of a supplied
line invoice and object discriminator. Line `invoice` may be absent or null;
line `object` may be absent, but if present must be `line_item` (null is rejected).
This projection policy is explicit; it does not treat omissions as observed IDs.
The 47-test Core admission group passed with positive absent/null/consistent
projection controls. A new full-source qualification is running; the 1187-pass
coverage snapshot predates this shape repair. Production remains unchanged.

## Unconfigured webhook authentication

Three actual-SDK/Django controls demonstrated that the preceding endpoint
accepted signed fixture events using an empty, whitespace-only or prefix-only
signing secret (`20261004T005917.217157Z`). This is an offline endpoint-admission
counterexample, not demonstrated entitlement creation or a production exploit.

The candidate returns 503 before SDK construction or event-receipt creation
unless the signing secret has the expected prefix, a nonblank suffix and no
leading/trailing whitespace. This is a configuration-shape guard, not evidence
of secret strength or Stripe account identity. The focused webhook group passed
61 tests. A new full qualification is running; the previous 1196-pass shape
snapshot predates this authentication guard. No new keys are requested.
