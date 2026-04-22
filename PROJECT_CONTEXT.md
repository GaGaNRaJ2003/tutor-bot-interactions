# Tutor Bot Pilot Dashboard Context

## Purpose

This workspace exists to analyze tutor bot pilot study data and make the results easier to inspect. The root project collects versioned pilot exports, computes engagement and data-quality metrics, and presents them through a Streamlit dashboard for quick monitoring.

The main questions this project helps answer are:

- How many teachers or user IDs interacted with the tutor bot in each pilot?
- How much activity happened across sessions, messages, time spent, and prompt versions?
- Which teachers were most active?
- Are there data-quality gaps, such as message/session/prompt records for user IDs not present in `users.json`?
- Do generated improvement jobs line up with persisted prompt versions?

## Root Project Structure

The project root is the working directory for both analysis and dashboard usage.

- `store_Pilot_v0/`, `store_Pilot_v1/`, `store_Pilot_v2/`: versioned pilot data exports.
- `analyze_pilot_studies.py`: batch analysis script that reads the pilot folders and writes CSV, JSON, and Excel reporting outputs.
- `dashboard_app.py`: Streamlit dashboard for interactive pilot monitoring.
- `requirements-dashboard.txt`: Python dependencies required for the dashboard and analysis tooling.
- `pilot_*_summary.csv`, `pilot_*_details.csv`: generated tabular analysis outputs.
- `pilot_*_analysis.json`: generated machine-readable analysis outputs.
- `pilot_interaction_view_workbook.xlsx`: generated Excel workbook with summaries, details, and charts.

## Pilot Data Layout

Each `store_Pilot_vX` folder is expected to contain a consistent JSON export structure:

- `users.json`: registered users for that pilot.
- `sessions.json`: tutor bot session records.
- `prompt_versions.json`: prompt versions created or persisted during the pilot.
- `feedback.json`: feedback data captured during interactions.
- `improvement_jobs.json`: generated prompt improvement jobs and their status.
- `messages/`: per-user message files, grouped by user ID and session/message file.

The dashboard and analysis script discover pilot folders automatically by looking for directory names that start with `store_Pilot_v`.

## Analysis Script

`analyze_pilot_studies.py` is the batch/reporting layer. It reads all pilot folders and creates:

- registered-user summaries and details;
- interaction-user summaries and details;
- JSON analysis files;
- an Excel workbook with summary sheets, per-pilot user sheets, and charts.

It calculates metrics such as registered users, active registered users, sessions, messages, observed interaction time, new prompt versions, and orphaned user IDs found in messages/sessions/prompts but missing from `users.json`.

Run it from the project root with:

```powershell
python .\analyze_pilot_studies.py
```

## Streamlit Dashboard

`dashboard_app.py` is the interactive monitoring layer. It imports core analysis helpers from `analyze_pilot_studies.py`, reads pilot JSON exports directly, and builds live dashboard views with Pandas and Plotly.

The dashboard includes:

- overall pilot comparison metrics;
- pilot filtering controls;
- top teacher rankings by messages and time spent;
- message/time/session/prompt charts;
- prompt pipeline checks comparing completed improvement jobs to persisted prompt versions;
- tables for detailed inspection and data-quality issues.

Run it from the project root with:

```powershell
streamlit run .\dashboard_app.py
```

## Data Flow

The project has two related data flows:

1. Batch reporting:
   `store_Pilot_vX` JSON exports -> `analyze_pilot_studies.py` -> CSV, JSON, and XLSX outputs.

2. Interactive monitoring:
   `store_Pilot_vX` JSON exports -> `dashboard_app.py` -> Streamlit charts, metrics, filters, and tables.

The dashboard recomputes metrics from the raw pilot folders and uses a dataset signature based on JSON file timestamps and sizes to refresh cached data when files change.

## Interpretation Notes

- "Registered users" means users present in a pilot folder's `users.json`.
- "Interaction user IDs" means any user ID observed in sessions, messages, or prompt versions.
- Some interaction user IDs may not appear in the pilot's `users.json`; these are surfaced as data-quality gaps rather than silently ignored.
- "Observed time" is estimated from the first and last message timestamps within message files. It is useful for comparison, but it is not necessarily a complete measure of time spent in the product.
- "Generated prompt versions from jobs" counts completed improvement jobs with a resulting prompt version ID.
- "Persisted prompt versions" counts prompt versions found in `prompt_versions.json` with a positive version number.

## Intended Use

Use this project when reviewing tutor bot pilot performance across versions. The batch script is best for producing shareable files and archived reporting artifacts. The Streamlit dashboard is best for quick exploration, filtering, and spotting engagement patterns or data inconsistencies during pilot review.
