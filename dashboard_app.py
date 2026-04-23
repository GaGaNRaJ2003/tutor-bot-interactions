from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from analyze_pilot_studies import analyze_pilot, build_global_user_lookup, load_json


ROOT = Path(__file__).resolve().parent
# On a deployed server, set TUTOR_BOT_DATA_ROOT to the folder that contains store_Pilot_v* directories.
_DEFAULT_DATA_ROOT = os.environ.get("TUTOR_BOT_DATA_ROOT", str(ROOT))


st.set_page_config(
    page_title="Tutor Bot Pilot Monitor",
    page_icon="TB",
    layout="wide",
    initial_sidebar_state="expanded",
)


THEME = {
    "paper": "#f7f3ea",
    "ink": "#1f2a2e",
    "muted": "#63706d",
    "line": "#ded6c8",
    "blue": "#245c73",
    "ochre": "#c48a2c",
    "green": "#4f7f52",
    "red": "#b55345",
    "cream": "#fffaf0",
}


st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,750&family=Source+Serif+4:wght@400;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Source Serif 4', Georgia, serif;
        color: {THEME["ink"]};
    }}

    .stApp {{
        background:
            radial-gradient(circle at top left, rgba(196, 138, 44, 0.18), transparent 32rem),
            linear-gradient(135deg, {THEME["paper"]} 0%, #efe6d3 100%);
    }}

    h1, h2, h3 {{
        font-family: 'Fraunces', Georgia, serif;
        letter-spacing: -0.02em;
    }}

    .hero {{
        padding: 1.25rem 1.5rem;
        border: 1px solid {THEME["line"]};
        border-radius: 24px;
        background:
            linear-gradient(135deg, rgba(255,250,240,0.92), rgba(255,250,240,0.64)),
            repeating-linear-gradient(45deg, rgba(36,92,115,0.05), rgba(36,92,115,0.05) 8px, transparent 8px, transparent 16px);
        box-shadow: 0 14px 36px rgba(61, 51, 36, 0.12);
        margin-bottom: 1rem;
    }}

    .hero-eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: {THEME["blue"]};
        font-weight: 700;
        font-size: 0.78rem;
    }}

    .hero-title {{
        font-family: 'Fraunces', Georgia, serif;
        font-size: 2.4rem;
        line-height: 1.02;
        margin-top: 0.15rem;
    }}

    .hero-copy {{
        color: {THEME["muted"]};
        max-width: 62rem;
        font-size: 1.04rem;
    }}

    div[data-testid="stMetric"] {{
        background: rgba(255,250,240,0.78);
        border: 1px solid {THEME["line"]};
        border-radius: 18px;
        padding: 1rem;
        box-shadow: 0 10px 24px rgba(61, 51, 36, 0.08);
    }}

    section[data-testid="stSidebar"] {{
        background: #e9dfcb;
        border-right: 1px solid {THEME["line"]};
    }}

    .section-note {{
        color: {THEME["muted"]};
        margin-top: -0.4rem;
        margin-bottom: 1rem;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def discover_pilot_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("store_Pilot_v"))


def _safe_unzip(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in archive.infolist():
        out = (dest / member.filename).resolve()
        if not (str(out) == str(dest) or str(out).startswith(str(dest) + os.sep)):
            raise ValueError("Invalid path in zip archive (possible zip slip).")
        if member.is_dir() or str(member.filename).rstrip().endswith("/"):
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, out.open("wb") as t:
                shutil.copyfileobj(src, t)


def _find_pilot_data_parent(extracted: Path) -> Path:
    """Return the directory that *directly* contains store_Pilot_v* folders (what discover_pilot_dirs expects)."""
    stores = [
        p
        for p in extracted.rglob("store_Pilot_v*")
        if p.is_dir() and p.name.startswith("store_Pilot_v")
    ]
    if not stores:
        raise FileNotFoundError("No store_Pilot_v* folder found. Zip the parent folder of your exports, or the exports themselves.")
    parents = {s.parent for s in stores}
    if len(parents) != 1:
        raise ValueError(
            "All store_Pilot_v* folders must sit under a single parent directory. "
            "Re-zip so one folder contains store_Pilot_v0, store_Pilot_v1, etc."
        )
    return parents.pop()


def extract_pilot_zip_to_temp(zip_bytes: bytes) -> tuple[Path, Path]:
    """Return (pilot_data_root, temp_base_to_delete) where all files live under temp_base_to_delete."""
    base = Path(tempfile.mkdtemp(prefix="pilot_stores_"))
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            _safe_unzip(zf, base)
        root = _find_pilot_data_parent(base)
        if not discover_pilot_dirs(root):
            raise FileNotFoundError("Expected store_Pilot_v* folders with JSON exports were not found at the top level of the unzipped tree.")
    except (zipfile.BadZipFile, OSError, FileNotFoundError, ValueError) as e:
        shutil.rmtree(base, ignore_errors=True)
        raise e
    return root, base


def dataset_signature(root: Path) -> str:
    parts: list[str] = []
    for pilot_dir in discover_pilot_dirs(root):
        for path in sorted(pilot_dir.rglob("*.json")):
            stat = path.stat()
            parts.append(f"{path.relative_to(root)}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


def count_completed_improvement_jobs(pilot_dir: Path) -> tuple[int, dict[str, int]]:
    path = pilot_dir / "improvement_jobs.json"
    if not path.exists():
        return 0, {}

    jobs = load_json(path)
    per_user: dict[str, int] = {}
    total = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if job.get("status") != "done" or not job.get("result_prompt_version_id"):
            continue
        user_id = job.get("user_id")
        if not isinstance(user_id, str):
            continue
        total += 1
        per_user[user_id] = per_user.get(user_id, 0) + 1
    return total, per_user


@st.cache_data(ttl=10, show_spinner=False)
def load_dashboard_data(root_text: str, signature: str) -> dict[str, Any]:
    root = Path(root_text)
    pilot_dirs = discover_pilot_dirs(root)
    global_user_lookup = build_global_user_lookup(pilot_dirs)

    summary_rows: list[dict[str, Any]] = []
    user_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []

    for pilot_dir in pilot_dirs:
        analysis = analyze_pilot(pilot_dir, global_user_lookup)
        summary = dict(analysis["interaction_summary"])
        persisted_summary = dict(analysis["summary"])
        generated_jobs, generated_jobs_by_user = count_completed_improvement_jobs(pilot_dir)

        summary["persisted_new_prompt_versions"] = summary["interaction_new_prompt_versions"]
        summary["generated_prompt_versions_from_jobs"] = generated_jobs
        summary["prompt_version_gap"] = generated_jobs - summary["interaction_new_prompt_versions"]
        summary_rows.append(summary)

        for row in analysis["interaction_users"]:
            enriched = dict(row)
            enriched["generated_prompt_versions_from_jobs"] = generated_jobs_by_user.get(row["user_id"], 0)
            enriched["prompt_version_gap"] = (
                enriched["generated_prompt_versions_from_jobs"] - enriched["new_prompt_versions"]
            )
            user_rows.append(enriched)

        quality_rows.append(
            {
                "pilot": pilot_dir.name,
                "non_registered_interaction_ids": summary["interaction_user_ids_not_registered_in_pilot"],
                "orphaned_message_users": json.dumps(persisted_summary["orphaned_message_users"], indent=2),
                "orphaned_session_users": json.dumps(persisted_summary["orphaned_session_users"], indent=2),
                "orphaned_prompt_users": json.dumps(persisted_summary["orphaned_prompt_users"], indent=2),
                "prompt_version_gap": summary["prompt_version_gap"],
            }
        )

    return {
        "summary": summary_rows,
        "users": user_rows,
        "quality": quality_rows,
        "loaded_pilots": [path.name for path in pilot_dirs],
    }


def make_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    clean = df.copy()
    for column in columns:
        if column in clean:
            clean[column] = pd.to_numeric(clean[column], errors="coerce").fillna(0)
    return clean


def apply_interaction_summary_csv(root: Path, df: pd.DataFrame) -> pd.DataFrame:
    """Align chart/metric values with the batch export and Excel Summary sheet.

    ``analyze_pilot_studies.py`` writes ``pilot_interaction_user_summary.csv`` with the
    same figures that go into ``pilot_interaction_view_workbook.xlsx``. If that CSV
    is present, we prefer its columns for the interaction summary so the app matches
    the workbook even if live DataFrame types or cached runs were wrong.
    """
    path = root / "pilot_interaction_user_summary.csv"
    if df.empty or not path.is_file():
        return df
    try:
        exported = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return df
    if "pilot" not in exported.columns:
        return df
    exported = exported.drop_duplicates(subset=["pilot"], keep="last")
    map_idx = exported.set_index("pilot", verify_integrity=True)
    out = df.copy()
    merge_cols = [
        "registered_users",
        "interaction_user_ids_total",
        "interaction_user_ids_registered_in_pilot",
        "interaction_user_ids_not_registered_in_pilot",
        "interaction_sessions",
        "interaction_messages",
        "interaction_time_minutes",
        "interaction_new_prompt_versions",
    ]
    for col in merge_cols:
        if col in map_idx.columns and col in out.columns:
            mapped = out["pilot"].map(map_idx[col])
            out[col] = mapped.where(mapped.notna(), out[col])
    if "persisted_new_prompt_versions" in out.columns and "interaction_new_prompt_versions" in out.columns:
        out["persisted_new_prompt_versions"] = out["interaction_new_prompt_versions"]
    if "generated_prompt_versions_from_jobs" in out.columns and "interaction_new_prompt_versions" in out.columns:
        out["prompt_version_gap"] = (
            pd.to_numeric(out["generated_prompt_versions_from_jobs"], errors="coerce").fillna(0)
            - pd.to_numeric(out["interaction_new_prompt_versions"], errors="coerce").fillna(0)
        )
    return out


def readable_number(value: float | int) -> str:
    if abs(float(value) - int(float(value))) < 0.005:
        return f"{int(value):,}"
    return f"{float(value):,.2f}"


def compact_teacher_labels(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    if clean.empty:
        clean["teacher_label"] = []
        return clean
    clean["teacher_label"] = clean["plot_label"].fillna(clean["user_id"]).astype(str).str.strip()
    duplicate_mask = clean.duplicated(["pilot", "teacher_label"], keep=False)
    clean.loc[duplicate_mask, "teacher_label"] = (
        clean.loc[duplicate_mask, "teacher_label"]
        + " - "
        + clean.loc[duplicate_mask, "user_id"].astype(str).str.slice(0, 6)
    )
    return clean


def rank_label_across_pilots(df: pd.DataFrame) -> pd.Series:
    """Unique y-axis label per row when several pilots are combined (avoids duplicate-category bar bugs)."""
    p = df["pilot"].astype(str).str.replace("store_Pilot_", "", regex=False)
    t = df["teacher_label"].astype(str).str.strip()
    u = df["user_id"].astype(str).str.slice(0, 8)
    return t + " (" + p + " · " + u + ")"


def pilot_order(df: pd.DataFrame) -> list[str]:
    if "pilot" not in df:
        return []
    return sorted(df["pilot"].dropna().unique().tolist())


def chart_layout(fig: Any) -> Any:
    fig.update_layout(
        font_family="Source Serif 4, Georgia, serif",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,250,240,0.78)",
        margin=dict(l=24, r=24, t=56, b=34),
        legend_title_text="",
    )
    # Setting title_font without a real title (e.g. make_subplots with only subplot_titles) can
    # serialize as title.text = null; Streamlit's Plotly embed may then show the word "undefined".
    title_text: str | None = None
    if fig.layout.title is not None:
        title_text = getattr(fig.layout.title, "text", None)
    if title_text:
        fig.update_layout(
            title_font=dict(family="Fraunces, Georgia, serif", size=22, color=THEME["ink"]),
        )
    else:
        fig.update_layout(title_text="")
    fig.update_xaxes(showgrid=False, linecolor=THEME["line"])
    fig.update_yaxes(gridcolor="rgba(99,112,109,0.16)", linecolor=THEME["line"])
    return fig


# Excel Summary charts use a single blue for all columns (see analyze_pilot_studies add_chart).
EXCEL_STYLE_BAR = "#5B8FF9"


def overview_pilot_comparison_figure(df: pd.DataFrame, *, uirevision: str = "") -> go.Figure:
    """Three column charts in one full-width figure (avoids squashed/buggy sub-layout in narrow columns)."""
    d = df.copy()
    d["_pilot"] = d["pilot"].astype(str)
    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=(
            "Messages by Pilot",
            "Time Spent by Pilot (Minutes)",
            "New Prompt Versions by Pilot",
        ),
        horizontal_spacing=0.08,
    )
    series_spec = [
        (1, "interaction_messages", "Messages"),
        (2, "interaction_time_minutes", "Minutes"),
        (3, "interaction_new_prompt_versions", "New prompt versions"),
    ]
    for col, metric, ylabel in series_spec:
        yv = pd.to_numeric(d[metric], errors="coerce").fillna(0.0)
        y_list = [float(x) for x in yv.tolist()]
        x_list = d["_pilot"].tolist()
        fig.add_trace(
            go.Bar(
                x=x_list,
                y=y_list,
                marker=dict(color=EXCEL_STYLE_BAR, line=dict(width=0)),
                text=[readable_number(v) for v in y_list],
                textposition="outside",
                cliponaxis=False,
                hovertemplate=f"<b>%{{x}}</b><br>{ylabel}: %{{y:,.2f}}<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=col,
        )
        hi = float(yv.max()) if len(yv) else 0.0
        fig.update_yaxes(title_text=ylabel, range=[0, max(hi * 1.28, 0.1)], row=1, col=col)
        fig.update_xaxes(type="category", title_text="Pilot", tickangle=0, row=1, col=col)
    ul: dict[str, Any] = dict(height=450, barmode="group", margin=dict(t=64, b=72))
    if uirevision:
        ul["uirevision"] = uirevision
    fig.update_layout(**ul)
    return chart_layout(fig)


def registration_stacked_bar_figure(df: pd.DataFrame, *, uirevision: str = "") -> go.Figure:
    """Stacked bars built directly from summary columns (avoids px+melt / Streamlit stale-figure issues)."""
    if df.empty:
        return chart_layout(go.Figure())
    d = df.sort_values("pilot").copy()
    pilots = d["pilot"].astype(str).tolist()
    reg = pd.to_numeric(d["interaction_user_ids_registered_in_pilot"], errors="coerce").fillna(0.0)
    nreg = pd.to_numeric(d["interaction_user_ids_not_registered_in_pilot"], errors="coerce").fillna(0.0)
    reg_l = [float(x) for x in reg.tolist()]
    nreg_l = [float(x) for x in nreg.tolist()]
    stack_max = max((r + n for r, n in zip(reg_l, nreg_l)), default=0.0)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Registered in users.json",
            x=pilots,
            y=reg_l,
            marker_color=THEME["green"],
            text=[readable_number(v) for v in reg_l],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate="<b>%{x}</b><br>Registered in users.json: %{y:.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Not in users.json",
            x=pilots,
            y=nreg_l,
            marker_color=THEME["red"],
            text=[readable_number(v) for v in nreg_l],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate="<b>%{x}</b><br>Not in users.json: %{y:.0f}<extra></extra>",
        )
    )
    layout: dict[str, Any] = {
        "title": "Interaction User IDs by Registration Status",
        "barmode": "stack",
        "height": 430,
        "xaxis_title": "pilot",
        "yaxis_title": "count",
        "yaxis": dict(range=[0, max(stack_max * 1.2, 1.0)]),
        "legend": dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0),
    }
    if uirevision:
        layout["uirevision"] = uirevision
    fig.update_layout(**layout)
    return chart_layout(fig)


