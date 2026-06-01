# Tier 0 — Implementation Notes

## SIGN_RESTRICTION reform deferred to Tier 1

The Tier 0 spec called for removing F5×precious_metals, F7×global_duration,
F7×precious_metals SIGN_RESTRICTION entries (dash-for-cash contradictions per
Brunnermeier-Pedersen 2009).

These bucket names exist only in the 8-bucket schema (Tier 1). In current
5-bucket schema (fx_commodity, bond), these specific cells don't exist.
Therefore SIGN_RESTRICTION cleanup is **deferred to Tier 1** Task 4 where
the 8-bucket SIGN_RESTRICTION dict is built fresh.

No action needed in Tier 0.
