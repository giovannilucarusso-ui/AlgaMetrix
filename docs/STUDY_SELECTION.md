# Study selection and data extraction

This document describes how the evidence set in `data/studies/studies.yaml` was
assembled, and — more importantly — what about that process is **not** known.

## 1. What this dataset is

A **curated evidence set** of published production-cost and cradle-to-gate GWP
estimates for microalgal, cyanobacterial and thraustochytrid biomass. It is
**not** a systematic review and must not be described as one.

The software enforces this: `meta.is_systematic_search` is `false` in the
dataset, and `results/study_selection_audit.txt` prints that flag together with
`unknown` for every field of the search protocol.

## 2. What is not known about the selection process

The dataset was compiled during the development of AlgaMetrix and the
identification/screening trail was not recorded at the time. The following are
therefore `unknown`, and are reported as `unknown` rather than reconstructed
after the fact:

| Field | Status |
|---|---|
| databases or evidence sources searched | unknown |
| search period | unknown |
| search strings | unknown |
| number of records identified | unknown |
| number screened | unknown |
| number excluded before inclusion, and why | unknown |
| date of the search | unknown |

Consequently **no PRISMA-style flow diagram can be produced**, and the counts in
`results/study_selection_audit.txt` describe the dataset as it now stands (how
many records it contains, how many report a cost, how many a GWP), not a
selection process.

If a systematic claim is wanted for the manuscript, the search must be run and
recorded prospectively; retro-fitting one to this dataset would be fabrication.

## 3. Inclusion and exclusion, as they can be stated

Every record carries `eligibility_status` and `eligibility_reason` describing why
it is in the dataset. These are the *operative* criteria, written down after the
fact from what the records have in common:

**Included** — a published (or vendor-published) estimate of
* production cost, operating cost or a minimum selling price per kg of microalgal /
  cyanobacterial / thraustochytrid biomass or of a product fractionated from it, **or**
* a cradle-to-gate (or explicitly stated other-boundary) GWP for the same.

**Not represented** — anything the compiler did not encounter. Because the search
is unrecorded, absence from this dataset is not evidence of absence in the
literature.

## 4. Multiple scenarios from one publication

Where a source reports several systems or scenarios, each enters as a separate
record with its own `study_id` (e.g. `norsker2011_pond`, `norsker2011_tubular`,
`norsker2011_flatpanel`). This is stated in each record's `assumptions_required`.

Consequences that must be carried into any statistic:

* the 3 Norsker, 2 Acien, 3 Oostlander, 3 Russo, 3 Pechsiri and 2 Maiolo records
  are **not** independent observations;
* `acien2012_real` (a measured plant) and `acien2012_scaled` (its own scale-up
  projection) describe the same facility at two maturities;
* `spiralg2019` and `gwp_spiralg2022` are two inventory years of one pilot.

No statistic in `results/` currently corrects for this clustering. That is a
declared limitation, not an oversight to be hidden.

## 5. Secondary citations and values taken from figures

Not recorded. `data_location_in_source` is `unknown` for almost every record, so
it cannot be established whether a value was read from a table, from a figure, or
from another paper's citation of the source. `results/study_selection_audit.txt`
lists every record with this traceability gap.

Records whose citation resolves only to a publisher PII rather than a DOI
(`gwp_spirulina_artisanal`, `gwp_spirulina_france`, `gwp_pond_biofuel`,
`gwp_pbr_biofuel`, `gwp_pbr_tubular_pilot`, `gwp_pbr_lightguided`,
`gwp_pbr_industrial`) carry a TODO to resolve the identifier. One of them,
`gwp_pbr_industrial`, sets the maximum of the published GWP spread and therefore
the headline ratio; verifying it against the source is a priority.

## 6. Missing assumptions

Never imputed. A field that the compiler did not extract is `null`, prints as
`unknown`, and blocks the record from any analysis that needs it:

* no `reported_price_year` → `not_normalizable`, excluded from the cost cohort
  (`phycocyanin`, `astaxanthin`, `padi2023_spirulina`);
* no `economic_endpoint_type` → excluded from the primary production-cost spread;
* `functional_unit` other than 1 kg dry biomass → excluded from the primary
  production-cost spread (the biorefinery cases).

Every exclusion and its reason appear in `results/economic_endpoint_audit.txt`.

### 6a. What the resulting cohort may be called

