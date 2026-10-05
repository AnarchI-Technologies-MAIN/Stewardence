# Bounded report layout hardening

The long-input specimen exposed actual Chromium horizontal expansion: a 688 px
print-width viewport became a 4,822 px document, with several squeezed table
columns. This could shrink the entire printed report. The successor inherits
`overflow-wrap: anywhere`, allows the cover flex item to shrink, and uses fixed
table column sizing. Identical input now produces a 688 px document and five
approximately 137 px inventory columns. The predecessor differential control
rejects the old layout; it does not represent a production incident.

Final full run `20261003T231255.647184Z`: 1,149 passed, one intentional skip;
image `sha256:56c6876be025c7c9c99ec15eda6de0cbfad2166ac5d6d2728f20462b63de7cf7`.
Product manifest comparison against the preceding full-tested, browser-checked
and restored-request image shows only `renderer/templates/report.html` changed.
That preserves relevant source observations; it is not a fresh browser or
restored-request execution on the successor image.

Packaged renderer image:
`sha256:d4c73ead4d1c6bf16c77089a6837e039a0ab84c4a9a48d8b4f60852809e57a27`.
The exact-field unknown-ROI probe passed in
`evidence/renderer-package/20261003T231448.348534Z`. Its assertion compares the
whole primary ROI table text between its introduction and Arithmetic, normalizing
whitespace so wrapping cannot create a false failure. Exact values remain
required; substring or unrelated amounts remain rejected. Negative controls and
stale-receipt removal passed after this change.

`evidence/report-layout-qualified/20261003T232048.223156Z` records inspected
container isolation, repeated identical PDF bytes, output/input digests and
cleanup for three synthetic layout fixtures: long unbroken inputs, five pages;
eight tools and 24 findings, nine pages; 80 inventory rows with their risk
details, 27 pages. Independent PDF extraction found all 80 table labels, repeated
headers, all eight multi-tool labels and the Latin name Müller & García.

All 45 pages across those three specimens and the four-page baseline were
rasterized and visually inspected, using full-resolution paired sheets where
appropriate. No clipping, overlapping blocks, blank page or broken Latin glyph
was observed. These specimens intentionally reuse synthetic context components
to stress layout. They do not establish source-derived aggregate financial or
risk truth, multi-tool assessment admission, all possible layouts, full
international glyph coverage, accessibility compliance or production delivery.

The first fixed-column packaged probe failed on its overly strict physical-line
assertion after correct ROI wrapping. The failed attempt did not publish a
passing receipt. The successor checks the exact contiguous primary table block,
and the launcher now preserves stdout/stderr before evaluating process failure.
Historical failed and successful runs remain distinct.