def prompt_pipeline_figure(df: pd.DataFrame, *, uirevision: str = "") -> go.Figure:
    """Grouped bars from persisted vs job columns (same data as caption / summary table)."""
    if df.empty:
        return chart_layout(go.Figure())
    d = df.sort_values("pilot").copy()
    pilots = d["pilot"].astype(str).tolist()
    pers = pd.to_numeric(d["persisted_new_prompt_versions"], errors="coerce").fillna(0.0)
    jobs = pd.to_numeric(d["generated_prompt_versions_from_jobs"], errors="coerce").fillna(0.0)
    pers_l = [float(x) for x in pers.tolist()]
    jobs_l = [float(x) for x in jobs.tolist()]
    mx = max(max(pers_l, default=0.0), max(jobs_l, default=0.0), 1.0)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Persisted prompt_versions.json",
            x=pilots,
            y=pers_l,
            marker_color=THEME["blue"],
            text=[readable_number(v) for v in pers_l],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Persisted: %{y:.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Done improvement jobs",
            x=pilots,
            y=jobs_l,
            marker_color=THEME["ochre"],
            text=[readable_number(v) for v in jobs_l],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Done jobs: %{y:.0f}<extra></extra>",
        )
    )
    layout: dict[str, Any] = {
        "title": "Prompt Version Generation Signals",
        "barmode": "group",
        "bargap": 0.22,
        "height": 480,
        "xaxis_title": "pilot",
        "yaxis_title": "count",
        "yaxis": dict(range=[0, mx * 1.25]),
        "legend": dict(orientation="h", yanchor="bottom", y=1.06, xanchor="right", x=1.0),
    }
    if uirevision:
        layout["uirevision"] = uirevision
    fig.update_layout(**layout)
    return chart_layout(fig)


