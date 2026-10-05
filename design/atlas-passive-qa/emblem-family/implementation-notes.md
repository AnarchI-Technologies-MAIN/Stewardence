# Overview emblem family — implementation notes

Overview master plus Inventory, ROI, Policies, Reports, Evidence Library, Billing, Admin, Funnels, Contact, Pricing, Login and Signup. Native SVG assets, not generated raster approximations. Production assets and templates remain unchanged.

## Specification resolutions

- Coordinates were not supplied for the bands. The renderer defines shared cubic Bézier ribbon contours; these are an interpretation requiring visual review. The filled contours approximate a 48px band; width varies with taper and interlock rather than a constant-width stroke.
- Eye: centered 220×140 quadratic almond, 1.2px mask feather, 70% knockout. This clears bands without painting an independent gaze graphic.
- Screen is used at the overlap. The conflicting overlay instruction is not applied simultaneously. Opacity .92; band blur 2px.
- The tick-ring radius was unspecified: chosen 204px. Base opacity .70, variance ±.08; angle jitter ±1.5°, deterministically seeded per page. The same seed regenerates each signature. These are decorative signatures and do not encode observed completeness, unknowns, or actual measurements. A data-driven version needs a denominator and explicit mapping before implementation.
- Radius 42 outline, 28 cyan filled core with glow, then 18/12/7 nested dark outline hexes at .40/.25/.15 opacity. Nested radii cannot be distinguished reliably at tiny icon sizes.
- Meta ring: radius 110, width 14; .002 idle and .005 hover opacity kept literally. These values are barely visible. No unrequested brightness increase was applied.
- 1.2°/second resolves to 300 seconds per revolution. The supplied 12-second CSS would be 30°/second. The motion SVG uses 300 seconds.
- CSS animation reversal restarts the animation phase; a smooth exit to 0° then clockwise resumption requires a coordinated motion controller. That exit behavior is not implemented here. Static SVGs are the default exports; motion SVGs are optional review artifacts.
- Reduced-motion preference disables rotation. Keyboard focus on the preview triggers the same style as hover. Embedded image SVGs cannot be assumed to inherit host-page hover/focus; inline the optional motion SVG in a reviewed component if used.
- Monochrome exports intentionally remove backdrop, blur, ticks, nested detail and motion; they are compact structural derivatives, not identical full-detail illustrations. Page signatures disappear in this derivative; page labels remain necessary.

## Integration boundary

These assets are reviewable vector artwork, not a complete production qualification. Before adoption: select the final contour, check actual 16/24/32px rendering, confirm motion/opacity intent, coordinate filenames and ownership, collect Django static files, and inspect real pages. No routes, billing logic, integration behavior, security policy, analytics or application flags changed. The revised visual brief allows glow and gradients for this emblem family; the calm application layout remains separate.


## Founder-approved interpretation — subtle living motion

Alexander subsequently delegated the conflicting motion choices and requested movement that is almost imperceptible. The review page now uses a local requestAnimationFrame controller: 1.2°/second, softly eased direction changes, continuous angle without a reset, 1.8% idle / 2.8% hover meta opacity. Reduced motion and hidden tabs stop frame updates. These small opacity increases replace the near-invisible literal percentage only in the living preview. No other layers pulse or move. Optional standalone motion SVGs retain the literal original specification; use the review component and motion.js for the preferred smooth behavior. Production integration remains pending.


## Transparent purple revision

All 39 SVGs now have no painted canvas/background. Color PNGs are re-rendered directly from SVG with native alpha, not white-background removal. Pale cyan replaced by royal-purple highlights: core #8651C9, outline #7441B7, band highlight #9565D5, ticks #8955C6. Navy, deep purple and muted teal remain. White cards and light-blue motion/monochrome wells are review-page backgrounds only, never baked into the assets. motion.js remains unchanged.

Rebuild sequence: build_emblem_family.py → refine_emblem_motion.py → transparent_purple_emblems.py. PNG rendering requires resvg-py; this is a local export dependency, not an application/frontend dependency. Browser screenshot of the review page is an opaque presentation board, distinct from the transparent asset files.
