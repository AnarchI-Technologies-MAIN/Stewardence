# V4 release packaging audit

Static source inspection only, following the parent's reported 20-pass qualification including two actual Chromium/private-delivery journeys. No images were built or run for this audit. The qualification receipt is local candidate evidence, not release-image or production evidence.

## Resolved dependency separation

The application Dockerfile copies `apps`, `src`, `templates`, `static` and `collector`, then transfers the entire builder `/app` into its unprivileged runtime. V4 app imports resolve within `apps.reviews` and permanent `apps.assessments` modules; neither `capture_context_v3.py` nor `capture_event_v2.py` imports `renderer`. Required external RFC8785 is a normal project dependency. The new owner include is inside the recursively copied templates directory. Source inspection therefore finds no new v4 app dependency on the separately packaged renderer.

The renderer Dockerfile installs only the renderer dependency group, copies the complete `renderer` tree and the two referenced brand assets, and runs as UID 10001. That recursive copy includes `capture_pack_v4_schema.py`, the v4 HTML template and all six `semantics_v1` modules. Their imports are standard library, RFC8785 or sibling permanent modules. They import no `apps`, database, current policy registry, mutable provenance catalog or live provider code. Renderer Django templates and Playwright are present in its explicit dependency group. This is a static packaging conclusion, not a successful renderer-image build/import claim.

Both source and qualification dockerignore files retain these product directories. Release source dockerignore excludes tests/docs/cache; qualification intentionally includes tests and the full source. No runtime implementation was accidentally placed in tests or docs.

## Qualification differs materially from release layout

`Dockerfile.qualification` copies all source into one image and installs default groups containing both development and renderer dependencies, Chromium plus Poppler. It therefore exposes application and renderer packages together and has more tools than either release image. The qualifier freezes and hashes source before building, runs a disposable PostgreSQL database and uses development settings under bounded container resources. The worker tests call `render_pdf` directly in that qualification image through a test renderer object; they do not demonstrate the production HTTP renderer client → isolated renderer service path.

Outstanding release qualification gates: build both actual Dockerfiles from one frozen reviewed source; cold-import v4 application modules in the app image without renderer/dev packages; cold-import renderer v4 with application modules absent; render through the existing `/v1/render` HTTP contract using the real client and response bounds; verify Chromium executable/native dependencies, writable output permissions, timeout behavior and cleanup under deployment container restrictions; run production-settings system checks and staticfiles/template availability with securely supplied local qualification configuration. These are local release-image gates, not permission to deploy or activate services. Database role provisioning/migration and production restore/provider/billing gates remain separately qualified activities.

## Permanent semantics and successor discipline

The vendor modules retain the permanent application module bodies, changing only imports to renderer siblings and lint comments. Focused tests compare meaningful AST bodies and independently exercise frozen accounting failures and rehashed semantic forgeries. Closed app and renderer v4 validator bodies are also compared. Literal field provenance and permanent accounting/profile/policy/exposure/proposal versions keep current aliases out of these paths.

This duplication creates a future maintenance obligation: changing either permanent copy in place would alter meaning for existing v4 packs. Introduce new semantic module/version plus pack/context dispatch for actual semantic changes, leaving old copies available. Do not “synchronize” historical copies to newer current aliases. AST equivalence proves source consistency between copies at qualification time; it does not prove every input truthful or establish database issuance. Helper-specific resource/timestamp behavior and actual image dependency resolution still require boundary tests, rather than inferring everything from equal central validator bodies.

Old pack v2/v3 closed schema branches remain separate. No defect in their unchanged historical semantics was established by this packaging audit. No stronger production readiness claim follows from it.

## Later attempted release-image qualification: still failed

Receipt `evidence/release-renderer/20261005T004353.285638Z` is a retained failed successor attempt. The actual headless Chromium launch/close probe and actual application production-settings check succeeded. Both positive HTTP specimens execute before the malformed-payload negative: the receipt contains generic `other.pdf` (94,234 bytes) and accounting `accounting_bookkeeping.pdf` (96,949 bytes), with their synthetic input JSON. These are successful positive client calls, not proof of database issuance.

The negative reached the renderer and correctly received HTTP 422 for an unsupported schema. The harness incorrectly asserted HTTP 400, so it failed before writing `http-results.json` and before running the separate semantic PDF verifier. Cleanup was verified. The fixture expectation was subsequently corrected to the server's existing schema-validation contract; no server behavior changed. Preserve this failed receipt and distinguish its successful intermediate observations from a complete harness pass. Earlier receipt `20261005T002146.594208Z` also remains failed because its probe checked the full-browser path despite a headless-shell-only installation. No overall release qualification or production readiness claim follows from either attempt.
