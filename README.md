# Tutor Bot — Pilot study dashboard

This app helps you **explore pilot-study data**: summaries, how teachers engaged, and quality-related views. You open it in a web browser (using the link you were given) and **load your own export** so you can see charts and tables for your pilots.

---

## Before you start

- You need the **pilot export folders** from your project — usually named `store_Pilot_v0`, `store_Pilot_v1`, and so on, each with JSON and related files inside.
- The live app (for example on Streamlit Cloud) **cannot see your computer’s files by path**. To use it online, you will **upload a zip** you create on your machine. If your team runs the app on an internal server with data already on disk, you may not need a zip; ask whoever gave you the link.

---

## Load your data with a zip (typical for the hosted link)

### 1. Put all pilot folders in one place

Create **one folder** (name it anything you like). **Inside that folder only**, you should have your pilot export folders, for example:

- `store_Pilot_v0`
- `store_Pilot_v1`
- … and any other `store_Pilot_v…` folders you use  

Nothing special is required in the *parent* folder name — it only has to **contain** those `store_Pilot_v…` folders as **direct** subfolders.

### 2. Zip that parent folder

- **Windows:** Right‑click the **parent** folder (the one that contains `store_Pilot_v0`, …) → **Send to** → **Compressed (zipped) folder**.
- **macOS:** Right‑click the parent folder → **Compress**.

### 3. Open the app and upload

1. Open the dashboard in your browser (the URL from your team).
2. In the **sidebar**, find **Load pilot data (ZIP)** and choose your `.zip` file.
3. Wait for the app to process it. The sidebar will show that you are using data from the last upload in this **session**.

### 4. Refresh and explore

- Use **Refresh data from disk** in the sidebar if you change something and the numbers look stale.
- Use **Remove uploaded data** when you want to clear what was loaded from the zip in this session.

### What to expect

- Data loaded from a zip is kept only **for this browser session** (and may be **lost if the app restarts** on the host). It is not your permanent backup — keep the original export folders in a safe place.
- If the zip is **very large**, upload may fail or be slow. Your host may also limit upload size; if that happens, ask your team about a self‑hosted app or a smaller export.

### Privacy

Treat zip uploads like the original export: **sensitive** if the pilot data is sensitive. Only use links you trust, and do not share exports more widely than your policy allows. Anyone who can open the app and upload can see the data they put in (same as any web tool you use with files you upload).

---

## If the sidebar has “Data root” and your team uses a server path

Sometimes the app is already pointed at a folder on a server. You may see **Data root** in the sidebar with a path, or the charts may work **without** uploading. In that case, follow the instructions your administrator gave you. The zip steps above are mainly for the **browser-hosted** version where the app has no access to your PC’s folders.

---

## Something looks wrong?

| What you see | What to try |
|----------------|------------|
| No charts / “no pilot folders” | Check that the zip’s layout is: **one** folder, and **inside** it only the `store_Pilot_v…` folders (not a zip of each store separately in a confusing way). Re‑zip the **parent** of `store_Pilot_v0`, `store_Pilot_v1`, … |
| Empty after a while | The session may have reset. Upload the zip again. |
| Upload fails or times out | Try a smaller zip, or ask your team about size limits. |

---

## For administrators and developers (repository)

The following is for people who **maintain this repository**, deploy the app, or run it on a server — not for day‑to day dashboard users.

**Repository contents (high level):** `dashboard_app.py` (Streamlit UI), `analyze_pilot_studies.py` (optional local batch / Excel from data on disk), `requirements.txt` (Python dependencies). Do **not** commit `store_Pilot_v*` export trees; they are large, often sensitive, and belong on the machine or share where analysis runs.

**Run locally (development):**

```powershell
cd tutor-bot-interactions
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run dashboard_app.py
```

Point **Data root** in the UI at the folder that **contains** `store_Pilot_v0`, `store_Pilot_v1`, … (or set `TUTOR_BOT_DATA_ROOT` to that path).

