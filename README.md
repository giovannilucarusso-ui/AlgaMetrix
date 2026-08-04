# AlgaMetrix

[![tests](https://github.com/giovannilucarusso-ui/AlgaMetrix/actions/workflows/tests.yml/badge.svg)](https://github.com/giovannilucarusso-ui/AlgaMetrix/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21764183.svg)](https://doi.org/10.5281/zenodo.21764183)

**Open-source techno-economic analysis (TEA) and life-cycle assessment (LCA) for microalgae and aquatic protist biomass.**

Existing TEA/LCA tools (SuperPro Designer, SimaPro, GaBi, Aspen Plus) are proprietary, expensive, and
generic. `AlgaMetrix` is a free, transparent, and reproducible alternative focused specifically on
photo- and heterotrophic cultivation of microalgae, cyanobacteria, and thraustochytrids/protists.

It is a **desktop application** (PySide6/Qt) built on a small, UI-agnostic calculation engine.
Everything is computed from an explicit **process model** (mass & energy balance); the economic and
environmental results are derived from the *same* inventory, so TEA and LCA always stay consistent.

## What it does

For a user-defined production scenario it computes, from a single mass/energy balance:

- **Process inventory** — per kilogram of dry biomass: electricity, heat (incl. optional fuel-switchable
  **cultivation/greenhouse heating**), inorganic carbon (CO₂ gas **or** sodium bicarbonate / NaHCO₃),
  N, P, water, organic substrate (heterotrophic), and land.
- **Techno-economic analysis** — a SuperPro-style capital structure (equipment → installed → direct
  fixed capital → total investment incl. working capital & start-up), an annual operating cost split into
  raw materials, utilities, labour and facility-dependent cost (depreciation + maintenance + insurance),
  and the **minimum biomass production cost (€/kg)** with a full cost breakdown.
- **Profitability** — revenues, gross/net profit, ROI, payback, **NPV**, **IRR** and the
  **minimum expected product price (MEPP / break-even selling price)** from a discounted cash-flow model.
- **Downstream extraction & co-products** — optional cell disruption + solvent extraction splitting the
  biomass into a **main product** and **co-products**, with **cost and environmental-impact allocation**
  (economic, mass, or SuperPro-style "all cost to the main product"). The **target product** is
  selectable — **oil / lipid** (e.g. omega-3 PUFA) or **protein** — so the same biomass can be evaluated
  for an oil-first or a protein-first biorefinery. The functional unit becomes 1 kg of the main product.
- **Life-cycle assessment** — cradle-to-gate **Global Warming Potential (kg CO₂-eq)**, **Cumulative
  Energy Demand (MJ)**, **water use (m³)**, **land use (m²·a)**, **marine & freshwater eutrophication**
  and **acidification** per kg of biomass, with GWP contribution analysis.
- **Sensitivity analysis** — sweep any key input (scale, product price, productivity, discount rate, …)
  and plot how production cost, NPV or GWP respond.
- **Uncertainty analysis** — Monte-Carlo propagation of several uncertain inputs at once, giving the
  P10 / P50 / P90 distribution of any output.
- **Scenario comparison** — snapshot several cases (strains, systems, configurations) and compare their
  KPIs side by side.
- **Validation** — compare your results against an external reference such as **SuperPro Designer**;
  two real SuperPro cases are bundled (see below).

Raw materials and utilities are fully itemised: on top of the physics-derived flows (CO₂, N, P, glucose,
water) you can add explicit media components and chemicals (yeast extract, nitrate, hexane, flocculant, …)
and utilities (sterilization steam, cooling / chilled water), each with its own price and LCA factors —
so a real fermentation recipe (where e.g. yeast extract dominates the material cost) is represented faithfully.

**Fully configurable, no coding required.** In the desktop app you can define your own media recipes and
products through built-in table editors, and switch between **continuous** production and **batch mode**
(batch size + cycle time → batches/year), so the same tool fits an open-pond biofuel plant and a
sterile fed-batch fermentation alike.

Cultivation systems built in: open raceway pond, tubular PBR, flat-panel PBR, bubble-column/airlift PBR,
thin-layer cascade, a bicarbonate-fed **Spirulina** raceway (NaHCO₃ carbon source, calibrated to Padi
et al. 2023), and a stirred-tank **heterotrophic** fermenter (thraustochytrids on organic carbon).
Phototrophic systems can draw carbon from **CO₂ gas** or **dissolved sodium bicarbonate (NaHCO₃)** — the
latter is how alkaliphilic *Arthrospira* (Spirulina) is actually grown at pH 9–10.

## Design principles

1. **One source of truth** — TEA and LCA read the same physical inventory.
2. **Transparent data** — every organism, cultivation system, price and characterization factor lives in
   editable, citable YAML files under [`data/`](data/). No hidden numbers.
3. **Reproducible** — the engine is pure Python; a scenario is a plain object you can build in a script,
   a notebook, or the desktop app.
4. **Extensible** — new systems, impact categories, or downstream processes are added by editing data or
   adding a small module.

> ⚠️ The default parameter values are literature-typical **placeholders** meant to make the tool run out
> of the box. They are **not** validated for any specific plant. Replace them with your own data — and
> validate against SuperPro — before drawing conclusions.

## Quick start

```bash
# 1. (recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux

# 2. install
pip install -r requirements.txt

# 3. run the desktop app
python run_desktop.py
```

On first launch you choose a **language** (English, Italian, Spanish or French — remembered for next
time, changeable from **Help → Language**), then a **7-step setup wizard** helps you build your case
study: start from the closest validated example (or from scratch), pick the product goal, organism (with
**full editable composition** — protein/lipid/carbohydrate/ash and C/N/P), cultivation system and scale
(by target tonnage **or** by plant size), downstream, and **regional** economic/energy context (12 grid
presets with country electricity price and carbon intensity), then open the scenario in the full tool.
"Skip to full tool" bypasses the wizard; **File → New case study (wizard)** reopens it.

A web version (Streamlit) is also available: `streamlit run app/streamlit_app.py`.

## Validation & transparency

The tool is validated on three independent levels — against SuperPro Designer, against
published techno-economic studies (omega-3, phycocyanin, astaxanthin, single-cell protein,
biodiesel), and against open-access literature benchmark ranges. See **[docs/VALIDATION.md](docs/VALIDATION.md)**
for the full table with deviations and sources.

## Validating against SuperPro Designer

SuperPro's project files (`.spf` / `.dyn`) are a proprietary binary format that this tool cannot read.
Validation therefore works from data you **export** from SuperPro for the *same* process:

**Bundled cases.** Three real SuperPro references ship with the app and are one click away under
**Validation → SuperPro: …**, each with a calibrated example that reproduces it:

| Case | Example | Unit cost | Total investment | Annual output |
|------|---------|-----------|------------------|---------------|
| Omega-3 oils fermentation (INTELLIGEN) | `examples/omega3_fermentation.py` | +6 % | +5 % | +2 % |
| Heterotrophic microalgae powder | `examples/heterotrophic_powder.py` | +5 % | −5 % | −1 % |
| Phototrophic algal-oil biorefinery | `examples/phototrophic_algal_oil.py` | +1 % | +9 % | +3 % |

For a biorefinery the production cost and annual rate are compared for the **main product** (e.g. the
oil), matching how SuperPro reports against its "Main Product/Revenue" stream.

**Open-literature benchmarks.** Beyond SuperPro, **Validation → Check open-literature benchmarks**
compares the scenario's per-kg-biomass production cost, GWP, energy demand, electricity and water use
against **published, citable ranges** (NREL techno-economic reports, peer-reviewed LCA studies) held in
[`data/benchmarks.yaml`](data/benchmarks.yaml) — each with its source — and flags whether the model
sits inside the literature range. The default raceway and PBR scenarios fall within every range.
**Validation → Market price reference** shows indicative product price ranges
([`data/market_prices.yaml`](data/market_prices.yaml): biomass, Spirulina, C-phycocyanin, astaxanthin,
omega-3 oil, protein meal) so selling prices can be sanity-checked. A food-grade Spirulina example
([`examples/spirulina_foodgrade.py`](examples/spirulina_foodgrade.py)) is validated purely against these
open benchmarks — no proprietary reference needed.

Processes that recover energy or valorise waste (anaerobic digestion, heat recovery) can carry an
operating-cost **credit** that lowers the net production cost and improves NPV — the mechanism SuperPro
uses for such savings.

**High-value pigment biorefineries** are covered too: [`examples/phycocyanin_biorefinery.py`](examples/phycocyanin_biorefinery.py)
lands C-phycocyanin at ~$383/kg (published €283–544/kg, and correctly unprofitable at the €170–280/kg
market price) and [`examples/astaxanthin_biorefinery.py`](examples/astaxanthin_biorefinery.py) lands
astaxanthin at ~$930/kg (published ~$718/kg; $500–1500/kg powder market). Minor high-value fractions are
modelled with an explicit yield and price, and economic allocation loads the cost onto the target product.

**Option A — reference CSV (always works).** Copy [`data/superpro_reference_template.csv`](data/superpro_reference_template.csv),
fill the `value` column from any SuperPro report, then in the app open
**Validation → Load reference CSV…**.

**Option B — Excel report (best-effort).** In SuperPro, export the *Economic Evaluation Report* to Excel,
then use **Validation → Import SuperPro Excel report…**. The app scans the sheet for labels such as
"Total Capital Investment", "Annual Operating Cost" and "Unit Production Cost" and pulls the numbers.
Layouts vary between SuperPro versions, so always check the parsed values and fall back to the CSV if a
metric is missed.

The comparison table shows, for each metric, the reference value, this tool's value and the percentage
deviation (green ≤10 %, amber ≤25 %, red >25 %).

## Use it as a library

```python
from algametrix.library import load_library
from algametrix.models import Scenario
from algametrix.scenario import run_scenario

lib = load_library()
scenario = Scenario(
    organism=lib.organisms["Chlorella vulgaris"],
    system=lib.systems["Open raceway pond"],
    harvesting=lib.harvesting["Settling + centrifugation"],
    drying=lib.drying["Spray drying"],
    economics=lib.economics,
    lcia=lib.lcia,
    scale=100_000,  # m² of pond
)
results = run_scenario(scenario)
print(results.tea.production_cost_eur_per_kg)
print(results.lca.gwp_kg_co2eq_per_kg)
```

## Building a standalone Windows .exe

To distribute the app to users without a Python installation:

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name AlgaMetrix ^
    --paths src --paths . --add-data "data;data" ^
    --collect-submodules algametrix --collect-submodules desktop ^
    --hidden-import openpyxl ^
    --exclude-module streamlit --exclude-module plotly ^
    run_desktop.py
```

The app appears in `dist/AlgaMetrix/` — run `AlgaMetrix.exe`. The editable `data/` YAML files are
bundled alongside it. (On macOS/Linux replace `;` with `:` in `--add-data`.)

## Languages

The interface is available in **English, Italian, Spanish and French**. The language is chosen on first
launch and remembered; change it any time from **Help → Language** (restart to apply). Engine-generated
technical labels (flow names, cost/impact breakdown categories) stay in English as a common reference.

## Project layout

```
data/                     editable YAML: organisms, systems, prices, LCIA factors, SuperPro template
src/algametrix/   the engine
  models.py               dataclasses describing a scenario
  library.py              loads the YAML data into objects
  inventory.py            mass & energy balance  ->  Inventory
  tea.py                  Inventory + prices     ->  economic results
  lca.py                  Inventory + factors    ->  environmental results
  scenario.py             orchestrates the above
  validation.py           SuperPro / reference comparison
desktop/                  PySide6 desktop UI (primary)
app/streamlit_app.py      optional web UI
examples/                 scripted scenarios
tests/                    unit tests for the engine and validation
```

## Roadmap

- [x] Phototrophic cultivation (raceway, tubular / flat-panel / bubble-column PBR, thin-layer cascade)
- [x] Heterotrophic cultivation (stirred-tank fermenter for thraustochytrids)
- [x] Core TEA (production cost) and LCA (GWP, CED, water, land)
- [x] Itemised raw materials & utilities (media recipes, steam, cooling water, …)
- [x] Profitability: revenues, NPV, IRR, ROI, payback (discounted cash flow)
- [x] Downstream extraction + multi-product output with cost/impact allocation (economic/mass/none)
- [x] LCA impact categories: GWP, CED, water, land, eutrophication (N & P), acidification
- [x] One-dimensional sensitivity analysis in the UI
- [x] Monte-Carlo uncertainty analysis (P10/P50/P90)
- [x] Side-by-side scenario comparison in the UI
- [x] Desktop app with save/load scenarios and results export
- [x] Validation against SuperPro Designer (3 calibrated bundled cases + CSV/Excel import)
- [x] Open-literature benchmark check (NREL / peer-reviewed ranges, with sources)
- [x] Batch scheduling (batch size, cycle time, batches/yr) alongside continuous mode
- [x] In-app editors for arbitrary media recipes and products
- [ ] Finer product fractionation (individual pigments/PUFA) and quality-based pricing
- [ ] Tornado / global sensitivity (Sobol) analysis
- [ ] Optional [Brightway2](https://docs.brightway.dev/) / ecoinvent background integration

## Contributing

Contributions are very welcome — especially validated inventory data for specific strains and plants.
Open an issue or a pull request. Please cite the source for any numbers you add.

## Citation

If AlgaMetrix contributes to work you publish, please cite it. GitHub's *Cite this repository*
button reads [CITATION.cff](CITATION.cff) and will give you BibTeX or APA directly:

> Russo, G. L. (2026). *AlgaMetrix: open-source techno-economic analysis and life-cycle assessment
> for microalgae and aquatic protist biomass* (Version 1.0.2) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.21764183

Each release is archived on Zenodo. **`10.5281/zenodo.21764183` is the concept DOI**: cite it when
you mean "AlgaMetrix" and it will always resolve to the most recent version. To pin the exact
version you ran, cite its own DOI instead — v1.0.1 is
[`10.5281/zenodo.21796849`](https://doi.org/10.5281/zenodo.21796849) and v1.0.0 is
[`10.5281/zenodo.21764184`](https://doi.org/10.5281/zenodo.21764184).

## License

MIT — see [LICENSE](LICENSE).
