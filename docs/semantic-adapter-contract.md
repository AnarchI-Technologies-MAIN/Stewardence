# Versioned semantic adapters

Stewardence's shared deterministic entrypoint is the stable contract. Provider adapters translate to it; they do not redefine its meaning or issue authority. Current work is read-only; provider writes remain disabled.

## Canonical evidence

Every admitted record preserves tenant, source account identity, provider and adapter versions, source receipt, observed/declared/inferred/calculated/unknown classification, original timestamp and timezone, normalized UTC time, units, currency, precision, coverage, transformation version and supersession lineage. Preserve bounded raw evidence separately under its retention policy. Missing, zero, false and unavailable are distinct. Conflicting records remain explicit; adapter matching does not establish input truth or comprehensive coverage.

## Adapter update packet

A reviewed immutable packet binds adapter version and artifact hash, compatible canonical-schema versions, fixed provider operations/endpoints, required scopes, transformation rules, fixtures and golden outputs, replay/recovery contract, resource bounds, migration impact and rollback compatibility. Use established package signing/provenance mechanisms when distribution is implemented; no custom cryptography. Never load user-supplied executable adapters into the application process.

Classify releases as compatible repair, new optional capability, semantic change, permission change or state migration. Cosmetic fixes do not request unnecessary consent. New meaning, scope or effects require explicit client review and fresh applicable authority. Preview affected records and qualification results before adoption. Pin each tenant/job to an adapter version; draining in-flight work must preserve that version. Rollback cannot silently reinterpret existing receipts or undo provider effects.

The hosted SaaS installs qualified adapters in server containers on the existing Droplet. Client enablement selects a capability and consent; it ordinarily requires neither local installation nor reboot. StewardSensors is a separate installed collector with its own signed update and review flow.

## Future exact-action writes

A separately authorized action binds tenant, provider account, immutable target identity, operation, exact parameters, currency/units, precondition/version, approver, policy/adapter versions, expiry, nonce and stable idempotency identity. Translate and preview before authorization; send exactly those reviewed semantics. An adapter update cannot expand an old grant, change its target or reinterpret its parameters. Fresh authorization is required when the bound meaning changes.

Resolve ambiguous outcomes by querying the same operation identity and provider state. A lost response never authorizes a duplicate purchase/write. Unsupported preconditions, unresolved identities or uncertain translation fail closed. Provider receipts confirm bounded observed outcomes, not universal truth.

## Qualification gates

Cross-tenant/account substitution; malformed and unknown fields; unit/currency/time conversion; precision loss; scope escalation; malicious endpoint/redirect; nonce and credential-generation replay; revocation races; duplicate delivery; lost response; adapter-version drift during a job; rollback; stale preconditions; partial collection and impossible coverage claims. The private broker authenticates and consumes capabilities; shape-valid UUIDs and matching hashes are not authority.

This document is a development contract. No live broker, downloadable adapter installer or provider write capability is claimed.

## Standards consultation and implemented local candidate

On 2026-10-03, Alexander requested consultation with his persistent Lyra agent
before beginning this implementation. Her complete pre-implementation advice is
preserved in `evidence/lyra-semantic-contract-consultation-20261003.txt`. The
implementation review is a separate gate; advice is not release authorization.

Reuse these distinct standards rather than inventing a universal semantic language:

| Piece | Reused standard/pattern | What it does not establish |
|---|---|---|
| Closed wire structure | [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation) | Domain truth, receipt issuance or authority |
| HTTP interface description | [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html) referencing the same schemas | A live endpoint or enforcement of `readOnly` |
| Stable JSON bytes | [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) | Authentication, arbitrary numeric precision or meaning |
| Source/derivation relationships | [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) concepts mapped to compact JSON | Verified source authenticity; no full PROV export is claimed |
| Provider/domain separation | [Anti-corruption adapter pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer) | Entitlement, orchestration or policy decisions |
| Explicit-offset instants | [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339) with a documented v1 precision subset | An absent timezone, a date-only instant or accounting period boundaries |

CloudEvents is deferred until an event transport is required; no listeners,
message broker, extra service or Droplet are introduced for normalization. If
added, transport identity/time remain separate from content identity and effective
time. Signed distribution remains a future separately qualified operator release
mechanism; the local registry is unsigned integrity metadata, not a trusted signer.

Implemented candidate files live in `source/apps/integrations/semantics/`:

- Bundled, closed JSON Schemas and component-only OpenAPI description.
- A versioned entity-descriptor concept profile, explicit currency/unit subsets,
  pinned mapping/configuration/schema/implementation digests, and no dynamic loader.
- Bounded strict parsing with duplicate-key, invalid Unicode and nonfinite-number
  rejection. Raw numeric lexemes are parsed exactly; financial decimals cannot
  cross the canonical wire as floating-point numbers.
- `prepare_read_request` and `normalize_request`: a language-agnostic input contract
  and read entrypoint binding the exact source and interpretation tuple before
  execution. A queued request cannot silently adopt changed schema/profile/
  mapping/configuration/implementation bytes. These are not issued jobs or grants.
- `normalize_read`: pure transformation of caller-supplied bytes/context.
- `validate_read_envelope`: checks structure, integrity and exact expected bindings.
- `verify_read_translation`: independently re-derives the pinned mapping from exact
  source bytes to detect self-consistent fabricated normalized values.

