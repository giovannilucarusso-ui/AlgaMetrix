# Currency and price year: what an AlgaMetrix number is denominated in

## The problem this document exists to remove

AlgaMetrix has no currency. `tea.py` does arithmetic on the numbers held in
`Economics`; the unit of its output is whatever unit those numbers were in. A
reconstruction fed a source's published **USD 2015** price set returns a
production cost in USD 2015.

The repository nevertheless called every monetary output EUR. The field is named
`production_cost_eur_per_kg`; the SuperPro reference files use column names such
as `total_capex_eur` while their own header line says *"Values in USD"*, and one
of them says *"Values in USD (~EUR for comparison)"*.

That labelling error produced two defects in published results:

1. **The validation table** divided an engine number by a source number in a
   different currency and printed the quotient as a percentage deviation, with a
   note underneath saying the currencies differed. A note does not make a
   quotient dimensionless. Affected rows: `russo2022_aury` (+5%),
   `superpro_algaloil` (+1%), `superpro_omega3` (+6%), and the `astaxanthin`
   range check — and the ratio axis of Figure 2.
2. **Analysis B of the harmonization** pooled engine outputs denominated in
   EUR 2016, EUR 2021, EUR 2022 and USD 2022 into a single max/min spread.

## The fix

`paper/basis.py` introduces `PriceBasis(currency, price_year, kind, provenance)`.
Every registered reconstruction declares the basis of the price set it is run
with, in `reconstructions.BUILDER_PRICE_BASIS`. Nothing is compared or pooled
until both sides are in one declared basis.

### Three kinds of price set

| kind | meaning |
|---|---|
| `source_price_set` | every price fed to the engine comes from the source study |
| `mixed_price_set` | the source's published prices are used; the rest are shipped library defaults, which are in the library's own currency and year |
| `library_default_price_set` | the scenario runs entirely on `data/parameters.yaml`, whatever currency the source is in |

`LIBRARY_PRICE_BASIS` is declared as **EUR 2022, declared not sourced**: the
shipped price set is not tied to a dated price table (0.15 EUR/kWh sits between
the Eurostat EU27 industrial band-IC price for 2021 and 2022), and 2022 is chosen
because it is the year the harmonization normalises to. Every result depending on
it says so.

### Transformations

`paper/indices.py:transfer()` moves an amount between two bases. The currency
step is taken **at the price year the money is denominated in**, then the result
is escalated inside the target currency — doing it the other way round applies an
exchange rate to money of a year it never existed in. Escalation is per-class
(plant-cost index for capital, labour cost index for labour, industrial
electricity price for energy, HICP for the rest), weighted as in `normalize()`.

A transformation that cannot be defended is refused rather than approximated:

* unknown currency on either side → blocked;
* different currencies with an unknown denomination year → blocked, because no
  year-specific rate can be chosen and a flat rate folds a currency movement into
  what is reported as a deviation;
* different price years with either year unknown → blocked.

Matching currencies with an unknown year are *not* blocked — the comparison is
already dimensionless — but are flagged `currency_aligned_year_unknown` so nobody
mistakes them for aligned.

Exchange rates are the ECB annual average euro reference rate, per year, from
`data/studies/indices.yaml`. A pair declared in one direction is usable in both:
the reverse is the reciprocal of the same published rate.

## Mixed price sets are bracketed, not assumed away

Several reconstructions take some prices from the source and leave the rest at
the library defaults. Their output is not cleanly in one currency.
`reconstructions.build_in_basis()` re-runs such a scenario with the library
defaults expressed in the declared currency, and the deviation is reported as the
**interval the two readings span** instead of a point that quietly assumes the
mixing is negligible.

The intervals turn out to be narrow, which is the useful result: the deviations
were numerically right and only the label was wrong.

| study | engine basis | deviation |
|---|---|---|
| `tredici2016` | EUR 2016, source price set | −1% (no conversion needed) |
| `vazquez2022` | EUR 2021, source price set | −4% (no conversion needed) |
| `russo2022_aury` | USD 2022, mixed | +5% to +6% |
| `superpro_algaloil` | USD 2015, mixed | −2% to +1% |
| `superpro_omega3` | USD 2021, mixed | −2% to +6% |

`astaxanthin` is now reported as **not comparable**: the engine runs on the
library price set (EUR) and the source envelope is in USD with no recorded price
year, so no year-specific rate can be chosen. It carries no percentage and no
verdict until the source's price year is extracted.

## What this changed in the results

* `results/validation.txt` states the basis of both sides of every comparison and
  the transformation between them, and summarises how many comparisons needed no
  conversion, how many needed one, and how many are bracketed.
* Figure 2's ratio axis is labelled "both in the source's own currency and price
  year", mixed price sets are drawn as intervals, and rows that cannot be brought
  to one basis are counted in the caption rather than plotted.
* Analysis B converts each engine output into EUR at the common price year before
  pooling. Stage labels carry the basis. The conversion is not cosmetic: the
  factors range from ×0.95 (USD 2022 → EUR 2022) to ×1.49 (EUR 2016 → EUR 2022).

## What is still open

* The library price year is **declared, not sourced**. Pinning each shipped price
  in `data/parameters.yaml` to a dated published source would remove the
  assumption that `scp_protein`, `phycocyanin` and `astaxanthin` inherit.
* `phycocyanin` and `padi2023_spirulina` compare EUR against EUR of an unrecorded
  year. They are dimensionless but not aligned to a common price level.
* The field name `production_cost_eur_per_kg` is still wrong for a scenario run
  on a non-euro price set. It is left alone because renaming it touches the
  desktop application and the export formats; the basis layer makes the unit
  explicit wherever the number is used in the paper.