def messages_time_scatter_figure(df: pd.DataFrame) -> go.Figure:
    """Explicit go.Scatter traces (px.scatter can render empty with size encoding in some Streamlit/Plotly builds)."""
    d = df.copy()
    d["messages"] = pd.to_numeric(d["messages"], errors="coerce")
    d["time_minutes"] = pd.to_numeric(d["time_minutes"], errors="coerce")
    d["sessions"] = pd.to_numeric(d["sessions"], errors="coerce")
    d = d.dropna(subset=["messages", "time_minutes"])
    d["sessions"] = d["sessions"].fillna(1).clip(lower=1)
    if d.empty:
        return go.Figure(
            layout=dict(
                title="Messages vs time spent",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,250,240,0.78)",
            )
        )
    label_col = "rank_axis_label" if "rank_axis_label" in d.columns else "teacher_label"
    color_map = {
        "store_Pilot_v0": THEME["blue"],
        "store_Pilot_v1": THEME["ochre"],
        "store_Pilot_v2": THEME["green"],
    }
    fig = go.Figure()
    for pilot in sorted(d["pilot"].dropna().unique(), key=str):
        sub = d[d["pilot"] == pilot]
        if sub.empty:
            continue
        smax = float(sub["sessions"].max() or 1.0)
        sizes = (7.0 + 21.0 * (sub["sessions"].astype(float) / smax)).clip(7.0, 28.0).tolist()
        col = color_map.get(pilot, THEME["red"])
        fig.add_trace(
            go.Scatter(
                x=sub["messages"].astype(float).tolist(),
                y=sub["time_minutes"].astype(float).tolist(),
                mode="markers",
                name=str(pilot).replace("store_", ""),
                text=sub[label_col].astype(str).tolist(),
                marker=dict(
                    size=sizes,
                    color=col,
                    line=dict(width=0.5, color="rgba(0,0,0,0.25)"),
                    opacity=0.92,
                ),
                hovertemplate="%{text}<br>Messages: %{x:,.0f}<br>Time: %{y:,.1f} min<extra></extra>",
            )
        )
    max_x = float(d["messages"].max()) or 0.0
    max_y = float(d["time_minutes"].max()) or 0.0
    fig.update_layout(
        title="Messages vs time spent",
        height=520,
        font_family="Source Serif 4, Georgia, serif",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,250,240,0.78)",
        margin=dict(l=24, r=24, t=56, b=50),
        title_font=dict(family="Fraunces, Georgia, serif", size=20, color=THEME["ink"]),
        xaxis_title="Messages",
        yaxis_title="Time (minutes)",
        xaxis=dict(
            range=[0, max(max_x * 1.06, 3)],
            showgrid=True,
            gridcolor="rgba(99,112,109,0.2)",
            zerolinecolor=THEME["line"],
        ),
        yaxis=dict(
            range=[0, max(max_y * 1.06, 3)],
            showgrid=True,
            gridcolor="rgba(99,112,109,0.2)",
            zerolinecolor=THEME["line"],
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1.0, title=""),
    )
    return fig


