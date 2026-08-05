# Tacticus API Dumper

Self-hosted Flask application for pulling JSON from the **Warhammer 40,000: Tacticus** API. The first containerization milestone is behavioral parity with the current app: the web UI saves a Tacticus API key, fetches the Player/Guild/Guild Raid endpoints, stores timestamped JSON dumps, and lets you re-download saved dumps.

## Repository inspection summary

| Area | Finding |
| --- | --- |
| Frontend framework | No separate frontend framework. The UI is server-rendered inline HTML/CSS/JavaScript from Flask's `render_template_string` in `app.py`. |
| Backend framework | Python Flask, served in production by Gunicorn. |
| Package manager | `pip` with `requirements.txt`. |
| Build command | Local/container dependency install: `pip install -r requirements.txt`; container build: `docker build -t tacticus-dumper:local .`. |
| Run command | Development-style local run can use `flask --app app run`; production container uses `gunicorn ... app:app`. |
| Rendering/service model | Server-rendered Flask app plus JSON API routes. It is not a static-only site and requires the Python API service. |
| User data location | `DATA_DIR`, defaulting to `/data`. |
| Storage backend | Files on disk only: `config.json` for saved API key/settings and `dumps/*.json` for exports. No browser local storage, SQLite, or external database is used by the app. |
| Persistent paths | Persist `/data` in the container. The Dockhand/Unraid compose file uses the named volume `tacticus-data` to preserve the app's existing live data location. |
| Required runtime environment variables | None strictly required for startup. `DATA_DIR`, `TZ`, `AUTH_USER`, `AUTH_PASS`, `TACTICUS_KEY`, `GUNICORN_WORKERS`, and `GUNICORN_TIMEOUT` are supported. |
| Expected internal port | `5000`. |
| Existing deployment files before this pass | The repository already had `Dockerfile` and `docker-compose.yml`. It did not have a health endpoint, `.dockerignore`, Dockhand `compose.yaml`, or GitHub Actions publishing workflow. Follow-up review kept the existing named volume instead of switching to appdata bind mounts to avoid hiding live data. |

## Runtime configuration

| Variable | Default | Required? | Purpose |
| --- | --- | --- | --- |
| `APP_PORT` | `5001` | No | Host port used by `compose.yaml`. The container still listens on port `5000`. |
| `TZ` | `America/Chicago` | No | Container timezone. |
| `DATA_DIR` | `/data` | No | Directory where the app stores `config.json` and `dumps/`. The compose file fixes this to `/data`. |
| `AUTH_USER` | empty | No | Enables basic auth when set. Leave empty when using a trusted reverse proxy or Cloudflare Access. |
| `AUTH_PASS` | empty | No | Password for basic auth. |
| `TACTICUS_KEY` | empty | No | Optional API key seed. If provided and no saved key exists, the app writes it to `config.json`. |
| `GUNICORN_WORKERS` | `2` | No | Gunicorn worker count. |
| `GUNICORN_TIMEOUT` | `60` | No | Gunicorn request timeout in seconds. |

## Persistent storage

The app persists all user data under the container path `/data`:

```text
/data/config.json      # saved API key and settings
/data/dumps/*.json     # timestamped endpoint exports
```

For Unraid/Dockhand, `compose.yaml` intentionally maps that path to the Compose named volume `tacticus-data`:

```yaml
volumes:
  - tacticus-data:/data
```

This preserves behavioral parity with the existing deployment, whose live data is already in the stack's named Docker volume. Do not switch to an appdata bind mount unless you first migrate the existing `config.json` and `dumps/` into the new host directory and ensure the container can write to it.

## Build and run locally

```bash
cp .env.example .env
# Edit .env if desired.
docker compose -f compose.yaml build
docker compose -f compose.yaml up -d --wait --wait-timeout 60
curl -fsS http://127.0.0.1:${APP_PORT:-5001}/healthz
docker compose -f compose.yaml logs -f tacticus-dumper
```

Open <http://127.0.0.1:5001> by default.

To stop the app:

```bash
docker compose -f compose.yaml down
```

## Deploy on Unraid through Dockhand

1. In Dockhand, use this repository's `compose.yaml`.
2. Keep the `tacticus-data:/data` named volume mapping unless you have intentionally migrated data elsewhere.
3. Set or review environment variables:
   - `APP_PORT=5001` or another available host port
   - `TZ=America/Chicago`
   - Optional `AUTH_USER` and `AUTH_PASS`
   - Optional `TACTICUS_KEY`
4. Deploy the stack.
5. Confirm the health check passes and open `http://<unraid-host>:5001`.

## GitHub Container Registry publishing

The workflow in `.github/workflows/ghcr.yml` builds and publishes the image to GHCR on:

- pushes to `master` or `main`
- version tags matching `v*`, such as `v1.0.0`

Published image name:

```text
ghcr.io/jshauns81/tacticus-dumper
```

The workflow writes `latest` for the default branch, tag names for version tags, and SHA tags for traceability.

## Health check

The container exposes an unauthenticated health endpoint:

```bash
curl -fsS http://127.0.0.1:5001/healthz
```

The Dockerfile and `compose.yaml` both use `/healthz` for health checks.

## Getting your Tacticus API key

1. Go to <https://api.tacticusgame.com/>.
2. Generate a Player API key with scopes: **Player**, **Guild**, **Guild Raid**.
3. Either paste it in the web UI after launch, or set `TACTICUS_KEY` before first start.

## What it does

- Fetches Tacticus **Player**, **Guild**, and **Guild Raid** JSON.
- Downloads JSON directly to your device.
- Copies JSON to clipboard from the browser UI.
- Auto-saves each fetch as a timestamped file in `/data/dumps` when enabled.
- Lists and re-downloads previous dumps from the UI.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Immediate health request is reset or refused | Start with `docker compose -f compose.yaml up -d --wait --wait-timeout 60`; the published port can exist briefly before Gunicorn is ready. |
| Container is unhealthy | Check `docker compose -f compose.yaml logs tacticus-dumper`; the health check calls `/healthz` on internal port `5000`. |
| Permission errors under `/data` | The container starts as root only long enough to prepare `/data`, then drops to UID/GID `10001` before launching Gunicorn. Check logs if the volume cannot be repaired. |
| Browser prompts for login | `AUTH_USER` is set. Use the configured credentials or unset `AUTH_USER`/`AUTH_PASS` if another access layer handles authentication. |
| No API key saved | Paste a key in the UI or set `TACTICUS_KEY` before first container startup. |
| 401 from Tacticus API | Re-generate your key and confirm it has the required scopes. |
