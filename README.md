# Tutor Bot Pilot Monitor

Streamlit dashboard for monitoring tutor bot pilot study exports: engagement metrics, teacher rankings, prompt pipeline checks, and data-quality flags.

## What is in the repo

- `dashboard_app.py` — Streamlit app
- `analyze_pilot_studies.py` — batch analysis (optional local use)
- `requirements.txt` — Python dependencies for deployment

## Local run

```powershell
cd tutor-bot-interactions
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run dashboard_app.py
```

Place or symlink your `store_Pilot_v0`, `store_Pilot_v1`, … folders next to the app (or set **Data root** in the UI).

### Optional: default data directory via environment

On a server, set the directory that contains the pilot stores (same parent folder the app would use when opened locally):

```powershell
$env:TUTOR_BOT_DATA_ROOT = "C:\path\to\folder\containing\store_Pilot_vX"
streamlit run dashboard_app.py
```

Linux example:

```bash
export TUTOR_BOT_DATA_ROOT=/data/tutor-exports
streamlit run dashboard_app.py
```

## Deploy to Streamlit Community Cloud (GitHub)

1. Create a new **empty** repository on GitHub (any name, e.g. `tutor-bot-interactions`).

2. From this project folder (with Git), add the remote and push:

   ```powershell
   git init
   git add .
   git status
   git commit -m "Initial commit: Tutor Bot Pilot Monitor (no pilot data in repo)"
   git branch -M main
   git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
   git push -u origin main
   ```

3. Open [Streamlit Community Cloud](https://share.streamlit.io/), sign in with GitHub, **New app** → select the repo, branch `main`, main file **`dashboard_app.py`**. Choose a Python version (e.g. 3.12) in the deploy flow if prompted.

4. **Important:** the Cloud run has **no access** to your laptop’s `C:\...` path. The app will start with an **empty** data root unless you:
   - host the app on **your own** machine/VM and set `TUTOR_BOT_DATA_ROOT` to a folder that holds the stores, or  
   - add other integrations (S3, secrets) yourself — not included here.

   For a **private** dataset, Community Cloud is usually not the right place unless you ship data by another mechanism. Prefer **self-hosted** Streamlit (same `streamlit run` on a server with the data on disk) or **Docker** on a VM with a volume mount.

## Self-hosting on a server (recommended for real pilot data)

1. Clone the repo (or copy files) onto the host.
2. Install Python 3.12+ and `pip install -r requirements.txt`.
3. Copy the `store_Pilot_v*` tree to a path on that server, e.g. `/data/pilots/`.
4. Set `TUTOR_BOT_DATA_ROOT=/data/pilots` and run under `screen`, `systemd`, or a process manager, or use Docker.
5. Put the app behind your org’s reverse proxy and authentication if the data is sensitive.

## Regenerating the Excel/CSV (optional, on a machine with data)

```powershell
python analyze_pilot_studies.py
```

This writes CSV/JSON/Excel under the data root; those outputs are **gitignored** by default.