Screening on `economic_endpoint_type` and `functional_unit` makes the cohort
uniform in its **declared label**. It does not make the underlying numbers the
same quantity. Whether a source includes depreciation, whether it embeds a return
on capital, whether the cost is net of co-product credits, which allocation rule
produced it and where the system boundary sits are each large enough to move a
unit cost by more than the differences the spread is used to discuss — and for
most records they are unknown.

The cohort is therefore named once, in code
(`paper/endpoints.py:PRIMARY_COHORT_LABEL`), as

> studies nominally classified as biomass production-cost estimates

and never as a homogeneous production-cost cohort.
`paper/endpoints.py:definition_audit` reports, study by study and as counts, which
of the six endpoint-definition attributes are still unknown, and generates the
sentence the manuscript is allowed to use. It will only say "homogeneous in the
endpoint definition" when every member has every attribute recorded.

### 6b. Eligibility is enforced, not decorative

`eligibility_status: excluded` now removes a record from the primary cohort,
from Analysis A and B, and from the validation table. It was previously a comment
that no analysis read. The record it currently removes is `scp_protein`: an
open-literature single-cell-protein envelope with **no primary source**, which
had been a member of the matched reconstructable cohort and set that cohort's
minimum — so the headline divergence rested in part on an uncited number. The
scenario builder survives as the open-raceway *archetype*, which
`paper/archetypes.py` now declares as a library-default configuration rather than
a study reconstruction.

## 7. Tier definition (operational, machine-readable)

Implemented in `paper/schema.py:tier_rule`.

**Tier B** requires *all three*:
1. `published_inventory_available` — the source's foreground can be entered;
2. `published_capex_available` **or** `published_opex_available` — the cost
   structure can be rebuilt;
3. a scenario builder registered in `paper/reconstructions.py` — the repository
   can actually run it.

**Tier A** is everything else: a literature point that may enter descriptive range
statistics but not a mechanistic reconstruction.

`paper/schema.py:tier_disagreements` compares the declared tier against the rule
and the audit prints every disagreement. There are currently **none**: every
study declared Tier B has a registered, runnable builder (see §9).

## 8. Completeness score

`StudyRecord.completeness()` is the fraction of the 18 fields listed in
`COMPLETENESS_FIELDS` that are known. It is a declared rule over a declared field
list — two records with the same score are documented to the same degree. It says
nothing about the quality of the underlying science.

## 9. Where the scenario reconstructions came from