def horizontal_rank_chart(
    df: pd.DataFrame,
    metric: str,
    title: str,
    x_title: str,
    *,
    label_col: str = "teacher_label",
    sort_by: str | None = None,
    preserve_order: bool = False,
    bar_color: str | None = None,
    y_axis_title: str = "Teacher",
) -> go.Figure:
    """Horizontal bars: one row per user. Best (highest metric) is drawn at the top of the list."""
    chart_df = df.copy()
    chart_df[metric] = pd.to_numeric(chart_df[metric], errors="coerce").fillna(0.0)
    if preserve_order:
        pass  # follow df row order (e.g. workbook: table order = best message count first)
    else:
        sort_key = sort_by or metric
        chart_df = chart_df.sort_values(sort_key, ascending=False).copy()
    if chart_df.empty:
        return chart_layout(
            go.Figure().update_layout(
                title=title,
                annotations=[dict(text="No data", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)],
            )
        )
    # Plotly: first y category in categoryarray = top of the chart (match leaderboard).
    y_order = chart_df[label_col].astype(str).tolist()
    color_map = {
        "store_Pilot_v0": THEME["blue"],
        "store_Pilot_v1": THEME["ochre"],
        "store_Pilot_v2": THEME["green"],
    }
    fig = go.Figure()
    if bar_color:
        fig.add_trace(
            go.Bar(
                x=chart_df[metric].astype(float).tolist(),
                y=y_order,
                orientation="h",
                marker_color=bar_color,
                text=[readable_number(v) for v in chart_df[metric]],
                textposition="outside",
                name="",
                showlegend=False,
                hovertemplate=f"<b>%{{y}}</b><br>{x_title}: %{{x:,.2f}}<extra></extra>",
            )
        )
    else:
        # One trace per pilot so the legend is meaningful and y categories are never merged badly.
        for pilot in sorted(chart_df["pilot"].dropna().unique(), key=str):
            sub = chart_df[chart_df["pilot"] == pilot]
            if sub.empty:
                continue
            pc = color_map.get(pilot, THEME["red"])
            fig.add_trace(
                go.Bar(
                    x=sub[metric].astype(float).tolist(),
                    y=sub[label_col].astype(str).tolist(),
                    orientation="h",
                    marker_color=pc,
                    name=pilot.replace("store_", ""),
                    text=[readable_number(v) for v in sub[metric]],
                    textposition="outside",
                    customdata=sub[["user_id", "registered_in_pilot", "sessions"]],
                    hovertemplate=(
                        f"<b>%{{y}}</b><br>{x_title}: %{{x:,.2f}}<br>"
                        "User ID: %{customdata[0]}<br>"
                        "Registered: %{customdata[1]}<br>"
                        "Sessions: %{customdata[2]}<extra></extra>"
                    ),
                )
            )
    max_value = float(chart_df[metric].max()) if not chart_df.empty else 0.0
    layout: dict[str, Any] = {
        "title": title,
        "height": max(430, 28 * len(chart_df) + 150),
        "barmode": "overlay",
        "bargap": 0.35,
        "xaxis_title": x_title,
        "yaxis_title": y_axis_title,
        "xaxis": dict(range=[0, max(max_value * 1.2, 0.5)]),
    }
    if not bar_color:
        layout["legend"] = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0)
    fig.update_layout(**layout)
    fig = chart_layout(fig)
    # Re-apply category order after chart_layout (so yaxis settings are not lost).
    fig.update_yaxes(
        type="category",
        categoryorder="array",
        categoryarray=y_order,
    )
    return fig


