# BigQuery connection (`noonbimerch`)

Connect to the BigQuery project **`noonbimerch`** using **user login (OAuth)** —
you sign in with your own Google account through the browser; no service-account
key files to manage. Works as a CLI or a small web app.

> Looking for the **GitLab** connection? See [`GITLAB.md`](GITLAB.md) — same
> OAuth-login shape, for `dp-gitlab.noon.team`.

## Prerequisites

- Python 3.9+
- Access to the `noonbimerch` project with your Google account
- An **OAuth client** (one-time setup, see below)

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Create an OAuth client (one-time)

User login needs an OAuth client. In the [GCP Console](https://console.cloud.google.com/apis/credentials):

1. Select the **`noonbimerch`** project.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Download the JSON and save it in this folder as **`client_secret.json`**.
   (Or point `BQ_CLIENT_SECRETS` at it — see `.env.example`.)

Make sure the **BigQuery API** is enabled for the project
(APIs & Services → Enable APIs → "BigQuery API").

> `client_secret.json` and the cached token are already in `.gitignore` — never commit them.

## 3. Log in (web/browser)

```bash
python bq_login.py
```

This opens a Google consent screen in your browser. After you approve, the token
is cached to `.bq_token.json` and auto-refreshes — you won't be prompted again.
The script then lists a few datasets to confirm access.

Over SSH without a local browser? Run with `BQ_NO_BROWSER=1` and it prints a URL
to open manually.

## 4. Use it

**Command line:**

```bash
python bq_query.py "SELECT CURRENT_DATE() AS today"
python bq_query.py --file my_query.sql
python bq_query.py --dry-run "SELECT * FROM \`noonbimerch.dataset.table\`"   # cost estimate only
```

**Web app** (a "Log in with Google" page + query box):

```bash
pip install streamlit
streamlit run app.py
```

**In Python:**

```python
from bqconnect import get_client, run_query

client = get_client()                      # project defaults to noonbimerch
rows = run_query("SELECT 1 AS n", client=client)
for row in rows:
    print(row.n)

# Parameterized:
run_query("SELECT @x AS x", params={"x": 42}, client=client)

# As a DataFrame:
df = run_query("SELECT 1 AS n", client=client).to_dataframe()
```

## Configuration

All optional — defaults work out of the box. Copy `.env.example` to `.env` to override:

| Variable            | Default              | Purpose                                   |
| ------------------- | -------------------- | ----------------------------------------- |
| `BQ_PROJECT`        | `noonbimerch`        | Project to query/bill against             |
| `BQ_CLIENT_SECRETS` | `client_secret.json` | OAuth client-secrets file                 |
| `BQ_TOKEN_PATH`     | `.bq_token.json`     | Where the cached token is stored          |
| `BQ_LOCATION`       | *(unset)*            | Job location (e.g. `US`, `EU`)            |

## Layout

```
bqconnect/          package
  config.py         env-driven settings (project, paths, scopes)
  auth.py           OAuth user-login flow + token caching
  client.py         builds an authenticated bigquery.Client
  query.py          run_query() helper (params, dry-run, DataFrame)
bq_login.py         one-time browser login + connectivity check
bq_query.py         run SQL from the CLI
app.py              optional Streamlit web UI
```

## Notes

- This repo's remote container has no browser and no `gcloud`, so run the login
  **on your own machine** (or any host where you can open a browser).
- User login means queries run and bill **as you**, with your BigQuery permissions.