The module that held the study dataset and the scenario reconstructions
(`reference_studies.STUDIES`, referenced by `paper_handoff/DATASET.md`) is **not
on `main`**. It lives on the feature branch `m2-harmonization` (PR #1), which was
never merged, while its *outputs* were copied onto `main` as files.

Reconstructions therefore reach `main` by two routes, both recorded in
`paper/reconstructions.py:BUILDER_PROVENANCE`:

| route | studies |
|---|---|
| recovered from shipped templates and example scripts on `main` | `scp_protein`, `russo2022_aury`, `superpro_algaloil`, `superpro_omega3`, `phycocyanin`, `astaxanthin`, `frontiers2026_spirulina`, `padi2023_spirulina` |
| ported verbatim from `m2-harmonization:reference_studies.py` | `tredici2016`, `vazquez2022`, `iceland_spirulina`, `spiralg2019`, `mckuin_schizo` |
| built from a source's own published data in this revision | `vazquez2022b_nas`, `vazquez2022b_tiso_pht`, `vazquez2022b_nas_10ha` |

Each ported builder reproduces its published legacy value exactly (12.29, 104.26,
−0.56, 12.61, 2.39 respectively). That equality is how the port is verified: no
scenario was fitted to a known answer.

### 9a. Studies added to widen the matched cohort

The matched reconstructable cohort previously held four records: two external
primary studies, one study by the AlgaMetrix authors, and one benchmark with no
primary source. Three cases from **Vázquez-Romero et al. (2022), Sci. Total
Environ. 837:155742** were added because that paper is CC-BY and its
supplementary material publishes the *whole* cost model — Lang factors,
depreciation period, interest, property tax, insurance, maintenance and overhead
rates, and every input price — not only the answer.

Each is reconstructed **blind**: the engine receives the physical data and the
financial conventions and never the reported biomass cost. Transcription of the
capital chain is verified independently of the outcome, by reproducing the
paper's own published CAPEX per kg to within 0.5% for all three cases. The
resulting deviations on total cost are −7% to −14%, and the report states the
reason: consumables, wastewater treatment, cooling water, operating supplies and
contingencies are OPEX lines a mass balance cannot derive, and two of the three
cases buy a commercial nutrient solution whose consumption the paper does not
publish.

Independence is now counted rather than asserted. `author_overlap_with_algametrix`
is a schema field; `paper/harmonization.py:independence_audit` reports the number
of distinct publications behind a cohort, which members are the authors' own, and
which records share one publication — and therefore one facility, one cost model
and one author group — so cohort size is never mistaken for the amount of
independent evidence.

Porting them required two engine fields that also existed only on the branch —
`Scenario.other_opex_per_year` and its handling in `tea.py` — for the lump-sum
annual OPEX (consumables, thermal utilities, wastewater) that published TEAs
report but a per-kg balance cannot derive.

`verification.py` (mass-balance closure, product-mass and scale-invariance
invariants) was ported from the same branch and is now a stage of
`reproduce.py`, so `results/verification.txt` is regenerated rather than orphaned.
It runs over every executable reconstruction and the library-default archetype,
and the pipeline aborts if any conserved quantity fails to close.

### 9b. Two Intelligen studies admitted on 2026-08-12

Two further SuperPro Designer studies were identified on 2026-08-12. They were held out of the
dataset for as long as only their vendor summary page could be read: that page gives the
biostimulant case as 87,000 t/yr at a USD 1.2/kg selling price, from which a unit cost near
USD 0.92/kg follows by division — and a value the compiler divided out while the source's own
tables went unread is exactly the failure that withdrew two records on 2026-08-07 (§ *Excluded
records* in [VALIDATION.md](VALIDATION.md)). Both reports were then supplied in full, and both
print the endpoint directly, so both are now records:

| Record | Source | Endpoint, as printed |
|---|---|---|
| `superpro_dunaliella` | Misailidis N, Mustafa A, Da Gama Ferreira R, Petrides D (2022), [10.13140/RG.2.2.11426.71365](https://doi.org/10.13140/RG.2.2.11426.71365) | USD 358.57 per kg β-carotene, 2022 prices (Table 6, p. 21) |
| `superpro_biostimulant` | Gkousgkounis D, Parisis V, Misailidis N, Da Gama Ferreira R, Petrides D (2026), [10.13140/RG.2.2.11499.71202](https://doi.org/10.13140/RG.2.2.11499.71202) | USD 0.94 per kg biostimulant solution, 2026 prices (Table 13, p. 19) |

The published figures differ from the vendor page in both cases — USD 301 M rather than 289 M of
capital, USD 82.4 M rather than 79.9 M of operating cost, USD 0.94/kg rather than the 0.92 the
division gave. The gap is small and the direction is unimportant; what matters is that waiting
cost nothing and guessing would have entered three wrong numbers.

**Neither enters the primary cost cohort, and neither is screened out by hand.** The biostimulant
is priced per kilogram of a *solution* at 3.90% w/w peptides, and the Dunaliella case per kilogram
of β-carotene; `endpoints.classify` rejects both on functional unit, as it already does for the
algal-oil and omega-3 cases. What they widen is the range of processes the dataset can speak
about — from a pigment at USD 359/kg down to a waste-fed product at USD 0.94/kg — not the spread
of biomass production costs.

Both are Tier A: the engine cannot execute either today. The Dunaliella case splits one biomass
into five priced streams through a sequential solvent and ion-exchange train, and the engine
allocates across co-products without modelling the train that sets the yields. The biostimulant
case takes its nitrogen and phosphorus from municipal wastewater and sells no by-product but
discharges treated water, and the engine can neither price a nutrient that arrives as waste nor
credit a treatment service. Both limits are recorded as `todos` on the records themselves.

## 10. Quality control

* Controlled vocabularies are closed and validated at load time
  (`paper/schema.py`); a typo raises rather than silently creating a category.
* `tests/test_paper_evidence.py` asserts: unique ids, provenance on every record
  entering a main result, tier rule vs declared tier, endpoint homogeneity,
  cohort constancy, and an auditable transformation path for every normalized value.
* `python reproduce.py` regenerates every result file from the dataset, so a
  dataset edit that breaks an invariant fails loudly instead of shifting a number.
