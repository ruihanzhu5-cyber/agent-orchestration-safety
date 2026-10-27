# Validation scope

The earlier collection code passed 454 unit tests and a real Docker/Pi mock integration. The independent scoring code passed 443 unit tests and its Docker/Pi integration. The new core-only entry point was checked for syntax and exact wire-request equivalence on the three original response fixtures; it did not resend calibration requests. Further broad regressions were not run at the user’s instruction. Actual receipts are alongside this file.
