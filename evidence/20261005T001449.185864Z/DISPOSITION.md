# Qualification disposition

This frozen candidate produced 120 passes and seven failures. Migration 0007 compiled and its positive unused-stop, replay, expiry/pause and several authority negatives executed. This is not an overall passing qualification.

Six failures involved fixtures: owner-context refresh, two stale activity-snapshot barriers, an incorrect expected overflow message, a generic navigation label used as a privacy assertion, and CSRF acquisition from an unpaid foreign workspace. The overflow was rejected by the earlier queue canonicalizer; the admitted oversized freeze succeeded, but the rest of that failed test did not execute. Successor tests must prove recovery after this rejection.

The seventh failure was the repeated legacy UI admission test's future-time guard. Previously observed WSL wall-clock reversals remain an open infrastructure finding. No tolerance, retry or guard was weakened.

Repairs require a separately frozen successor receipt. Passing individual tests cannot erase these failures or establish production readiness. Production was untouched.
