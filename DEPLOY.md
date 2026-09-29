# Deploying the demo to Streamlit Community Cloud

The demo is a single Streamlit script with no secrets, no API keys and no network calls. Community Cloud builds from a public GitHub repo.

1. Push this repo to GitHub as a public repo (for example `github.com/HarshShroff/plainmem`).
2. Go to https://share.streamlit.io and sign in with GitHub. Authorize access to the repo when asked.
3. Click **Create app**, then choose to deploy a public app from GitHub (button labels change now and then; the fields below are what matter).
4. Fill in:
   - Repository: `HarshShroff/plainmem`
   - Branch: `main`
   - Main file path: `demo/app.py`
   - App URL: pick a subdomain, e.g. `plainmem`
5. Open **Advanced settings** and choose Python 3.12. Leave secrets empty.
6. Click **Deploy**. The build installs `requirements.txt` from the repo root (only `streamlit`); the app imports the package from `src/` directly, so nothing else is needed. The first build takes a few minutes.
7. Open the app, type a query, add a note, and check that the badges and the benchmark table show up.
8. Copy the app URL into the README line that says `Live demo: TODO add URL after deploy`, commit and push.

## Checking it locally first

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e ".[dev]"
pytest -q
streamlit run demo/app.py
```

## Notes

- Visitor notes live in Streamlit session state only. They disappear when the tab closes and are never written to disk.
- The benchmark table in the app is read from `bench/results.md`. Re-run `python bench/run.py` and commit the result if you change the ranker.
- Community Cloud apps sleep after a period without traffic and wake on the next visit.
