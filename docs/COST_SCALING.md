# Capital and labour cost against plant size

Up to 1.5 every equipment cost was proportional to capacity. Cultivation
equipment cost `capex_per_unit` per m² or m³, and harvesting, drying and
extraction equipment cost a fixed amount per kg/yr of dry biomass. Labour was a
fixed annual figure. Since 1.6 each of these can follow a power law instead. The
defaults keep the old model, so a scenario that declares nothing gets the same
numbers as before, to the last digit.

## The law

For each equipment group *k* (cultivation, harvesting, drying, extraction):

    C_k = N_k · c_k · S_ref,k · (S_k / (N_k · S_ref,k))^n_k
    N_k = max(1, ceil(S_k / S_max,k))

| Symbol | Meaning | Field |
|---|---|---|
| c_k | cost per unit of capacity, valid at S_ref,k | `capex_per_unit`, `harvest_capex_per_kgyr`, `drying_capex_per_kgyr`, `capex_per_kgyr` |
| S_k | capacity: m² or m³ for cultivation, kg/yr of dry biomass for the rest | `scenario.scale`, annual production |
| S_ref,k | capacity the coefficient was derived at | `reference_capacity` |
| n_k | exponent; 1 is proportional, the default | `exponent` |
| S_max,k | largest single unit | `max_capacity` |
| N_k | identical units in parallel | derived |

With n = 1 the expression reduces to c_k · S_k, whatever S_ref and N are. Any
other exponent needs the reference capacity, and the input check refuses the
scenario without it.

Labour follows the same form without units in parallel:

    L = L_ref · (S / S_ref,L)^n_L

where L_ref is `labor_cost_per_year`, S is the annual production in kg/yr and
the default n_L = 0 gives a fixed annual cost.

## Units in parallel

Above `max_capacity` the group is built as N identical units of S/N each, each
costed with the same law. Past that size, cost grows with the number of units
instead of following the curve. At the step from N to N + 1 units, cost rises
by a factor of ((N + 1)/N)^(1 − n), because the same capacity is now split
into more, smaller units. The TEA result lists the units of every group
in `tea.cost_scaling`.

## What the input check says

Errors (the scenario is not run):

- an exponent other than the default without a reference capacity;
- an equipment exponent of zero or below, or a negative labour exponent;
- a capacity of zero or below, or a range whose minimum exceeds its maximum.

Warnings (the result stands):

- a unit smaller than `min_capacity`, so the cost is extrapolated;
- labour above its `max_capacity`;
- no declared range, with the plant more than a factor of ten away from S_ref;
- an exponent above 1.

## Declaring it

In the YAML library, as a block next to the coefficient:

```yaml
- name: My fermenter
  capex_per_unit: 2500.0
  capex_scaling: {exponent: 0.6, reference_capacity: 100.0, min_capacity: 10.0,
                  max_capacity: 200.0, source: "vendor quote, 2025, 100 m3"}
```

`harvest_capex_scaling`, `drying_capex_scaling` and `labor_scaling` go in the
`economics:` block of `parameters.yaml`. Unknown keys are refused, so a typo
cannot silently drop a declaration. In Python:

```python
from dataclasses import replace
from algametrix.models import CostScaling, LabourScaling

scn.system = replace(scn.system,
                     capex_scaling=CostScaling(exponent=0.6, reference_capacity=100.0,
                                               max_capacity=200.0))
scn.economics = replace(scn.economics,
                        labor_scaling=LabourScaling(exponent=0.25,
                                                    reference_capacity=300_000.0))
```

The scaling objects are immutable, so a scenario cannot change a library preset
by mistake. They are saved with the scenario file.

## What the shipped data declares

Nothing. The costs in `data/systems.yaml` and `data/parameters.yaml` are
illustrative and were not taken from a costed plant of known size, so they have
no reference capacity to declare and stay proportional. A study reconstruction
or a template that takes its costs from a source at the source's capacity can
declare that capacity. Every published result of the paper uses the defaults.
