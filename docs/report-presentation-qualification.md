# Report presentation successor

Atlas/schema reconciliation precedes this change; see
`report-atlas-schema-alignment.md`. The successor keeps calculation engines,
context schema, original snapshots and existing artifact bytes intact. Browser
styling now restores the phone-width workspace menu and constrains report grid
width so only wide tables scroll. Phone (390), tablet (768) and desktop (1280)
browser measurements show no page-wide horizontal overflow in the synthetic
report. The menu opened and navigated to recovery controls. Evidence is under
`evidence/visual-qa`.

The printable report uses the supplied decorative Reports emblem, navy text,
blue information panels and white/light-blue tables. ROI starts on its own page;
immutable technical metadata occupies a deliberate appendix page. All four pages
of the final single-tool unknown-ROI specimen were rendered with Poppler and
visually inspected. No clipping, broken glyphs or orphaned final ruleset line
was observed in that specimen. Unknown value and net value remain unknown while
the known cost component remains visible. This does not qualify every possible
long-table or customer-input layout.

The final layout's 36 focused checks passed in
`20261003T224123.550152Z`, image
`sha256:89d7868be0b9be2f92281d03919d3fec7289bebb65bca353ef5535d030358938`.
The test exercised actual Chromium and independent renders with identical bytes.
Earlier full run `20261003T223829.697018Z` passed 1,146 with one inapplicable skip
but precedes the appendix page-break adjustment. The final presentation source
passed 1,146 tests with one intentional skip in `20261003T224551.665720Z`, image
`sha256:4049b2b5b577772d1d78cd8710b0ef8c6cb106623ce7c367f336d960738321bf`.
All six restored report objects also passed the restricted-role request probe
against that image at 22:54:20 UTC, including corruption, missing-object,
tenant-boundary and post-request metadata checks. This is in-process request
qualification, not production HTTP. Subsequent standard-only billing changes
require their own exact-source qualification.

The separate renderer-only image is
`sha256:45e9b2c15b940d94f9d8bd60ce4127d394fc6813223cd063b87ce2a2c75895a2`.
It contains the required SVG. Direct actual Chromium qualification used UID
10001, read-only root, dropped capabilities, no new privileges, no network and
bounded tmpfs/memory/pids. Its synthetic specimen rendered twice identically;
unknown values, the known cost and appendix heading checks passed. The first
probe failed because pypdf extracted the footer before the visible heading. The
diagnostic established that order; the corrected check excludes only that exact
footer and still requires the appendix heading first among body lines.

`renderer-package-summary.json` in the focused run records the passing result.
This is renderer execution evidence, not renderer HTTP authentication, end-to-end
worker delivery, live provider admission or production deployment evidence.
