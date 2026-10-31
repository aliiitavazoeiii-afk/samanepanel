# V113 — Third production unit-cost calculator

Parent: `v112-tailor-delivery-destination` (V111 product catalog, V110/V108 baseline preserved).

Add a third calculator card alongside the two existing pricing tools at `/calculator/`, with six editable inputs:
- fabric price per kilogram (toman)
- one fabric roll's weight (kilograms; default 20)
- pieces cut per roll (default 750)
- elastic consumed per roll (kilograms; default 5)
- elastic price per kilogram (toman)
- sewing wage per dozen = 12 pieces (default 110,000 toman)

Live browser-only result:
`fabric_per_piece = fabric_price_per_kg × roll_kg / pieces`
`elastic_per_piece = elastic_price_per_kg × elastic_kg / pieces`
`sewing_per_piece = wage_per_dozen / 12`
`unit_cost = fabric_per_piece + elastic_per_piece + sewing_per_piece`.

Also shows the total cost attributable to a roll's cut output (including proportional sewing). Inputs must be nonnegative; roll weight and piece count must be positive. No database writes, pricing changes, inventory changes, material formulas or persistent state.

Regression `check_production_unit_cost_v113` checks all three calculator cards, defaults, live-formula expressions and an independent Decimal example (20kg×250000 + 5kg×150000)/750 + 110000/12 = 16833.33 toman.

Production confirmation marker:
`SUCCESS: PRODUCTION UNIT COST CALCULATOR V113 DEPLOYED`

Future features should continue from V113 after successful deployment rather than older branches.
