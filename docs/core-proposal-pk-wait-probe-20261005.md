# Proposal issuance: final insertion wait probe

Status: executed same-role authority finding; repair pending. This does not reopen the closed historical capture or legacy issuer findings.

Evidence: `20261005T011703.013504Z` executed the probe. The controlled PK wait and committed revocation were established; paid/work authority were both false before release, but the target returned an admitted revision. The denial assertion failed. This finding is demonstrated within the tested same-role scope; its repair remains pending.

The public proposal issuer accepts a caller-selected revision UUID and checks authority after its cooperative locks but before insertion. An uncommitted, genuinely issued revision in another organization can collide on that global primary key. Its transaction can hold the target insertion after the last authority check; cancellation can then commit before the competing transaction rolls back and releases the insert.

`source/tests/test_capture_proposal_pk_wait_authority.py` stages the foreign revision through the actual application issuer, proves the target application's backend is blocked by that foreign transaction, commits cancellation, observes paid authority false, then rolls back the blocker. It requires target denial and no effects. There are no counterfeit rows, clock tolerances or retries.

The successor migration must recheck authority after all potentially waiting persistence effects, preserving transaction rollback, lock ordering and historical migrations. Qualify both denial after revocation and ordinary issuance/replay, then submit exact evidence to Lyra. Production remains unchanged.
