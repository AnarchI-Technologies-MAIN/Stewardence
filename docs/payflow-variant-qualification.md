# Payflow variant qualification

Alexander requested three tier contracts and a founder discount for each.
Founder is a pricing variant of each tier, not a separate entitlement tier.
Customer labels: Core / Freelancer, Automation / Organization, Enterprise /
Corporate. Registering or quoting a contract never opens its deployment gate.

## Confirmed Enterprise branch rule

Standard Enterprise is $500 monthly with four branches included. Each additional
branch adds $25 monthly: five branches $525, six branches $550. Count must be an
integer from 1 through 10,000. The upper bound is an admission safety limit, not
an advertised capacity or performance qualification.

The initial offline quotation scaffold is `apps.billing.offer_contracts`.
Enterprise founders have five included branches while founder status is retained;
each branch beyond five adds the full $25 monthly. Founder status requires no
unsubscribe or payment lapse. Alexander confirmed an Enterprise founder base
price of $350 monthly for six months, then $400 monthly continuously while founder
status is retained. This supersedes the historical $375/two-month proposal.
Against the $500 standard base, these are 30% and 20% discounts; dollar amounts
take precedence over the conflicting percentage labels supplied alongside them.
Core/Automation retain their existing six-month introductory schedules.

Custom agreements for larger corporate customers are an authorized future option,
not public checkout inputs. An agreement must record its approving operator,
customer/organization, exact base and branch prices, included capacity, duration,
version and accepted terms. No self-submitted price, metadata or company-name
match may activate an override. Agreement issuance, persistence and checkout
binding are not implemented by this quotation scaffold.

Founder continuity enforcement remains an open implementation gate: subscription
deletion currently clears founder status, but invoice payment failure only marks
the subscription past due. A failed collection attempt alone must not be labeled
as proven paid-coverage lapse. Define and enforce paid-through lapse, event order,
terminal founder loss and prevention of reallocation/revival before qualifying
this business rule. Capacity loss must not automatically charge for an existing
fifth branch or delete customer artifacts; obtain an exact accepted billing
transition and present the resulting capacity restriction.

## Required six-flow matrix

| Tier | Standard | Founder | Runtime baseline |
| --- | --- | --- | --- |
| Core / Freelancer | $99 monthly | Existing $49 intro, then $75; terms pending | Existing route; new founder offer disabled |
| Automation / Organization | $149 monthly | Existing $75 intro, then $112; terms pending | Existing gated route; purchases disabled |
| Enterprise / Corporate | $500, four branches; $25 each extra | $350 for six months, then $400; five branches; $25 each extra | No admitted checkout/fulfillment route yet |

For each variant qualify price selection, Checkout creation, paid completion,
signed webhook admission, duplicate/reordered deliveries, failed payment,
cancellation, renewal, exact founder phase transition and provider/local failure
reconciliation. Enterprise additionally needs 1/4/5/6 branch quantities,
increment line admission, adjustment consent and proration policy, persisted
branch capacity and verification that uploaded or declared directory entries
cannot silently cause a charge. Profile semantics must distinguish business
branches from development branches before billable capacity is assigned.

An isolated qualification may enable a gate only in its own test configuration.
Public/direct POST and webhook replay tests must show gated contracts cannot
start purchases or grant unavailable capability. Test-mode key authentication is
already verified separately; no actual six-flow Stripe qualification follows
from that fact or from the quotation unit tests.

Do not implement Enterprise paid admission by routing its completion through the
Core fallback. Existing admission supports Core and Automation only. Complete
the exact contract and receipt boundary before adding an Enterprise route.

No production deployment, production migration, service activation, Automation
purchases or new founder allocation is authorized by this scaffold.