st.markdown(
    """
    <div class="hero">
      <div class="hero-eyebrow">Pilot monitoring dashboard</div>
      <div class="hero-title">Tutor Bot Teacher Interaction Monitor</div>
      <div class="hero-copy">
        Track how teachers interact with the tutor bot across pilot studies, including messages,
        time spent, prompt evolution, improvement jobs, and data-quality gaps.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


def _prune_stale_session_upload() -> None:
    zroot = st.session_state.get("session_upload_root")
    zbase = st.session_state.get("session_zip_base")
    if not zroot:
        return
    if not Path(zroot).exists() or (zbase and not Path(zbase).exists()):
        for k, v in (("session_upload_root", None), ("session_zip_base", None), ("last_zip_md5", None)):
            st.session_state[k] = v


def _ensure_upload_state_keys() -> None:
    st.session_state.setdefault("session_upload_root", None)
    st.session_state.setdefault("session_zip_base", None)
    st.session_state.setdefault("last_zip_md5", None)


with st.sidebar:
    st.subheader("Load pilot data (ZIP)")
    st.caption(
        "For Streamlit Cloud, upload a .zip. It must have one parent folder with "
        "store_Pilot_v0, store_Pilot_v1, … as direct children." 
    )
    _ensure_upload_state_keys()
    _prune_stale_session_upload()
    f = st.file_uploader("Pilot export .zip (optional)", type=["zip"], key="pilot_zip_uploader")
    if f is not None and f.getvalue():
        b = f.getvalue()
        h = hashlib.md5(b).hexdigest()
        if h != st.session_state.get("last_zip_md5"):
            try:
                root, base = extract_pilot_zip_to_temp(b)
            except (ValueError, FileNotFoundError, zipfile.BadZipFile) as e:
                st.error(str(e))
            except OSError as e:
                st.error(f"Failed to read or extract the zip: {e}")
            else:
                old_b = st.session_state.get("session_zip_base")
                if old_b and str(old_b) != str(base) and Path(old_b).exists():
                    shutil.rmtree(old_b, ignore_errors=True)
                st.session_state["last_zip_md5"] = h
                st.session_state["session_upload_root"] = str(root)
                st.session_state["session_zip_base"] = str(base)
                load_dashboard_data.clear()
                st.rerun()
    if st.session_state.get("session_upload_root") and Path(st.session_state["session_upload_root"]).exists():
        st.info("Session is using the last uploaded zip (in-memory; temp is cleared on server restart).")
        if st.button("Remove uploaded data", use_container_width=True, key="remove_zip_upload"):
            b = st.session_state.get("session_zip_base")
            if b and Path(b).exists():
                shutil.rmtree(b, ignore_errors=True)
            st.session_state["session_upload_root"] = None
            st.session_state["session_zip_base"] = None
            st.session_state["last_zip_md5"] = None
            load_dashboard_data.clear()
            st.rerun()

    st.header("Controls")
    using_upload = bool(
        st.session_state.get("session_upload_root")
        and Path(st.session_state["session_upload_root"]).exists()
    )
    if using_upload:
        up = st.session_state["session_upload_root"]
        st.text_input("Data root", value=up, disabled=True, help="Data source from the uploaded zip in this session.")
        data_root = up
    else:
        data_root = st.text_input(
            "Data root",
            value=_DEFAULT_DATA_ROOT,
            help="Folder that contains the store_Pilot_v* directories. On a server you can set the "
            "environment variable TUTOR_BOT_DATA_ROOT instead of typing here.",
            key="manual_data_root_input",
        )
    refresh = st.button("Refresh data from disk", use_container_width=True)
    if refresh:
        load_dashboard_data.clear()

    signature = dataset_signature(Path(data_root))
    data = load_dashboard_data(data_root, signature)
    summary_df = make_df(data["summary"])
    users_df = make_df(data["users"])
    quality_df = make_df(data["quality"])

    numeric_summary_cols = [
        "registered_users",
        "interaction_user_ids_total",
        "interaction_user_ids_registered_in_pilot",
        "interaction_user_ids_not_registered_in_pilot",
        "interaction_sessions",
        "interaction_messages",
        "interaction_time_minutes",
        "interaction_new_prompt_versions",
        "persisted_new_prompt_versions",
        "generated_prompt_versions_from_jobs",
        "prompt_version_gap",
    ]  # interaction_new_prompt_versions == persisted in interaction view; both coerced
    numeric_user_cols = [
        "sessions",
        "message_files",
        "messages",
        "time_minutes",
        "new_prompt_versions",
        "generated_prompt_versions_from_jobs",
        "prompt_version_gap",
    ]
    summary_df = coerce_numeric(summary_df, numeric_summary_cols)
    users_df = coerce_numeric(users_df, numeric_user_cols)

    available_pilots = pilot_order(summary_df)
    selected_pilots = st.multiselect("Pilot studies", options=available_pilots, default=available_pilots)
    top_n = st.slider("Top users per chart (same as Excel per-pilot sheets)", min_value=5, max_value=20, value=10, step=1)
    include_unregistered = st.toggle(
        "Include user IDs not in users.json",
        value=True,
        help="Applies to Teacher engagement charts and the teacher detail table only. "
        "It does not change Overview summary metrics or the registration stacked bar (those always reflect all interaction user IDs).",
    )
    teacher_view = st.radio(
        "Teacher charts",
        options=("match_workbook", "compare_pilots"),
        format_func=lambda x: "Per pilot (workbook: top users on each pilot sheet)"
        if x == "match_workbook"
        else "Across pilots (scatter + combined rankings)",
        help="The Excel workbook has one tab per pilot with top-10 bar charts. "
        "Use 'Per pilot' to mirror that. Use 'Across pilots' to compare everyone together.",
    )


if summary_df.empty:
    st.warning(
        "No pilot folders were found. Upload a .zip in the sidebar (one folder containing store_Pilot_v0, "
        "store_Pilot_v1, …) or set Data root to a path with those folders, then refresh."
    )
    st.stop()

summary_view = summary_df[summary_df["pilot"].isin(selected_pilots)].copy()
users_view = users_df[users_df["pilot"].isin(selected_pilots)].copy()
quality_view = quality_df[quality_df["pilot"].isin(selected_pilots)].copy()
if not include_unregistered and not users_view.empty:
    users_view = users_view[users_view["registered_in_pilot"]].copy()
users_view = compact_teacher_labels(users_view)

if not selected_pilots:
    st.warning("Select at least one pilot study in the sidebar to load charts and tables.")
    st.stop()

# Align with Excel Summary: same numbers as pilot_interaction_user_summary.csv / workbook
summary_view = apply_interaction_summary_csv(Path(data_root), summary_view)

total_registered = int(summary_view["registered_users"].sum()) if not summary_view.empty else 0
total_interaction_ids = int(summary_view["interaction_user_ids_total"].sum()) if not summary_view.empty else 0
total_messages = int(summary_view["interaction_messages"].sum()) if not summary_view.empty else 0
total_minutes = float(summary_view["interaction_time_minutes"].sum()) if not summary_view.empty else 0.0
total_jobs = int(summary_view["generated_prompt_versions_from_jobs"].sum()) if not summary_view.empty else 0
total_persisted_prompts = int(summary_view["persisted_new_prompt_versions"].sum()) if not summary_view.empty else 0

metric_cols = st.columns(6)
metric_cols[0].metric("Registered users", f"{total_registered:,}")
metric_cols[1].metric("Interaction user IDs", f"{total_interaction_ids:,}")
metric_cols[2].metric("Messages", f"{total_messages:,}")
metric_cols[3].metric("Time spent (mins)", f"{total_minutes:,.0f} min")
metric_cols[4].metric("Generated prompts", f"{total_jobs:,}")
metric_cols[5].metric("Persisted prompts", f"{total_persisted_prompts:,}")

st.divider()

overview_tab, teacher_tab, prompt_tab, data_tab = st.tabs(
    ["Overview", "Teacher engagement", "Prompt pipeline", "Tables & data quality"]
)

with overview_tab:
    st.subheader("Pilot comparison (matches Excel Summary sheet charts)")
    st.markdown(
        '<div class="section-note">Same three column charts as <code>pilot_interaction_view_workbook.xlsx</code> &mdash; '
        "messages, time (minutes), and new prompt versions &mdash; one bar per pilot in each. "
        "If <code>pilot_interaction_user_summary.csv</code> is present (written with the workbook by "
        "<code>analyze_pilot_studies.py</code>), its values are used so the charts match that file and the xlsx.</div>",
        unsafe_allow_html=True,
    )
    st.plotly_chart(overview_pilot_comparison_figure(summary_view, uirevision=signature), use_container_width=True)

    st.subheader("Interaction user IDs (registration split)")
    st.markdown(
        '<div class="section-note">'
        "This chart is <b>not</b> &ldquo;how many people are in <code>users.json</code>&rdquo; as a single number. "
        "The top metrics row has <b>Registered users</b> for that. Here, the bar is built only from user IDs that appear in "
        "<b>interaction data</b> (messages, sessions, or new prompt versions). The total bar height is the count of "
        "<b>distinct</b> such IDs, split into: already listed in that pilot&rsquo;s <code>users.json</code> (green) vs not (red). "
        "That total should match the Excel <b>Interaction User IDs</b> column (and green/red match "
        "<i>Registered / Non-Registered Interaction IDs</i>). "
        "If your bars look far smaller than the Summary table or the Excel you generated from the <i>full</i> <code>store_Pilot_vX</code> folders, "
        "set <b>Data root</b> in the sidebar to the project folder that actually contains those directories (a truncated path can load the wrong or partial data). "
        "<b>Not affected</b> by the &ldquo;Include user IDs not in users.json&rdquo; toggle &mdash; that only filters Teacher engagement.</div>",
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        registration_stacked_bar_figure(summary_view, uirevision=signature),
        use_container_width=True,
    )
    if not summary_view.empty:
        check_bits = []
        for _, r in summary_view.iterrows():
            tot = int(r["interaction_user_ids_total"])
            reg = int(r["interaction_user_ids_registered_in_pilot"])
            nreg = int(r["interaction_user_ids_not_registered_in_pilot"])
            check_bits.append(f"{r['pilot']}: {tot} interaction user IDs total ({reg} green + {nreg} red)")
        st.caption(" · ".join(check_bits))

with teacher_tab:
    st.subheader("Teacher engagement")
    if users_view.empty:
        st.info("No teacher interaction rows match the selected filters.")
    elif teacher_view == "match_workbook":
        st.markdown(
            '<div class="section-note">Matches each per-pilot Excel tab: horizontal bars use the <b>Plot label</b> column, '
            "same blue as the workbook, and the time chart uses the <b>same users</b> as the message chart (sorted by messages, then time, then user id).</div>",
            unsafe_allow_html=True,
        )
        sheet_pilot = st.selectbox(
            "Pilot tab",
            options=selected_pilots,
            format_func=lambda p: p.replace("store_", ""),
            help="Each store_Pilot_vX folder has a matching sheet in the workbook with two charts.",
        )
        pilot_users = users_view[users_view["pilot"] == sheet_pilot].copy()
        ranked = (
            pilot_users.sort_values(
                by=["messages", "time_minutes", "user_id"],
                ascending=[False, False, True],
            )
            .head(top_n)
            .copy()
        )
        n_show = len(ranked)
        wb_left, wb_right = st.columns(2, gap="medium")
        with wb_left:
            st.plotly_chart(
                horizontal_rank_chart(
                    ranked,
                    "messages",
                    f"Top {n_show} users by messages",
                    "Messages",
                    preserve_order=True,
                    bar_color=EXCEL_STYLE_BAR,
                    y_axis_title="Plot label",
                ),
                use_container_width=True,
            )
        with wb_right:
            st.plotly_chart(
                horizontal_rank_chart(
                    ranked,
                    "time_minutes",
                    f"Top {n_show} users by time (same people as left)",
                    "Minutes",
                    preserve_order=True,
                    bar_color=EXCEL_STYLE_BAR,
                    y_axis_title="Plot label",
                ),
                use_container_width=True,
            )
    else:
        st.markdown(
            '<div class="section-note">Scatter compares all selected pilots. Rankings use <b>top '
            + str(top_n)
            + "</b> users by each metric (independent sorts &mdash; not the same cohort as the workbook sheet).</div>",
            unsafe_allow_html=True,
        )
        users_cmp = users_view.copy()
        users_cmp["rank_axis_label"] = rank_label_across_pilots(users_cmp)
        st.plotly_chart(messages_time_scatter_figure(users_cmp), use_container_width=True)

        rank_left, rank_right = st.columns(2, gap="medium")
        with rank_left:
            top_messages = users_cmp.sort_values(["messages", "time_minutes"], ascending=False).head(top_n).copy()
            st.plotly_chart(
                horizontal_rank_chart(
                    top_messages,
                    "messages",
                    f"Top {top_n} by messages (all selected pilots)",
                    "Messages",
                    label_col="rank_axis_label",
                ),
                use_container_width=True,
            )
        with rank_right:
            top_time = users_cmp.sort_values(["time_minutes", "messages"], ascending=False).head(top_n).copy()
            st.plotly_chart(
                horizontal_rank_chart(
                    top_time,
                    "time_minutes",
                    f"Top {top_n} by time (all selected pilots)",
                    "Minutes",
                    label_col="rank_axis_label",
                ),
                use_container_width=True,
            )

with prompt_tab:
    st.subheader("Prompt improvement pipeline")
    st.markdown(
        '<div class="section-note">Not in the interaction-view Excel workbook (that file only has <b>New Prompt Versions</b> from the interaction summary). '
        "Here the <b>blue</b> bar is the <b>interaction</b> total of <code>prompt_versions.json</code> records with an integer <code>version_number</code> greater than zero (same rule as the analysis script). "
        "The <b>gold</b> bar counts <code>improvement_jobs.json</code> entries with <code>status=done</code> and a <code>result_prompt_version_id</code>. "
        "Those are independent: jobs can be marked done and store a result ID even if this export&rsquo;s <code>prompt_versions.json</code> has no matching rows (e.g. empty file, only v0, or not re-exported), so for a pilot you can see <b>0 persisted</b> and <b>many done jobs</b>.</div>",
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        prompt_pipeline_figure(summary_view, uirevision=signature),
        use_container_width=True,
    )
    if not summary_view.empty:
        prompt_bits = []
        for _, r in summary_view.iterrows():
            p = int(pd.to_numeric(r["persisted_new_prompt_versions"], errors="coerce") or 0)
            j = int(pd.to_numeric(r["generated_prompt_versions_from_jobs"], errors="coerce") or 0)
            prompt_bits.append(f"{r['pilot']}: persisted {p}, done jobs {j}")
        st.caption(" · ".join(prompt_bits))


with data_tab:
    tab_summary, tab_teachers, tab_quality = st.tabs(["Summary table", "Teacher detail", "Data quality"])

    with tab_summary:
        st.dataframe(summary_view, use_container_width=True, hide_index=True)
        st.download_button(
            "Download summary CSV",
            summary_view.to_csv(index=False).encode("utf-8"),
            "pilot_interaction_dashboard_summary.csv",
            "text/csv",
            use_container_width=True,
        )

    with tab_teachers:
        teacher_columns = [
            "pilot",
            "teacher_label",
            "user_id",
            "registered_in_pilot",
            "sessions",
            "message_files",
            "messages",
            "time_minutes",
            "new_prompt_versions",
            "generated_prompt_versions_from_jobs",
            "prompt_version_gap",
        ]
        st.dataframe(users_view[teacher_columns], use_container_width=True, hide_index=True)
        st.download_button(
            "Download teacher detail CSV",
            users_view[teacher_columns].to_csv(index=False).encode("utf-8"),
            "pilot_interaction_dashboard_teacher_detail.csv",
            "text/csv",
            use_container_width=True,
        )

    with tab_quality:
        st.dataframe(quality_view, use_container_width=True, hide_index=True)
        st.info(
            "For dynamic updates: add or update store_Pilot_vX folders, then press Refresh data from disk. "
            "The app discovers pilot folders automatically and reloads cached data whenever source JSON files change."
        )
