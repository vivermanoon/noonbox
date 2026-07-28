# GitLab connection (`dp-gitlab.noon.team`)

Connect to noon's **GitLab** (`https://dp-gitlab.noon.team`) using **user login
(OAuth)** — you sign in with your own GitLab account through the browser; no
long-lived tokens to paste around. Works as a CLI or a small web app, mirroring
the BigQuery setup in [`README.md`](README.md).

> The instance is on noon's internal network, so run everything below from a
> machine that can reach `dp-gitlab.noon.team` (e.g. on the VPN / office
> network). Point `GITLAB_URL` at `https://gitlab.com` if you want the SaaS.

## Prerequisites

- Python 3.9+
- A GitLab account on the instance you're connecting to
  (default: `dp-gitlab.noon.team`)
- An **OAuth application** (one-time setup, see below)

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Create an OAuth application (one-time)

User login needs an OAuth application registered on your GitLab account:

1. Go to **GitLab → Settings → Applications → Add new application**
   (`https://dp-gitlab.noon.team/-/user_settings/applications`).
2. **Name**: anything, e.g. `noonbox`.
3. **Redirect URI**: `http://localhost:8080/callback`
   (must match `GITLAB_REDIRECT_URI` exactly).
4. **Confidential**: untick it for a PKCE-only desktop flow (recommended), or
   leave it ticked and also set `GITLAB_CLIENT_SECRET`.
5. **Scopes**: tick **`api`** (full read/write) or **`read_api`** for read-only.
6. Save, then copy the **Application ID** into `GITLAB_CLIENT_ID` (see
   `.env.example`).

```bash
cp .env.example .env
# then set GITLAB_CLIENT_ID=... (and GITLAB_CLIENT_SECRET=... if confidential)
```

> The cached token (`.gitlab_token.json`) is already in `.gitignore` — never commit it.

## 3. Log in (web/browser)

```bash
python gl_login.py
```

This opens the GitLab authorization screen in your browser. After you approve,
the token is cached to `.gitlab_token.json` and auto-refreshes — you won't be
prompted again. The script then prints your account and a few of your projects
to confirm access.

Over SSH without a local browser? Run with `GITLAB_NO_BROWSER=1` and it prints a
URL to open manually. (The browser you open it in must be able to reach this
machine's `localhost:8080`.)

## 4. Use it

**Command line:**

```bash
python gl_api.py /user
python gl_api.py /projects --param membership=true --param per_page=5
python gl_api.py /projects/123/issues --param state=opened
python gl_api.py --method list /groups          # auto-paginate all pages
```

**Web app** (a "Log in with GitLab" page + API box):

```bash
pip install streamlit
streamlit run gl_app.py
```

**In Python:**

```python
from glconnect import get_client, fetch, current_user

gl = get_client()                 # instance defaults to dp-gitlab.noon.team
me = current_user(client=gl)
print(me["username"])

# Any REST endpoint under /api/v4:
issues = fetch("/projects/123/issues", params={"state": "opened"}, client=gl)

# The full python-gitlab client is available too:
project = gl.projects.get("group/project")
for mr in project.mergerequests.list(state="opened", get_all=False):
    print(mr.title)
```

## Configuration

All optional except `GITLAB_CLIENT_ID`. Copy `.env.example` to `.env` to set them:

| Variable                | Default                          | Purpose                                        |
| ----------------------- | -------------------------------- | ---------------------------------------------- |
| `GITLAB_URL`            | `https://dp-gitlab.noon.team`    | Instance to connect to                         |
| `GITLAB_CLIENT_ID`      | *(required)*                     | OAuth application ID                            |
| `GITLAB_CLIENT_SECRET`  | *(unset)*                        | Only for a confidential OAuth app              |
| `GITLAB_TOKEN_PATH`     | `.gitlab_token.json`             | Where the cached token is stored               |
| `GITLAB_REDIRECT_PORT`  | `8080`                           | Local port that captures the OAuth callback    |
| `GITLAB_REDIRECT_URI`   | `http://localhost:8080/callback` | Must match the app's registered redirect URI   |
| `GITLAB_SCOPES`         | `api`                            | OAuth scopes (`api`, `read_api`, `read_user`)  |
| `GITLAB_CA_BUNDLE`      | *(unset)*                        | PEM CA bundle for a private/internal CA        |
| `GITLAB_SSL_VERIFY`     | `true`                           | `true`, `false`, or a CA bundle path           |
| `GITLAB_ACCESS_TOKEN`   | *(unset)*                        | A token supplied out-of-band (skips login)     |
| `GITLAB_TOKEN_TYPE`     | `oauth`                          | `oauth` or `private` for a personal token      |

## Layout

```
glconnect/          package
  config.py         env-driven settings (URL, client id/secret, scopes, paths)
  auth.py           OAuth authorization-code (+PKCE) flow + token caching/refresh
  client.py         builds an authenticated gitlab.Gitlab client
  query.py          fetch() helper over the REST API (+ current_user())
gl_login.py         one-time browser login + connectivity check
gl_api.py           call the REST API from the CLI
gl_app.py           optional Streamlit web UI
```

## Notes

- This repo's remote container has no browser, so run the login **on your own
  machine** (or any host where you can open a browser and reach `localhost`).
- User login means API calls run **as you**, with your GitLab permissions.
- Prefer a read-only footprint? Register the app with the `read_api` scope and
  set `GITLAB_SCOPES=read_api`.
- **Private CA:** `dp-gitlab.noon.team` serves a certificate signed by noon's
  internal CA. If you hit `SSLError: certificate verify failed`, point
  `GITLAB_CA_BUNDLE` at the CA's PEM file — it's applied to both the API client
  and the OAuth token exchange. As a last resort, `GITLAB_SSL_VERIFY=false`
  disables verification (not recommended).
