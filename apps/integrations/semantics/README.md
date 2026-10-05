# Semantic boundary v1

This package performs deterministic, offline read-response translation. It has
no network, database, credentials, executable-plugin loader, collection admission,
write executor or tenant update installer. Existing provider routes are unchanged.

The JSON Schemas use Draft 2020-12. Trusted code loads only bundled schemas, checks
their pinned SHA256 identities and applies explicit UUID/timestamp format checks.
RFC 8785 supplies canonical bytes; exact decimals travel as canonical decimal
strings. A validated envelope establishes structure and pinned mapping consistency,
not input truth, source authenticity, entitlement, consent or receipt issuance.

Source bytes remain an independent private evidence object. They are not embedded
in normalized output or exceptions. Source SHA256 and normalized SHA256 cover
different byte domains. Callers must authenticate the capture, verify tenant/account
and immutable source-receipt binding, enforce retention, and perform atomic admission
before any normalized result enters assessments. That live admission is not shipped.

The initial adapters extract identity and provider-declared display name from one
QuickBooks sandbox CompanyInfo or Microsoft Graph organization response. They do
not assert that an accounting company and directory tenant are the same entity,
establish legal identity, inventory permissions, or establish full account coverage.
The Microsoft adapter supports the existing id-only response: a missing displayName
remains missing. No wider Graph permission or query change is introduced.

Provider JSON may contain additional fields; they remain in raw evidence and are
not automatically interpreted. Normalized core fields are closed. Unknown adapter,
schema, profile, mapping or configuration versions fail closed. v1 is a narrow
entity-descriptor profile; later financial/grant domains require separately reviewed
concept registries and mappings, not a universal synonym table.
