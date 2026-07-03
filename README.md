# Tacticus API Dumper (Docker + Cloudflare Tunnel)

Self-hosted Docker app for pulling JSON from the **Warhammer 40,000: Tacticus**
API. Runs on your server, accessible from anywhere via Cloudflare Tunnel —
phone, laptop, whatever.

## Setup

### 1. Create a Cloudflare Tunnel

In the Cloudflare dashboard:

1. Go to **Zero Trust → Networks → Tunnels**
2. Click **Create a tunnel** → choose **Cloudflared**
3. Name it (e.g. `tacticus-dumper`)
4. Copy the **tunnel token**
5. Under **Public Hostnames**, add a route:
   - **Subdomain**: whatever you want (e.g. `tacticus`)
   - **Domain**: your domain
   - **Service**: `http://tacticus-dumper:5000`

> The service URL points at the Docker container name, not localhost — both
> containers share a Docker network so this just works.

### 2. Configure & Launch

```bash
cd tacticus-dumper
cp .env.example .env
```

Edit `.env` and paste your tunnel token:

```
TUNNEL_TOKEN=eyJh...your-token-here
```

Then launch:

```bash
docker compose up -d
```

That's it. Hit `https://tacticus.yourdomain.com` (or whatever you configured)
from any device.

### 3. (Optional) Lock it down with Cloudflare Access

If you want zero-trust auth instead of basic auth:

1. In **Zero Trust → Access → Applications**, add a self-hosted app
2. Set the domain to match your tunnel hostname
3. Add a policy (e.g. email allowlist, one-time PIN, etc.)
4. Leave `AUTH_USER` and `AUTH_PASS` blank in `.env` — Cloudflare handles login

If you'd rather use basic auth instead (or in addition), set `AUTH_USER` and
`AUTH_PASS` in `.env`.

## Getting your Tacticus API key

1. Go to <https://api.tacticusgame.com/>
2. Generate a Player API key with scopes: **Player**, **Guild**, **Guild Raid**
3. Either paste it in the web UI after launch, or set `TACTICUS_KEY` in `.env`

## What it does

- Tap **Player**, **Guild**, or **Guild Raid** to fetch that endpoint's JSON
- **Download** the JSON straight to your phone/device
- **Copy** to clipboard
- **Auto-saves** every fetch as a timestamped file on the server (`dumps/` folder)
- Browse and re-download past dumps from the UI

## Data persistence

Everything lives in a Docker volume (`tacticus-data`):

- `config.json` — your saved API key + settings
- `dumps/` — timestamped JSON exports

Survives container rebuilds. To back up:

```bash
docker cp tacticus-dumper:/data ./backup
```

## File overview

```
├── app.py              # Flask app (UI + API proxy)
├── Dockerfile          # Python 3.12 slim + gunicorn
├── docker-compose.yml  # App + cloudflared sidecar
├── .env.example        # Template for your .env
├── .dockerignore
└── requirements.txt
```

## Adding new endpoints

If Snowprint adds API endpoints, edit the `ENDPOINTS` dict in `app.py`:

```python
ENDPOINTS = {
    "player":    {"path": "/player",    "label": "Player",     "icon": "⚔",  "desc": "..."},
    "guild":     {"path": "/guild",     "label": "Guild",      "icon": "🛡",  "desc": "..."},
    "guildRaid": {"path": "/guildRaid", "label": "Guild Raid", "icon": "💀",  "desc": "..."},
    # add new ones here
}
```

Then rebuild: `docker compose up -d --build`

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Tunnel won't connect | Check `TUNNEL_TOKEN` in `.env`, make sure it matches the dashboard |
| 502 from Cloudflare | The app container might not be up yet — check `docker compose logs tacticus-dumper` |
| 401 from Tacticus API | Re-generate your key at api.tacticusgame.com — scopes may be wrong |
| Can't reach the site | Verify the public hostname in the Cloudflare tunnel config points to `http://tacticus-dumper:5000` |
| Downloads don't work on mobile | Make sure you're on HTTPS (Cloudflare handles this) — some browsers block downloads over HTTP |
