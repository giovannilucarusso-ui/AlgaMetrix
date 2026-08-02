"""Interactive web UI for AlgaMetrix.

Run from the repository root::

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Make `src/` importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from algametrix.library import load_library
from algametrix.models import Basis, Scenario
from algametrix.scenario import run_scenario

st.set_page_config(page_title="AlgaMetrix", page_icon="🌱", layout="wide")


@st.cache_data
def get_library():
    return load_library()


lib = get_library()


# --------------------------------------------------------------------------- #
# Sidebar: build the scenario from editable defaults
# --------------------------------------------------------------------------- #
st.sidebar.title("🌱 AlgaMetrix")
st.sidebar.caption("Techno-economic & life-cycle analysis of microalgae / protist biomass")

# --- Organism --------------------------------------------------------------
st.sidebar.header("Organism")
org_name = st.sidebar.selectbox("Strain", list(lib.organisms), index=0)
org = lib.organisms[org_name]
with st.sidebar.expander("Edit composition"):
    org = replace(
        org,
        carbon=st.number_input("Carbon (fraction of DW)", 0.0, 1.0, org.carbon, 0.01),
        nitrogen=st.number_input("Nitrogen (fraction of DW)", 0.0, 0.3, org.nitrogen, 0.005),
        phosphorus=st.number_input("Phosphorus (fraction of DW)", 0.0, 0.1, org.phosphorus, 0.001, format="%.3f"),
    )
st.sidebar.caption(org.notes)

# --- Cultivation system ----------------------------------------------------
st.sidebar.header("Cultivation system")
sys_name = st.sidebar.selectbox("System", list(lib.systems), index=0)
system = lib.systems[sys_name]
with st.sidebar.expander("Edit cultivation"):
    system = replace(
        system,
        productivity=st.number_input(
            f"Productivity ({'g/m²/d' if system.basis == Basis.AREA else 'g/L/d'})",
            0.0, 200.0, system.productivity, 1.0,
        ),
        operating_days=st.number_input("Operating days per year", 1.0, 365.0, system.operating_days, 5.0),
        elec_kwh_per_kg=st.number_input("Cultivation electricity (kWh/kg)", 0.0, 50.0, system.elec_kwh_per_kg, 0.1),
        co2_utilization=st.slider("CO₂ utilization", 0.1, 1.0, float(system.co2_utilization) or 0.75),
        nutrient_uptake=st.slider("Nutrient uptake efficiency", 0.1, 1.0, system.nutrient_uptake),
        water_m3_per_kg=st.number_input("Water use (m³/kg)", 0.0, 5.0, system.water_m3_per_kg, 0.05),
        substrate_yield=st.number_input("Substrate yield (kg biomass/kg substrate)", 0.0, 1.0, system.substrate_yield, 0.05),
        capex_per_unit=st.number_input(
            f"Cultivation CAPEX (€/{'m²' if system.basis == Basis.AREA else 'm³'})",
            0.0, 5000.0, system.capex_per_unit, 5.0,
        ),
    )
st.sidebar.caption(system.notes)

unit = "m²" if system.basis == Basis.AREA else "m³"
default_scale = 100_000.0 if system.basis == Basis.AREA else 500.0
scale = st.sidebar.number_input(
    f"Plant scale ({unit})", min_value=1.0, value=default_scale, step=default_scale / 10
)

# --- Harvesting & drying ---------------------------------------------------
st.sidebar.header("Downstream")
harv_name = st.sidebar.selectbox("Harvesting", list(lib.harvesting), index=0)
harvesting = lib.harvesting[harv_name]
with st.sidebar.expander("Edit harvesting"):
    harvesting = replace(
        harvesting,
        recovery=st.slider("Biomass recovery", 0.1, 1.0, harvesting.recovery),
        elec_kwh_per_kg=st.number_input("Harvesting electricity (kWh/kg)", 0.0, 20.0, harvesting.elec_kwh_per_kg, 0.1),
        final_solids=st.slider("Concentrate solids fraction", 0.02, 0.5, harvesting.final_solids),
    )

dry_name = st.sidebar.selectbox("Drying", list(lib.drying), index=0)
drying = lib.drying[dry_name]
with st.sidebar.expander("Edit drying"):
    drying = replace(
        drying,
        enabled=st.checkbox("Drying enabled", drying.enabled),
        thermal_mj_per_kg_water=st.number_input("Drying heat (MJ/kg water)", 0.0, 6.0, drying.thermal_mj_per_kg_water, 0.1),
        final_solids=st.slider("Dried product solids", 0.5, 1.0, drying.final_solids),
    )

# --- Economics -------------------------------------------------------------
eco = lib.economics
with st.sidebar.expander("💶 Economic assumptions"):
    eco = replace(
        eco,
        electricity_price=st.number_input("Electricity price (€/kWh)", 0.0, 1.0, eco.electricity_price, 0.01),
        nitrogen_price=st.number_input("Nitrogen price (€/kg N)", 0.0, 10.0, eco.nitrogen_price, 0.1),
        co2_price=st.number_input("CO₂ price (€/kg)", -0.2, 1.0, eco.co2_price, 0.01),
        substrate_price=st.number_input("Substrate price (€/kg)", 0.0, 3.0, eco.substrate_price, 0.05),
        labor_cost_per_year=st.number_input("Labour (€/yr)", 0.0, 5_000_000.0, eco.labor_cost_per_year, 10_000.0),
        discount_rate=st.slider("Discount rate", 0.0, 0.25, eco.discount_rate),
        plant_lifetime=st.number_input("Plant lifetime (yr)", 1.0, 40.0, eco.plant_lifetime, 1.0),
    )

# --- LCIA ------------------------------------------------------------------
lcia = lib.lcia
with st.sidebar.expander("🌍 LCA factors"):
    lcia = replace(
        lcia,
        elec_gwp=st.number_input("Grid electricity GWP (kg CO₂-eq/kWh)", 0.0, 1.5, lcia.elec_gwp, 0.01),
        nitrogen_gwp=st.number_input("N fertilizer GWP (kg CO₂-eq/kg N)", 0.0, 20.0, lcia.nitrogen_gwp, 0.5),
        count_biogenic_uptake=st.checkbox("Credit biogenic CO₂ uptake at gate", lcia.count_biogenic_uptake),
    )

scenario = Scenario(
    organism=org, system=system, harvesting=harvesting, drying=drying,
    economics=eco, lcia=lcia, scale=scale,
)
results = run_scenario(scenario)
inv, tea, lca = results.inventory, results.tea, results.lca


# --------------------------------------------------------------------------- #
# Main panel
# --------------------------------------------------------------------------- #
st.title("Techno-economic & Life-cycle results")
st.caption(
    f"**{org.name}** · {system.name} · {scale:,.0f} {unit} · "
    f"functional unit: **1 kg dry biomass**"
)
st.info(
    "Default values are literature-typical placeholders to make the tool run. "
    "Replace them with your own data before drawing conclusions.",
    icon="⚠️",
)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Production cost", f"€ {tea.production_cost_eur_per_kg:,.2f}", help="per kg dry biomass")
k2.metric("GWP", f"{lca.gwp_kg_co2eq_per_kg:,.2f}", help="kg CO₂-eq per kg biomass")
k3.metric("Energy demand", f"{lca.ced_mj_per_kg:,.1f}", help="MJ per kg biomass (CED)")
k4.metric("Water use", f"{lca.water_m3_per_kg:,.2f}", help="m³ per kg biomass")
k5.metric("Annual output", f"{inv.annual_biomass_kg/1000:,.0f} t/yr")

tab_tea, tab_lca, tab_inv = st.tabs(["💶 Techno-economic", "🌍 Life-cycle", "📦 Inventory"])

with tab_tea:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Annual cost breakdown")
        opex_df = (
            pd.DataFrame(tea.opex_breakdown.items(), columns=["Item", "€/yr"])
            .sort_values("€/yr", ascending=True)
        )
        fig = px.bar(opex_df, x="€/yr", y="Item", orientation="h")
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.subheader("CAPEX breakdown")
        capex_df = pd.DataFrame(tea.capex_breakdown.items(), columns=["Item", "€"])
        fig = px.pie(capex_df, names="Item", values="€", hole=0.4)
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    m1, m2 = st.columns(2)
    m1.metric("Total CAPEX", f"€ {tea.total_capex/1e6:,.2f} M")
    m2.metric("Annual OPEX", f"€ {tea.annual_opex/1e6:,.2f} M/yr")

with tab_lca:
    st.subheader("GWP contribution analysis (kg CO₂-eq / kg biomass)")
    gwp_df = pd.DataFrame(lca.gwp_breakdown.items(), columns=["Contributor", "kg CO₂-eq"])
    colors = ["#2E7D32" if v < 0 else "#C62828" for v in gwp_df["kg CO₂-eq"]]
    fig = go.Figure(go.Bar(x=gwp_df["kg CO₂-eq"], y=gwp_df["Contributor"], orientation="h", marker_color=colors))
    fig.add_vline(x=lca.gwp_kg_co2eq_per_kg, line_dash="dash", annotation_text="net")
    fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Net GWP", f"{lca.gwp_kg_co2eq_per_kg:,.2f} kg CO₂-eq")
    c2.metric("Cumulative energy demand", f"{lca.ced_mj_per_kg:,.1f} MJ")
    c3.metric("Land use", f"{lca.land_m2a_per_kg:,.2f} m²·a")

with tab_inv:
    st.subheader("Process inventory (per kg dry biomass)")
    inv_rows = [
        ("Electricity", inv.elec_kwh_per_kg, "kWh"),
        ("Heat (drying)", inv.heat_mj_per_kg, "MJ"),
        ("CO₂ supplied", inv.co2_supply_per_kg, "kg"),
        ("CO₂ fixed (biogenic)", inv.co2_fixed_per_kg, "kg"),
        ("Nitrogen", inv.nitrogen_per_kg, "kg"),
        ("Phosphorus", inv.phosphorus_per_kg, "kg"),
        ("Water", inv.water_m3_per_kg, "m³"),
        ("Substrate", inv.substrate_per_kg, "kg"),
        ("Land occupation", inv.land_m2a_per_kg, "m²·a"),
    ]
    inv_df = pd.DataFrame(inv_rows, columns=["Flow", "Value", "Unit"])
    st.dataframe(inv_df, use_container_width=True, hide_index=True)

    st.subheader("Electricity by stage (kWh/kg)")
    elec_df = pd.DataFrame(inv.elec_breakdown.items(), columns=["Stage", "kWh/kg"])
    st.plotly_chart(px.bar(elec_df, x="Stage", y="kWh/kg"), use_container_width=True)

# --- Download --------------------------------------------------------------
export = {
    "scenario": {
        "organism": org.name, "system": system.name, "scale": scale, "unit": unit,
        "harvesting": harvesting.name, "drying": drying.name if drying.enabled else "none",
    },
    "annual_biomass_t": inv.annual_biomass_kg / 1000,
    "tea": {
        "production_cost_eur_per_kg": tea.production_cost_eur_per_kg,
        "total_capex_eur": tea.total_capex,
        "annual_opex_eur": tea.annual_opex,
        "opex_breakdown_eur": tea.opex_breakdown,
        "capex_breakdown_eur": tea.capex_breakdown,
    },
    "lca_per_kg": {
        "gwp_kg_co2eq": lca.gwp_kg_co2eq_per_kg,
        "ced_mj": lca.ced_mj_per_kg,
        "water_m3": lca.water_m3_per_kg,
        "land_m2a": lca.land_m2a_per_kg,
        "gwp_breakdown": lca.gwp_breakdown,
    },
}
st.download_button(
    "⬇️ Download results (JSON)",
    data=json.dumps(export, indent=2),
    file_name="algae_tea_lca_results.json",
    mime="application/json",
)
