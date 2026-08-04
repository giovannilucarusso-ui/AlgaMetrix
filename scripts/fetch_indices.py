#!/usr/bin/env python
"""Fetch the price indices and exchange rates used to normalize published costs.

    python scripts/fetch_indices.py            # print what would change
    python scripts/fetch_indices.py --write    # update data/studies/indices.yaml

Why this exists
---------------
The reviewer's objection to the previous method was that CEPCI - a plant and
equipment cost index - was applied to labour, energy and every other operating
expenditure. Fixing that needs one index per expenditure class, each with real
provenance. This script pulls them from public statistical APIs and writes them
into ``data/studies/indices.yaml`` together with the dataset identifier, the
filter used, the provider's own "last updated" timestamp and the retrieval date,
so no index value in this repository is hand-typed or unattributable.

Sources
-------
Eurostat dissemination API (no key required)
    ``lc_lci_r2_a``   labour cost index, EU27, NACE B-S, wages and salaries
    ``prc_hicp_aind`` HICP annual average index, EU27, all items
    ``nrg_pc_205``    electricity price for industrial consumers, EU27, band IC
European Central Bank Data Portal
    ``EXR/A.USD.EUR.SP00.A`` annual average euro reference exchange rate

CEPCI is **not** fetched: it is published by *Chemical Engineering* magazine
behind a paywall and has no open API. Its values remain flagged in the YAML as
back-calculated from the committed legacy output, with a TODO to confirm them
against the published issues.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDICES = ROOT / "data" / "studies" / "indices.yaml"

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
ECB = "https://data-api.ecb.europa.eu/service/data/"

#: Years the study dataset spans; nothing outside this is stored.
YEARS = range(2010, 2024)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.load(r)


def _eurostat(dataset: str, filters: dict) -> tuple[dict[str, float], str, str]:
    """Return ``({period: value}, provider_updated, url)`` for one Eurostat series."""
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    url = f"{EUROSTAT}{dataset}?format=JSON&lang=EN&{query}"
    d = _get_json(url)
    periods = {v: k for k, v in d["dimension"]["time"]["category"]["index"].items()}
    values = {periods[int(k)]: float(v) for k, v in d["value"].items()}
    return values, d.get("updated", "unknown"), url


def fetch_labour() -> dict:
    filters = {"geo": "EU27_2020", "nace_r2": "B-S", "lcstruct": "D11", "unit": "I20"}
    values, updated, url = _eurostat("lc_lci_r2_a", filters)
    return {
        "index_name": "labour_cost_index",
        "normalization_class": "labour",
        "description": "Eurostat labour cost index, wages and salaries, EU27, "
                       "NACE Rev. 2 B-S (industry and services), index 2020 = 100.",
        "source": f"Eurostat dataset lc_lci_r2_a ({url})",
        "provider_last_updated": updated,
        "values_by_year": {int(y): v for y, v in sorted(values.items()) if int(y) in YEARS},
    }


def fetch_general_opex() -> dict:
    filters = {"geo": "EU27_2020", "coicop": "CP00", "unit": "INX_A_AVG"}
    values, updated, url = _eurostat("prc_hicp_aind", filters)
    return {
        "index_name": "general_opex_index",
        "normalization_class": "general_opex",
        "description": "Eurostat HICP, all items, EU27, annual average index 2015 = 100. "
                       "Used for non-energy, non-labour operating expenditure.",
        "source": f"Eurostat dataset prc_hicp_aind ({url})",
        "provider_last_updated": updated,
        "values_by_year": {int(y): v for y, v in sorted(values.items()) if int(y) in YEARS},
    }


def fetch_energy() -> dict:
    """Industrial electricity price, band IC, excluding taxes and levies.

    Bi-annual, so the two semesters are averaged into an annual figure. Band IC
    (500-1999 MWh/yr) is the consumption band a plant of the size modelled here
    falls into; the band is recorded in the description because the choice
    materially changes the level.
    """
    filters = {"geo": "EU27_2020", "currency": "EUR", "siec": "E7000",
               "nrg_cons": "MWH500-1999", "tax": "X_TAX", "unit": "KWH"}
    values, updated, url = _eurostat("nrg_pc_205", filters)
    annual: dict[int, list[float]] = collections.defaultdict(list)
    for period, v in values.items():
        annual[int(period[:4])].append(v)
    return {
        "index_name": "energy_price_series",
        "normalization_class": "energy",
        "description": "Eurostat electricity price for industrial consumers, EU27, "
                       "band IC (500-1 999 MWh/yr), excluding taxes and levies, EUR/kWh. "
                       "Bi-annual observations averaged to an annual figure.",
        "source": f"Eurostat dataset nrg_pc_205 ({url})",
        "provider_last_updated": updated,
        "values_by_year": {y: round(sum(v) / len(v), 5)
                           for y, v in sorted(annual.items()) if y in YEARS},
    }


def fetch_fx() -> dict:
    """Annual average euro reference rate, USD per EUR, inverted to USD -> EUR."""
    url = f"{ECB}EXR/A.USD.EUR.SP00.A?format=csvdata"
    req = urllib.request.Request(url, headers={"Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
    rates = {}
    for row in rows:
        year = row.get("TIME_PERIOD")
        if year and int(year) in YEARS:
            rates[int(year)] = round(1.0 / float(row["OBS_VALUE"]), 5)
    return {
        "from_currency": "USD",
        "to_currency": "EUR",
        "year_specific": True,
        "rates_by_year": rates,
        "source": f"European Central Bank, annual average euro reference exchange rate ({url})",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="write the fetched values into data/studies/indices.yaml")
    args = ap.parse_args()

    today = date.today().isoformat()
    fetched = {
        "retrieval_date": today,
        "indices": [fetch_labour(), fetch_general_opex(), fetch_energy()],
        "currency": fetch_fx(),
    }

    for idx in fetched["indices"]:
        years = sorted(idx["values_by_year"])
        print(f"{idx['index_name']:22s} {idx['normalization_class']:14s} "
              f"{len(years)} years {years[0]}-{years[-1]}  "
              f"provider updated {idx['provider_last_updated']}")
    fx = fetched["currency"]
    print(f"{'USD->EUR':22s} {'currency':14s} {len(fx['rates_by_year'])} years, year-specific")

    out = ROOT / "data" / "studies" / "indices_fetched.json"
    if args.write:
        out.write_text(json.dumps(fetched, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {out.relative_to(ROOT)}")
        print(f"Now merge it into {INDICES.relative_to(ROOT)} "
              "(the YAML is the source of truth and carries the notes and TODOs).")
    else:
        print("\ndry run; pass --write to store the fetched values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
