# -*- coding: utf-8 -*-
"""
App_readonly.py — Tableau de Bord Streamlit (Lecture seule)
Suivi Fabrication Structure Métallique — KPI & Graphiques uniquement

- Onglets visibles : KPI, Graphiques
- Édition et Export supprimés
- Chargement Excel : upload ou fichier par défaut (env DEFAULT_XLSX ou Structural_data.xlsx)
- Calculs : RowProgress% pondéré par étape (PROGRESS_MAP), TOR cumulatif par étape

Exécuter :
    streamlit run App_readonly.py
"""

import os
from io import BytesIO
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ------------------------------
# 0) Configuration & thème
# ------------------------------
st.set_page_config(page_title="Suivi Fabrication (Lecture seule)", layout="wide")
st.title("📊 Tableau de Bord — Suivi Fabrication (Lecture seule)")

# Couleurs par Étape (cohérence visuelle)
STEP_COLORS = {
    "Préparation": "#1f77b4",      # bleu
    "Assemblage": "#ff7f0e",       # orange
    "Traitement de surface": "#2ca02c",  # vert
    "Finalisation": "#d62728",     # rouge
    "None": "#7f7f7f"
}

# Étapes et pondérations (pour RowProgress% global)
STEPS_ORDER = ["Préparation", "Assemblage", "Traitement de surface", "Finalisation"]
STEP_RANK = {s: i for i, s in enumerate(STEPS_ORDER)}  # ordre pour logique TOR
PROGRESS_MAP = {
    "Préparation": 0.25,
    "Assemblage": 0.60,
    "Traitement de surface": 0.85,
    "Finalisation": 1.00,
    "None": 0.00,
}

# ------------------------------
# 1) Chargement des données
# ------------------------------
DEFAULT_XLSX = os.getenv("DEFAULT_XLSX", "Structural_data.xlsx")  # même dossier que l'application par défaut

@st.cache_data(show_spinner=False)
def load_excel(path_or_buffer):
    """Lit la première feuille automatiquement (évite les erreurs de nom)."""
    return pd.read_excel(path_or_buffer, engine="openpyxl")


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Vérifie les colonnes attendues & initialise les colonnes app si absentes."""
    required = ["PHASE", "ASSEMBLY NO.", "PART NO.", "TOT MASS (Kg)"]
    for c in required:
        if c not in df.columns:
            st.error(f"⚠️ Colonne manquante dans Excel : '{c}'")
            st.stop()
    # Harmonisation
    df["PHASE"] = df["PHASE"].astype(str)
    df["TOT MASS (Kg)"] = pd.to_numeric(df["TOT MASS (Kg)"], errors="coerce").fillna(0.0)
    # Colonnes d'application (si absentes)
    if "Etape" not in df.columns:
        df["Etape"] = "None"
    if "RowProgress%" not in df.columns:
        df["RowProgress%"] = 0.0
    if "CompletedMass_Row" not in df.columns:
        df["CompletedMass_Row"] = 0.0
    return df

st.sidebar.header("🛠️ Données (Lecture seule)")
st.sidebar.caption("Chargez un Excel pour alimenter le tableau; sinon le fichier local par défaut sera utilisé.")
uploaded = st.sidebar.file_uploader(
    "Importer un Excel (.xlsx)", type=["xlsx"],
    help="Optionnel : sinon le fichier par défaut sera utilisé."
)

try:
    if uploaded is not None:
        df_loaded = load_excel(uploaded)
        source_label = f"Fichier importé : {uploaded.name}"
        current_source_key = f"upload::{uploaded.name}"
    else:
        df_loaded = load_excel(DEFAULT_XLSX)
        source_label = f"Fichier local : {DEFAULT_XLSX}"
        current_source_key = f"local::{DEFAULT_XLSX}"
except Exception as e:
    st.error(f"❌ Échec de chargement : {e}")
    st.stop()

df_loaded = ensure_columns(df_loaded)
st.caption(f"✅ {source_label}")

# ------------------------------
# 1.b) Initialisation état partagé (SESSION)
# ------------------------------
if "df" not in st.session_state:
    st.session_state["df"] = df_loaded.copy()
    st.session_state["source_key"] = current_source_key
elif st.session_state.get("source_key") != current_source_key:
    st.session_state["df"] = df_loaded.copy()
    st.session_state["source_key"] = current_source_key

if "refresh_needed" not in st.session_state:
    st.session_state["refresh_needed"] = False

# ------------------------------
# 2) Fonctions utilitaires (TOR & calculs)
# ------------------------------

def recompute_progress(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcule RowProgress% (pondéré par Étape) et CompletedMass_Row (masse × RowProgress%)."""
    out = df.copy()
    out["RowProgress%"] = out["Etape"].map(PROGRESS_MAP).fillna(0.0)
    out["CompletedMass_Row"] = out["TOT MASS (Kg)"] * out["RowProgress%"]
    return out


