# Legacy proposal issuer predecessor probe

Frozen image `sha256:464f472399f33a996198909566e73d9637943c26256dd2b45ebf21df27278632` executed 39 cases: 34 passed and five failed.

All 30 actual-role RLS regressions passed with genuine schema-1 fixtures.

The direct application-role legacy issuer accepted an admitted schema-2 capture instead of denying it. The unresolved-schema probe also lacked the proposed dispatch fence. These are executed admission defects, not cross-tenant exploit claims. The other three failures concern the private delegate that does not exist before the proposed successor migration; they do not establish additional executed exploits.

Successor migration 0015 is required before these nine fence cases can qualify. Preserve the schema-1 function body, ownership and search path; revoke direct access to the renamed helper; validate tenant/actor context before privileged snapshot reads. Production was not touched.
