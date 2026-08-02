# Validation & transparency

`AlgaMetrix` is validated on three independent levels: against a proprietary process
simulator (SuperPro Designer), against published techno-economic studies, and against
open-access literature benchmark ranges. Every reference below is citable. All model
figures are reproduced by the scripts in [`examples/`](../examples); prices are USD (≈EUR).

> The defaults are literature-typical placeholders — validation shows the *methodology*
> is sound and the numbers are *plausible*, not that any single scenario is exact.

## 1. Against SuperPro Designer (calibrated cases)

Deviation of the model from the SuperPro reference (model − reference):

| Case | Script | Unit cost | Total investment | Annual output |
|------|--------|:---------:|:----------------:|:-------------:|
| Omega-3 oils fermentation (INTELLIGEN) | `omega3_fermentation.py` | +6 % | +5 % | +2 % |
| Heterotrophic microalgae powder | `heterotrophic_powder.py` | +5 % | −5 % | −1 % |
| Phototrophic algal-oil biorefinery | `phototrophic_algal_oil.py` | +1 % | +9 % | +3 % |

The phototrophic OPEX is ~16 % high because that plant's anaerobic-digestion energy
recovery (a ~$16M/yr credit) is only partly represented.

## 2. Against published techno-economic studies

| Product | Script | Model | Published |
|---------|--------|:-----:|-----------|
| C-phycocyanin (Spirulina) | `phycocyanin_biorefinery.py` | $383/kg | €283–544/kg; unprofitable at €170–280/kg market ¹ |
| Astaxanthin (Haematococcus) | `astaxanthin_biorefinery.py` | $932/kg | ~$718/kg; €1122–3247 by location; $500–1500/kg powder ² |
| Single-cell protein (Chlorella) | `microalgae_protein.py` | $5.89/kg; 29.7 t protein/ha/yr | 5.5–6.1 €/kg (2028); 22–44 t protein/ha/yr ³ |
| Biodiesel (Nannochloropsis) | `biodiesel_algae.py` | $1.45/L | NREL $0.42–0.97/L; for-profit MDSP < $1.85/L ⁴ |

¹ The model correctly reproduces the literature finding that food-grade C-phycocyanin is
not profitable at current market prices.  ⁴ Algal biodiesel is famously not yet
cost-competitive; the model reflects that (above the aggressive NREL target, below MDSP).

## 3. Against open-literature benchmark ranges

**Validation → Check open-literature benchmarks** flags whether per-kg-biomass metrics sit
inside published ranges ([`data/benchmarks.yaml`](../data/benchmarks.yaml)). The default
raceway, PBR and Spirulina scenarios fall within **every** range:

| Metric | Open pond | PBR |
|--------|-----------|-----|
| Production cost ($/kg) | 0.5–9.6 | 1.7–15 |
| GWP (kg CO₂-eq/kg) | 0.2–30 | 1–153 |
| Energy demand (MJ/kg) | 5.8–100 | 50–1000 |
| Electricity (kWh/kg) | 0.5–10 | 3–267 |
| Water (m³/kg) | 0.4–10 | 2.4–6.8 |

Indicative product prices for sanity-checking selling prices are in
[`data/market_prices.yaml`](../data/market_prices.yaml) (**Validation → Market price reference**).

## Sources

- Davis et al. 2016, *Process Design and Economics for the Production of Algal Biomass*,
  NREL/TP-5100-64772 — https://docs.nrel.gov/docs/fy16osti/64772.pdf
- NREL/TP-5100-72716, closed photobioreactors — https://docs.nrel.gov/docs/fy19osti/72716.pdf
- Gueguen et al. 2024, *Industrial-scale photobioreactors LCA*, Sustainable Production and
  Consumption — https://www.sciencedirect.com/science/article/pii/S2352554124001736
- Rahman et al. 2023, *Co-production of bioplastic and food supplements from Spirulina*,
  Scientific Reports 13:10387 — https://www.nature.com/articles/s41598-023-37156-3
- van der Walt et al. 2025, *Commercial C-phycocyanin process*, J. Applied Phycology —
  https://link.springer.com/article/10.1007/s10811-025-03443-x
- Panis & Carreon 2016, *Commercial astaxanthin from Haematococcus pluvialis*, Algal Research —
  https://www.sciencedirect.com/science/article/pii/S2211926416301965
- INTELLIGEN, *Production of Omega-3 Fatty Acids via Microalgal Fermentation* (SuperPro example)
- Water footprint of PBR cultivation (2018) —
  https://www.researchgate.net/publication/328896620_Water_footprint_of_microalgae_cultivation_in_photobioreactor
- Downstream-processing review 2024, Microorganisms 14:1393 — https://doi.org/10.3390/microorganisms14071393