@st.cache_data(show_spinner=False)
def step_advancement(df: pd.DataFrame) -> pd.DataFrame:
    """Avancement par étape TOR (cumulatif par rang)."""
    total_mass = df["TOT MASS (Kg)"].sum()
    rows = []
    for step in STEPS_ORDER:
        treated_mass = df.loc[
            df["Etape"].map(lambda s: STEP_RANK.get(s, -1)) >= STEP_RANK[step],
            "TOT MASS (Kg)"
        ].sum()
        pct = (treated_mass / total_mass) * 100 if total_mass > 0 else 0.0
        rows.append({"Etape": step, "CompletedMass": treated_mass, "Avancement%": pct})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def phase_advancement(df: pd.DataFrame) -> pd.DataFrame:
    """Avancement par PHASE (pondéré via CompletedMass_Row)."""
    rows = []
    for phase in sorted(df["PHASE"].unique()):
        phase_total_mass = df.loc[df["PHASE"] == phase, "TOT MASS (Kg)"].sum()
        treated_mass = df.loc[df["PHASE"] == phase, "CompletedMass_Row"].sum()
        pct = (treated_mass / phase_total_mass) * 100 if phase_total_mass > 0 else 0.0
        rows.append({"PHASE": phase, "CompletedMass": treated_mass, "Avancement%": pct})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def assembly_table(df: pd.DataFrame) -> pd.DataFrame:
    """Vue par assemblage (utilisée au besoin, lecture seule ici)."""
    agg = df.groupby(["PHASE", "ASSEMBLY NO."]).agg(
        AssemblyMass=("TOT MASS (Kg)", "sum"),
        EtapeRank=("Etape", lambda s: min([STEP_RANK.get(x, -1) for x in s]) if len(s) else -1)
    ).reset_index()
    inv_rank = {v: k for k, v in STEP_RANK.items()}
    agg["EtapeAsm"] = agg["EtapeRank"].map(inv_rank).fillna("None")
    return agg[["PHASE", "ASSEMBLY NO.", "AssemblyMass", "EtapeAsm"]]

# Première recomputation
st.session_state["df"] = recompute_progress(st.session_state["df"])

# ------------------------------
# 3) Onglets principaux (Lecture seule)
# ------------------------------
tab_kpi, tab_graph = st.tabs(["📈 KPI", "📊 Graphiques"])

# ------------------------------
# 📈 3.2 KPI
# ------------------------------
with tab_kpi:
    st.subheader("Indicateurs Globaux")
    total_mass = float(st.session_state["df"]["TOT MASS (Kg)"].sum())
    completed_global_mass = float(st.session_state["df"]["CompletedMass_Row"].sum())
    progress_global = (completed_global_mass / total_mass) * 100 if total_mass > 0 else 0.0

    k1, k2, k3 = st.columns(3)
    k1.metric("Masse Totale (Kg)", f"{total_mass:,.2f}")
    k2.metric("Masse Terminée (Kg)", f"{completed_global_mass:,.2f}")
    k3.metric("Avancement Global", f"{progress_global:.2f}%")

    gauge_color = "green" if progress_global >= 80 else ("orange" if progress_global >= 50 else "red")
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=progress_global,
        title={'text': "Avancement Global (%)"},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': gauge_color},
            'steps': [
                {'range': [0, 50], 'color': '#ffd6d6'},
                {'range': [50, 80], 'color': '#ffe9b5'},
                {'range': [80, 100], 'color': '#d6f5d6'},
            ]
        }
    ))
    st.plotly_chart(fig_gauge, use_container_width=True)

    st.divider()
    st.subheader("Avancement par Étape (TOR)")
    df_steps = step_advancement(st.session_state["df"])  # cumulatif par rang
    st.dataframe(
        df_steps.rename(columns={
            "Etape": "Étape",
            "CompletedMass": "Masse traitée (Kg)",
            "Avancement%": "Avancement (%)"
        }),
        use_container_width=True
    )
    fig_bar_steps = px.bar(
        df_steps,
        x="Etape",
        y="Avancement%",
        color="Etape",
        color_discrete_map=STEP_COLORS,
        text="Avancement%",
        title="Avancement par Étape (%)"
    )
    fig_bar_steps.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
    fig_bar_steps.update_yaxes(title="%", range=[0, 100])
    st.plotly_chart(fig_bar_steps, use_container_width=True)

    st.divider()
    st.subheader("Avancement par PHASE (pondéré)")
    df_phase = phase_advancement(st.session_state["df"])  # pondéré par PROGRESS_MAP
    st.dataframe(
        df_phase.rename(columns={
            "PHASE": "Phase",
            "CompletedMass": "Masse traitée (Kg)",
            "Avancement%": "Avancement (%)"
        }),
        use_container_width=True
    )
    fig_bar_phase = px.bar(
        df_phase,
        x="PHASE",
        y="Avancement%",
        color="PHASE",
        text="Avancement%",
        title="Avancement par PHASE (%)"
    )
    fig_bar_phase.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
    fig_bar_phase.update_yaxes(title="%", range=[0, 100])
    st.plotly_chart(fig_bar_phase, use_container_width=True)

# ------------------------------
# 📊 3.3 Graphiques
# ------------------------------
with tab_graph:
    st.subheader("Diagramme S — Progression cumulée par Étape (TOR)")
    df_steps = step_advancement(st.session_state["df"]).copy()
    # CompletedMass est déjà cumulative par construction (rang >= step)
    df_steps["Cumul_Masse"] = df_steps["CompletedMass"]

    fig_s = go.Figure()
    fig_s.add_trace(go.Scatter(
        x=df_steps["Etape"], y=df_steps["Avancement%"],
        mode="lines+markers", name="Avancement cumulé (%)",
        line=dict(width=3, color="#1f77b4")
    ))
    fig_s.add_trace(go.Bar(
        x=df_steps["Etape"], y=df_steps["Cumul_Masse"],
        name="Masse cumulée (Kg)", marker_color="#9ecae1", opacity=0.6, yaxis="y2"
    ))
    fig_s.update_layout(
        title="Diagramme S — % cumulé & masse cumulée",
        yaxis=dict(title="% cumulé", range=[0, 100]),
        yaxis2=dict(title="Masse (Kg)", overlaying="y", side="right"),
        legend=dict(orientation="h")
    )
    st.plotly_chart(fig_s, use_container_width=True)
