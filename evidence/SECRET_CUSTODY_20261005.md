# Secret Custody Inventory (Metadata Only)

Prepared 2026-10-05 for the Stewardence context handoff.

This file contains **no secret values**. The assistant has no credential or private-key value to transfer into a file. It must not be treated as a vault or as proof that any listed credential is valid.

## Known references and evidence

- Stripe sandbox credential file supplied by Alexander: `C:\Users\alexg\Downloads\New folder (3)\stripetest.txt`. Its observed size was **0 bytes**. No key or webhook secret was read from it.
- Earlier handoff reported a `sk_test` class secret in a separate DOCX, but it was not re-opened for this handoff. A secret-key class alone does not establish restricted-key scope, account identity, test-mode authorization or a matching webhook signing secret.
- Windows recovery key custody is user-managed at the previously designated local recovery-key location. Its value was neither read nor copied for this work. Keep the key out of the Droplet, containers, this workspace and chat.
- Encrypted backup ciphertext was reported/verified in Ubuntu WSL custody on the Windows machine. That WSL distribution and the Windows-held key share one physical device; this does not prove survival of device loss.
- Lyra bridge kits and identity keys were reported revoked by Alexander after a failed connection. No old kit/token/key is retained here; do not reuse it.

## Handling rule

When a specific sandbox credential is required, Alexander should place the minimum-scope value and matching webhook secret in an approved local secret store and provide only its path/readiness signal. Never print values, put them in command arguments, commit them, copy them to evidence, or embed them in handoff documents. Production credentials are not requested or required for current offline qualification.
