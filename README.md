## Zip layout for in-browser upload (Streamlit Community Cloud, etc.)

The Streamlit app can extract a **session-only** copy of your exports from a `.zip` (your laptop’s `C:\...` is not available to the host).

1. Create **one** folder (any name) whose **children** are `store_Pilot_v0`, `store_Pilot_v1`, … (each folder holds that pilot’s JSON and related files as usual).
2. Zip **that** folder (on Windows, right-click the parent folder → Send to → Compressed folder).
3. In the app sidebar, upload the zip. Data stays in a temp directory for the **session** and is **cleared** when the app restarts or you click **Remove uploaded data**. Do not upload if the data is highly sensitive: anyone with the app URL and access could upload and view; treat zips as confidential the same as the raw folders.

[Streamlit Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud) limits upload size (tens of MB; check current docs). For huge exports, self-host with `TUTOR_BOT_DATA_ROOT` and disk paths instead.

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

4. **Important:** the Cloud run has **no access** to your laptop’s `C:\...` path. Use the sidebar **Load pilot data (ZIP)** to upload a zip built as in the section above, or set **Data root** on a self-hosted deploy where a path is valid.

   For **confidential** pilot data, prefer **self-hosted** Streamlit with `TUTOR_BOT_DATA_ROOT` (or a VM volume) rather than a public share URL, unless you understand who can open the app and upload.

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
