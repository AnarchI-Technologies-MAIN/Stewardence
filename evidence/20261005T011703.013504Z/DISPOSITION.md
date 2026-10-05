# Executed chosen-ID wait finding

The single actual-role adversarial probe failed its required denial assertion. A foreign application transaction staged a genuine admitted proposal revision at a caller-selected UUID. The target application issuer was observed waiting on that foreign backend's primary-key conflict. Cancellation then committed, and database observations recorded `core_owner_entitled=false` and `core_work_allowed=false` before release.

After the foreign transaction rolled back, the target issuer nevertheless returned an admitted revision. This demonstrates missing authority revalidation after the final persistence wait under the tested same-application-role scope. It is not cross-tenant data disclosure or provider execution.

A successor migration will add a final database authority check after potentially waiting persistence effects, rolling back both revision and receipt on denial. Historical migration and this failing probe remain unchanged. Closure requires executed successor denial, ordinary issuance/replay and role/receipt regressions. Production was untouched.
