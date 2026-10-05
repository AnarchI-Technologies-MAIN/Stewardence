# QuickBooks sandbox connection candidate — 2026-10-02

Status: candidate only. Not installed on the Droplet. No live Intuit connection,
production approval, accounting import, automatic scheduling, or ROI attribution
is claimed by this change. Xero and Microsoft adapters remain pending.

## Implemented

- Disabled by default, sandbox-only client configuration; explicit owner user-ID
  allowlist. Production client files are rejected. DEBUG must be false.
- GET connect page with CSRF-protected POST consent initiation. Only the
  connecting Stewardence workspace owner can manage the connection. This does
  not independently monitor the user's subsequent QuickBooks administrator role.
- Official discovery lookup with a pinned set of allowed endpoint URLs; a change
  fails closed rather than redirecting credentials to a new host.
- Random 256-bit state bound to workspace, user, session nonce, generation, and
  ten-minute expiry. State is consumed in a committed transaction before token
  exchange. Replays, expired states, duplicate query parameters and wrong sessions
  are rejected. New attempts are rate-limited to one per connection per 30 seconds.
- AES-256-GCM credential envelope includes access token, refresh token and realm ID.
  Associated data binds ciphertext to environment, connection, workspace and actor.
  Client secret and AES keyring are in separate protected runtime files, not the DB,
  repo, image, browser session or logs. Keyring supports retaining old decryption keys.
- Refresh only near access expiry (60-second margin), using the most recently
  persisted refresh token. Row locks serialize refresh/disconnect/callback writes.
  Expired refresh token or invalid_grant commits reconnect-required status.
- Disconnect commits a paused state before remote revocation. Provider failure
  retains encrypted credentials solely to retry revocation, and cannot report
  success. Successful revocation clears credentials. Pending callbacks are fenced.
- Callback always returns an empty-body 302 to a fixed clean page, including framework
  errors and unauthenticated callbacks. No-cache/no-store and no-referrer headers.
- PostgreSQL forced RLS, connecting-owner plus active-tenant checks, immutable
  connection identity, append-only runtime event records, no worker grants.
- No accounting write/delete functions, no external model calls, no automatic
  retries of authorization-code exchanges or invalid grants.

## Qualification boundary

Local Python 3.12 checks use simulated provider responses. Lifecycle tests use
SQLite with the PostgreSQL context setter explicitly substituted; these do NOT
qualify RLS, SQL migrations, PostgreSQL locking, or the actual deployment runtime.
The bundled qualifier runs on Python 3.14 in the existing billing image against a
new internal-network PostgreSQL 18.6 container, with disposable tmpfs data. It runs
migrations, restricted-role checks, billing regressions, OAuth tests and deterministic
ROI foundation tests. It mounts no production volume, reads no production env file,
and does not restart web, renderer, worker, or database containers.

## Required before installation or enabling even sandbox access

1. Run the isolated PostgreSQL qualifier and resolve failures.
2. Confirm the exposed Intuit development secret was rotated. Privately install the
   replacement sandbox client credentials; do not upload them to chat.
3. Establish a reachable HTTPS hostname and register the exact callback:
   https://www.stewardence.com/integrations/quickbooks/callback/
4. Take a fresh backup; review/apply the new migration and middleware changes via
   a separately prepared deployment. Do not overlay this archive on production.
5. Runtime configuration files must be readable only by the app UID, mounted read-only.
   QUICKBOOKS_CLIENT_FILE: JSON environment=sandbox, client_id, client_secret.
   QUICKBOOKS_KEY_FILE: JSON primary=<key identifier>, keys mapping identifier to
   base64-encoded random 32-byte AES key. Generate the key on the server. Never reuse
   the Django secret or OAuth client secret as the encryption key. Keep encrypted
   backup and key custody separate; test restoration together.
6. Set QUICKBOOKS_REDIRECT_URI and QUICKBOOKS_SANDBOX_USER_IDS (explicit owner's UUID).
   Enable QUICKBOOKS_SANDBOX_ENABLED only after configuration and public log checks.
   AUTOMATION_ENABLED remains 0. The allowlist is a private sandbox-testing seam,
   not a production customer entitlement bypass.
7. Confirm proxy, Cloudflare, container, tracing, error-reporting and browser analytics
   do not capture callback query strings, OAuth secrets or QuickBooks data. Django
   callback diagnostic suppression is included; infrastructure logs need their own
   verification. Global HTTPS/caching/unused-method compliance remains separate.
8. Perform actual sandbox consent, disconnect, reconnect, expiry/refresh and denied
   consent checks using the app, and record sanitized outcomes. Company/realm grant
   validation against the accounting API is not yet implemented in this OAuth slice.

## Failure and recovery limits

Network exchanges and database commits cannot be one atomic transaction. If a
process dies after Intuit issues tokens but before the DB commit, the app will not
claim a working connection; remove the grant in Intuit and start a fresh connection.
A successful refresh with a lost response/failed commit may require reconnect.
Remote revocation rejected for an already-invalid token remains pending for explicit
operator reconciliation; no unverified claim of provider revocation is made.
Owner removal blocks runtime access but does not yet run a background revocation job.
No worker can read these credentials. Retention/cleanup policy for attempt/event
records, scheduled retries, account deletion, customer entitlement enforcement,
provider-side disconnect notifications, accounting reads and ROI mapping are future
work before enabling production customer collection.

## Form answers

Do not mark live sandbox testing or full compliance complete based on these tests.
Production Intuit keys are not required to run the isolated qualifier or later sandbox
consent tests. Finish implementation and live qualification before submitting the form.

## Documentation consulted

- User-provided Intuit security requirements, copied 2026-10-02.
- https://developer.intuit.com/app/developer/qbo/docs/develop/sdks-and-samples-collections/ruby/oauth-ruby-client
- https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization/oauth-2.0
  (direct page reader returned a loading page; do not treat that as a full review).

- Sandbox discovery document retrieved and endpoint values verified on 2026-10-02:
  https://developer.intuit.com/.well-known/openid_sandbox_configuration
