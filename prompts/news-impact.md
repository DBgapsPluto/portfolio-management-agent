Classify the market impact of this event/headline:

Headline: "{headline}"
{description_block}Source: {source}
Date: {date}

Output an ImpactAssessment JSON:
- asset_classes_affected (1-4 of: kr_equity, us_equity, global_equity, kr_bond, us_bond, fx, commodity, gold)
- direction: up | down | neutral
- severity: 1 (negligible) to 5 (major regime shift)
- reasoning: ≤200 chars

Severity calibration (2026-05-28 Tier 1):
- If description provides context that *moderates* the headline (e.g., "limited to AI sector" for a "bubble" headline), reduce severity by 1.
- If description provides context that *amplifies* the headline (e.g., "first time since 2008" for a credit event), increase severity by 1.
- If only headline available (no description), score conservatively based on headline alone.