The initial QuickBooks sandbox CompanyInfo and Microsoft Graph organization
adapters both map provider ID/display name. They preserve distinct namespaces and
entity kinds. CompanyInfo.Id is not the QuickBooks realm; capture authority must
bind the realm separately. Microsoft id-only responses preserve missing display
name and do not require a changed query/permission. Provider-supplied values are
**declared**, even though collecting the response is an observation. Partial
coverage and unresolved provider-scope evidence remain explicit.

This candidate does not change integration routes, persist new raw data, admit
normalizations into assessments, enable collection or execute writes. Those need
authenticated capture, tenant/connection/receipt verification, retention policy,
atomic admission and their own qualification. A valid result object or digest is
not a grant. No new production keys are needed for these offline tests.

## Exact v1 interchange decisions

Content hash covers RFC 8785 bytes of `payload` only; `payload_sha256` is outside
that payload. Raw SHA256 covers the independent original bytes. Schema/profile
digests identify bundled file bytes. Adapter artifact digest covers the RFC 8785
object containing `files`, `adapters` and `dependencies`. Mapping digest covers the
descriptor's id/version/provider/environment/API version/namespace/subject kind/
source-pointer map; configuration digest covers the exact configuration object
(only `{}` is supported initially). The loader enforces the complete nine-file
inventory including the request schema, dependency versions and recomputes all
three derivations. Logical
capture receipt identity and capture time are pinned inputs; retry timestamps and
attempt IDs are outside the content. Replaying a normalization never fetches the
current provider state or inserts the current clock.

Each field carries its own classification and discriminated value state:
`known`, `source_null`, `missing`, `unknown`, `unavailable`, `unsupported`, `redacted`.
Known values are tagged and non-null; source-null is explicit null; other states
forbid values and require a reason. Known zero, false and empty text are preserved.
The entity-descriptor profile admits only provider declarations with known,
missing or source-null state. Broader observed/inferred/calculated domain admission
requires explicit method/input/formula contracts; the generic field vocabulary
does not establish those capabilities.

Exact quantities use `Decimal` internally and canonical decimal strings on the
wire, with separate original source scale. No implicit rounding/conversion.
The v1 numeric subset requires at most 60 coefficient digits on input and at most
60 digits in the expanded canonical decimal representation, scale at most 18,
and bounded expansion. Values such as `1e60` are rejected rather than emitting a
string the validator would later reject. Normalization/validation round trips and
idempotence are tested at the boundaries.
Control integers are bounded to ±(2^53−1), and booleans cannot act as integers.
The explicit currency subset USD/EUR/GBP/CAD does not establish rates, minor-unit
rounding or equivalent accounting bases. The initial `1`, `h`, `count` unit subset
does not assert a full UCUM implementation. New domain/unit/currency meaning needs
a new qualified profile instead of silently relaxing an existing registry.

Normalized instants are UTC with six fractional digits. Original source text is
preserved. Unsupported/date-only/unknown-offset time does not acquire invented UTC.
More than six source fractional digits cannot be silently truncated. These initial
entity adapters have no source effective-time claim, so both effective-time fields
remain null rather than using collection time.

## Tenant updates and safety revocation

Separate central SaaS release, exact interpretation tuple and tenant-selected
semantic profile. A job pins all three relevant artifact/schema/mapping/config
identities at admission. Compatible security fixes may be centrally installed;
changes to meaning/capability require tenant impact preview and acceptance. New
interpretation produces a linked revision, preserving prior evidence.

The proposed notice lifecycle is available → previewed → accepted → pending drain
→ active, with rejected/withdrawn/revoked outcomes. There is no implemented notice
UI/installer or claim of durable acceptance yet. Operator approval, package trust,
tenant acceptance and credentials/scopes are independent checks. A client cannot
upload executable code or mint a capability by selecting an adapter.

If an old version is unsafe, stop that capability and notify the owner; optional
updates do not promise indefinite execution of a vulnerable version. Recovery
receipts must preserve the blocked version and reason. Rollback is a new authorized
release selecting an approved old artifact; it does not roll back anti-replay
state, rewrite historical evidence or undo remote effects.

## Candidate custody and logging limits

`scripts/seal_semantic_contract.py` operates on this local undeployed candidate
only. It computes file identities after edits and records explicit mapping/config
and implementation preimages. Resealing changes the interpretation tuple and
invalidates any earlier qualification for those bytes. Frozen qualification build
contexts preserve their earlier source/registry; no previously issued evidence is
rewritten. Once adopted, contract IDs and versions are immutable. A different
mapping needs a new version/profile and separately authorized release, not a
reseal under an old adopted identity.

Normal validation uses decision-returning schema checks rather than raising a
`jsonschema.ValidationError` carrying the rejected instance. Parser/Decimal/range
failures are classified outside their exception handlers, avoiding retained
vendor/parser exceptions in the normal rejection chain. Tests inspect actual
exception cause/context and ordinary formatted tracebacks with synthetic private
markers. This does not erase Python stack locals or make debug/local-variable
logging safe. Future live callers must catch constant-code failures, keep DEBUG
disabled and exclude payloads/locals from logs and client errors.

The serializer applies a conservative escaped-byte/container budget before dump,
then checks actual bytes afterward. Input bytes, tree depth/nodes and containers
are independently bounded; this is not a hard process memory quota. Private raw
storage and admission still require independent retention/resource controls.

Replay verifies source translation but cannot prove a supplied `supersedes` digest
exists, belongs to the same tenant/entity, precedes the new record or is acyclic.
Those predecessor checks belong to atomic admission. Direct content construction
validates canonical bytes/schema but establishes no authenticity or authority.
Generic typed values likewise do not establish admitted domain meaning or source
scale provenance.
