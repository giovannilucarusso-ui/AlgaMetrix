# Waste-derived nutrients and carbon

A culture grown on somebody else's effluent gets its nitrogen without a Haber-Bosch plant
behind it. That is worth a great deal to both results, which is exactly why the rules producing
it are written down here rather than left implicit in a spreadsheet.

Configured on the scenario as `waste_feed` ([`models.WasteFeed`](../src/algametrix/models.py));
the shipped streams are in [`data/waste_feeds.yaml`](../data/waste_feeds.yaml), each with its
source. Off by default — every result produced before this existed is reproduced exactly.

## 1. What a waste feed changes, and what it does not

**It does not change what the biomass needs.** The nitrogen demand is fixed by the organism's
composition and the culture's uptake efficiency, and it is untouched. What moves is the
**purchase**:

| Quantity | Meaning | Used by |
|---|---|---|
| `nitrogen_per_kg` | the demand — unchanged | the mass balance and its identities |
| `nitrogen_from_waste_per_kg` | the part the stream delivers | reporting |
| `nitrogen_purchased_per_kg` | the part still bought | **cost** and the **fertiliser-production burden** |
| `nitrogen_surplus_per_kg` | delivered beyond the demand | discharged; enters eutrophication |

Cost and impact are computed from the purchased quantity, because the fertiliser factors
describe *making fertiliser*. With no waste feed the purchased quantity **is** the demand and
every number is what it was.

## 2. One stream has one composition

The quantity dosed is fixed by a single demand — `dosed_on`, one of `nitrogen`, `phosphorus`,
`substrate` — scaled by `coverage`. Whatever the same quantity carries of the other two then
follows from the stream's own composition:

```
q_ws = coverage × demand(dosed_on) / concentration(dosed_on)
delivered(j) = q_ws × concentration(j)
purchased(j) = demand(j) − min(delivered(j), demand(j))
surplus(j)   = max(delivered(j) − demand(j), 0)
```

Letting the user dial coverage of nitrogen *and* phosphorus independently would describe a
stream nobody can buy. Municipal effluent is phosphorus-rich relative to what a culture takes
up, so a nitrogen-dosed dose **over-delivers phosphorus** — and that surplus is discharged, so
it is reported and it enters freshwater eutrophication. It is the honest cost of the choice and
the model does not hide it.

Two settings do nothing, deliberately and visibly: a stream dosed on something it does not
carry, and a stream dosed on a demand the scenario does not have (whey permeate, dosed on
substrate, fed to a phototrophic pond). Neither silently falls back to another nutrient. The
desktop app says which case it is; `verification.py` carries the admissibility checks.

## 3. Money

`price_per_unit` is EUR per m³ or per kg of stream, and **negative means a gate fee**: the plant
is *paid* to accept the stream, which is how a works treating municipal effluent earns. It is
its own line in the operating cost, never netted into the nutrient lines, so a reader sees both
the fertiliser not bought and the money the stream brings.

Waste is not automatically cheap. Sugar-beet vinasse is a traded fertiliser and animal feed, so
its price is positive; a stream can easily cost more than the fertiliser it saves, and the model
is able to say so.

### The treatment service is separate money

A works may be paid €0.15/m³ to accept effluent while displacing €0.30/m³ of conventional
treatment. Only the first is invoiced. `avoided_treatment_cost_per_unit` carries the second, and
the two never merge:

| | enters the AOC? | enters the production cost? | enters net cost & profit? |
|---|:---:|:---:|:---:|
| `price_per_unit` (gate fee) | yes | yes | yes |
| `avoided_treatment_cost_per_unit` | **no** | **no** | yes |

The credit stays out of the annual operating cost because no money changes hands for it. A
production cost that quietly nets off a service the plant was never paid for is not a production
cost — nobody could reproduce it from an invoice — so it sits with the co-product credits, in
`net_production_cost_eur_per_kg` and in the profit, and is reported on `TEAResult`
as `avoided_treatment_credit` so it can be taken back off.

## 4. One convention, both analyses

`WasteBurdenConvention`, on the feed:

- **`cut_off`** (default) — the waste enters burden-free: its producer carries everything up to
  the point of discard, and this system carries only what it does itself (`gwp_per_unit`,
  `ced_per_unit`, and the pumping electricity). This keeps a cradle-to-gate result comparable
  with studies that buy fertiliser.
- **`avoided_treatment`** — system expansion. The stream would have been treated and discharged,
  so the treatment displaced is credited — **its emissions in the LCA and its cost in the TEA**.
  This makes the result **a difference between two systems** rather than the footprint of one.

`convention` governs *both* analyses, deliberately. Crediting the displaced treatment in the LCA
while ignoring it in the economics would have the two describe different systems, which is the
failure this engine exists to prevent: one boundary, one inventory, two contractions of it. The
same is true in reverse, and `tests/test_waste_feed.py` requires a catalogued stream to declare
the avoided burden and the avoided cost together or neither.

Both credits are reported on their own lines — `Avoided treatment (system expansion)` in the GWP
breakdown, `avoided_treatment_kg_co2eq_per_kg` and `avoided_treatment_credit` on the two results
— and both are kept **outside the gross**, exactly as the biogenic-carbon credit is, so a reader
who disagrees with the convention can add them back. Under `cut_off` neither is applied, however
large the `avoided_treatment_*` figures on the stream happen to be.

It can drive the net GWP below zero. That is a legitimate system-expansion outcome and it is
labelled as one; it is not a claim that growing algae removes carbon.

## 5. What holds it together

- **Identities** ([`verification.py`](../src/algametrix/verification.py)): the demand equals
  purchased plus from-waste, for N, P and substrate; the stream delivers exactly what its
  composition says, used plus surplus; and everything entering the culture leaves it assimilated
  or emitted, surplus included.
- **Shared-flow consistency** ([`consistency.py`](../src/algametrix/consistency.py)): the
  received stream is a shared flow like any other. Its quantity is recovered independently from
  the cost result and from the impact result, and the two must agree.
- **An independent implementation** ([`paper/matrixlca.py`](../src/algametrix/paper/matrixlca.py)):
  the matrix formalism carries the same feed as a background process and the credit as its own
  elementary flow, and is checked against the sequential engine to 1e-9 under both conventions.
- **The printed equations** ([`paper/specification.py`](../src/algametrix/paper/specification.py)):
  `inv.waste` and `inv.nutrients.purchased` restate the dosing and the split from the scenario
  and are compared against the engine on every scenario in the suite.

## 6. Worked comparison

`Whole biomass — food (Chlorella, raceway)` against
`Biomass on municipal wastewater (raceway)`, the same organism and pond, both shipped templates:

| | conventional | on municipal effluent |
|---|---:|---:|
| Production cost | 6.145 €/kg | **5.808 €/kg** |
| GWP | 0.952 kg CO₂-eq/kg | **0.177 kg CO₂-eq/kg** |
| CED | 47.20 MJ/kg | 43.59 MJ/kg |
| Effluent received | — | 2.47 m³/kg |
| Phosphorus discharged | — | 0.0037 kg/kg |

Switching the same case to `avoided_treatment` moves it further, and moves both results at once:
the net production cost falls from 5.53 to 4.79 €/kg on a credit of €440k/yr, while the GWP goes
to −0.687 kg CO₂-eq/kg. The gross production cost does not move at all. A net GWP below zero is a
legitimate system-expansion outcome and is labelled as one; it is not a claim that growing algae
removes carbon.

Nitrogen leaves the GWP contribution list entirely — it was the largest term after energy. The
cost falls much less than the footprint does, because fertiliser was never the cost driver;
electricity, drying heat and capital were. The extra phosphorus discharge is the price.

The effluent intensity is a useful check: 2.47 m³ per kg of dry biomass here, against roughly
2.86 m³/kg implied by the Intelligen wastewater biostimulant case
([10.13140/RG.2.2.11499.71202](https://doi.org/10.13140/RG.2.2.11499.71202)), which was modelled
independently in SuperPro Designer.
