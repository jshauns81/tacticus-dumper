"""
Tacticus API Dumper — Dockerised, mobile-friendly, self-hosted.

Environment variables:
    AUTH_USER / AUTH_PASS — basic-auth credentials (required in production)
    TACTICUS_KEY         — optionally pre-seed the API key instead of using the UI
    HOST / PORT          — bind address (defaults: 0.0.0.0 / 5000)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import requests as http_requests
from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)

from advisor.actions import ActionModelError, generate_candidate_actions
from advisor.history import compare_player_snapshots
from advisor.knowledge import KnowledgeError, validate_knowledge_repository
from advisor.parser import (
    PlayerDumpSelectionError,
    load_latest_player_dump,
    load_player_dump,
    normalize_player,
    summarize_roster,
)
from advisor.scoring import ActionScoringError, score_guild_raid_actions

# ── paths ────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"
DUMPS_DIR = DATA_DIR / "dumps"
DUMPS_DIR.mkdir(exist_ok=True)
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

TACTICUS_BASE = "https://api.tacticusgame.com/api/v1"

ENDPOINTS = {
    "player":    {"path": "/player",    "label": "Player",     "icon": "⚔",  "desc": "Full roster, inventory, campaigns"},
    "guild":     {"path": "/guild",     "label": "Guild",      "icon": "🛡",  "desc": "Guild info & member list · Officer+"},
    "guildRaid": {"path": "/guildRaid", "label": "Guild Raid", "icon": "💀",  "desc": "Current raid season data · Officer+"},
}

OPTIONAL_ENDPOINT_SETTINGS = {
    "guild": "show_guild",
    "guildRaid": "show_guild_raid",
}

BOOLEAN_SETTINGS = {
    "auto_save": True,
    "show_guild": True,
    "show_guild_raid": True,
}

app = Flask(__name__)

# ── basic auth ───────────────────────────────────────────────────────────
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")


def check_auth(u, p):
    return u == AUTH_USER and p == AUTH_PASS


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_USER:          # auth disabled → pass through
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Login required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Tacticus Dumper"'},
            )
        return f(*args, **kwargs)
    return decorated


# ── config helpers ───────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def get_api_key() -> str | None:
    return load_config().get("api_key") or os.environ.get("TACTICUS_KEY")


# ── pre-seed key from env if provided ────────────────────────────────────
_env_key = os.environ.get("TACTICUS_KEY", "").strip()
if _env_key:
    cfg = load_config()
    if not cfg.get("api_key"):
        cfg["api_key"] = _env_key
        save_config(cfg)


# ── routes ───────────────────────────────────────────────────────────────


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/")
@requires_auth
def index():
    cfg = load_config()
    has_key = bool(cfg.get("api_key"))
    masked = ""
    if has_key:
        k = cfg["api_key"]
        masked = (k[:6] + "…" + k[-4:]) if len(k) > 12 else "••••"
    endpoints = {
        key: endpoint
        for key, endpoint in ENDPOINTS.items()
        if key not in OPTIONAL_ENDPOINT_SETTINGS
        or cfg.get(OPTIONAL_ENDPOINT_SETTINGS[key], True)
    }
    return render_template_string(
        INDEX_HTML,
        has_key=has_key,
        masked=masked,
        endpoints=endpoints,
        auto_save=cfg.get("auto_save", BOOLEAN_SETTINGS["auto_save"]),
        show_guild=cfg.get("show_guild", BOOLEAN_SETTINGS["show_guild"]),
        show_guild_raid=cfg.get(
            "show_guild_raid", BOOLEAN_SETTINGS["show_guild_raid"]
        ),
    )


@app.route("/api/key", methods=["POST"])
@requires_auth
def set_key():
    data = request.get_json(silent=True) or {}
    key = (data.get("api_key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "Key is empty."}), 400
    cfg = load_config()
    cfg["api_key"] = key
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/key", methods=["DELETE"])
@requires_auth
def clear_key():
    cfg = load_config()
    cfg.pop("api_key", None)
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["POST"])
@requires_auth
def update_settings():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    for key in BOOLEAN_SETTINGS:
        if key not in data:
            continue
        if not isinstance(data[key], bool):
            return jsonify({"ok": False, "error": f"{key} must be a boolean."}), 400
        cfg[key] = data[key]
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/fetch/<endpoint>")
@requires_auth
def fetch_endpoint(endpoint: str):
    if endpoint not in ENDPOINTS:
        return jsonify({"ok": False, "error": f"Unknown endpoint: {endpoint}"}), 400

    key = get_api_key()
    if not key:
        return jsonify({"ok": False, "error": "No API key saved yet."}), 400

    url = TACTICUS_BASE + ENDPOINTS[endpoint]["path"]
    try:
        r = http_requests.get(
            url, headers={"X-API-KEY": key, "Accept": "application/json"}, timeout=30
        )
    except http_requests.RequestException as e:
        return jsonify({"ok": False, "error": f"Request failed: {e}"}), 502

    if r.status_code != 200:
        return jsonify({
            "ok": False,
            "status": r.status_code,
            "error": f"Tacticus API returned {r.status_code}",
            "body": r.text[:2000],
        }), 502

    try:
        payload = r.json()
    except ValueError:
        return jsonify({"ok": False, "error": "Response was not valid JSON."}), 502

    saved_name = None
    cfg = load_config()
    if cfg.get("auto_save", True):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"{endpoint}_{ts}.json"
        (DUMPS_DIR / fname).write_text(json.dumps(payload, indent=2))
        saved_name = fname

    return jsonify({"ok": True, "endpoint": endpoint, "data": payload, "saved": saved_name})


@app.route("/api/download/<endpoint>")
@requires_auth
def download_endpoint(endpoint: str):
    if endpoint not in ENDPOINTS:
        return jsonify({"ok": False, "error": "Unknown endpoint."}), 400
    key = get_api_key()
    if not key:
        return jsonify({"ok": False, "error": "No API key saved."}), 400

    url = TACTICUS_BASE + ENDPOINTS[endpoint]["path"]
    try:
        r = http_requests.get(
            url, headers={"X-API-KEY": key, "Accept": "application/json"}, timeout=30
        )
        r.raise_for_status()
    except http_requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"{endpoint}_{ts}.json"
    pretty = json.dumps(r.json(), indent=2)

    return Response(
        pretty,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.route("/api/dumps")
@requires_auth
def list_dumps():
    files = []
    for p in sorted(DUMPS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        modified = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        files.append({
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": modified.strftime("%Y-%m-%d %H:%M UTC"),
            "mtime_iso": modified.isoformat().replace("+00:00", "Z"),
        })
    return jsonify({"ok": True, "files": files[:100]})


@app.route("/api/dumps/<filename>")
@requires_auth
def download_dump(filename: str):
    if "/" in filename or ".." in filename:
        return jsonify({"ok": False, "error": "Bad filename."}), 400
    return send_from_directory(DUMPS_DIR, filename, as_attachment=True)


def _load_requested_advisor_dump():
    selected_dump = request.args.get("dump", "")
    if selected_dump:
        return load_player_dump(DUMPS_DIR, selected_dump)
    return load_latest_player_dump(DUMPS_DIR)


def _load_advisor_history_pair():
    before_name = request.args.get("before", "")
    after_name = request.args.get("after", "")
    if bool(before_name) != bool(after_name):
        raise PlayerDumpSelectionError(
            "History selection requires both before and after dump filenames."
        )
    if before_name and before_name == after_name:
        raise PlayerDumpSelectionError(
            "History selection requires two different player dumps."
        )
    if before_name:
        return (
            load_player_dump(DUMPS_DIR, before_name),
            load_player_dump(DUMPS_DIR, after_name),
        )

    candidates = sorted(
        DUMPS_DIR.glob("player_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if len(candidates) < 2:
        raise FileNotFoundError(
            "At least two player_*.json dumps are required for history."
        )
    return (
        load_player_dump(DUMPS_DIR, candidates[1].name),
        load_player_dump(DUMPS_DIR, candidates[0].name),
    )


@app.route("/api/advisor/summary")
@requires_auth
def advisor_summary():
    try:
        source_path, payload = _load_requested_advisor_dump()
    except PlayerDumpSelectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422

    try:
        normalized = normalize_player(payload, source_path=source_path)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"Invalid player structure: {exc}"}), 422

    return jsonify(summarize_roster(normalized))


@app.route("/api/advisor/actions")
@requires_auth
def advisor_actions():
    try:
        source_path, payload = _load_requested_advisor_dump()
    except PlayerDumpSelectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422

    try:
        normalized = normalize_player(payload, source_path=source_path)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"Invalid player structure: {exc}"}), 422

    try:
        knowledge = validate_knowledge_repository(KNOWLEDGE_DIR)
        result = generate_candidate_actions(
            normalized,
            knowledge["progression_models"],
            knowledge["characters"],
        )
    except (ActionModelError, KnowledgeError) as exc:
        app.logger.exception("Advisor action knowledge could not be loaded")
        return jsonify({"ok": False, "error": f"Advisor knowledge error: {exc}"}), 500

    return jsonify(result)


@app.route("/api/advisor/recommendations")
@requires_auth
def advisor_recommendations():
    try:
        source_path, payload = _load_requested_advisor_dump()
    except PlayerDumpSelectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422

    try:
        normalized = normalize_player(payload, source_path=source_path)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"Invalid player structure: {exc}"}), 422

    try:
        knowledge = validate_knowledge_repository(KNOWLEDGE_DIR)
        candidates = generate_candidate_actions(
            normalized,
            knowledge["progression_models"],
            knowledge["characters"],
        )
        result = score_guild_raid_actions(normalized, candidates, knowledge)
    except (ActionModelError, ActionScoringError, KnowledgeError) as exc:
        app.logger.exception("Advisor recommendation knowledge could not be loaded")
        return jsonify({"ok": False, "error": f"Advisor knowledge error: {exc}"}), 500

    return jsonify(result)


@app.route("/api/advisor/history")
@requires_auth
def advisor_history():
    try:
        (before_path, before_payload), (after_path, after_payload) = (
            _load_advisor_history_pair()
        )
    except PlayerDumpSelectionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422

    try:
        before = normalize_player(before_payload, source_path=before_path)
        after = normalize_player(after_payload, source_path=after_path)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": f"Invalid player structure: {exc}"}), 422

    try:
        knowledge = validate_knowledge_repository(KNOWLEDGE_DIR)
        result = compare_player_snapshots(
            before, after, knowledge["progression_models"]
        )
    except KnowledgeError as exc:
        app.logger.exception("Advisor history knowledge could not be loaded")
        return jsonify({"ok": False, "error": f"Advisor knowledge error: {exc}"}), 500

    return jsonify(result)


# ── inline HTML ──────────────────────────────────────────────────────────
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tacticus Dumper</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b0d10">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:      #0b0d10;
    --surface: #12161c;
    --card:    #171c24;
    --border:  #252d38;
    --text:    #d8dce0;
    --muted:   #6b7a8a;
    --gold:    #c8a84e;
    --gold-d:  #a07e28;
    --red:     #c94444;
    --green:   #4a9e4a;
    --blue:    #4a8cc9;
    --font:    'Chakra Petch', sans-serif;
    --mono:    'JetBrains Mono', ui-monospace, monospace;
    --radius:  10px;
    --safe-b:  env(safe-area-inset-bottom, 0px);
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; }
  html { background: var(--bg); }
  body {
    background: var(--bg); color: var(--text);
    font-family: var(--font); font-size: 15px; line-height: 1.5;
    min-height: 100dvh; padding-bottom: var(--safe-b);
    -webkit-font-smoothing: antialiased;
  }

  /* ── header ── */
  .hdr {
    position: sticky; top: 0; z-index: 50;
    background: linear-gradient(180deg, #12161c 60%, #12161c00);
    padding: 16px 20px 24px; backdrop-filter: blur(12px);
  }
  .hdr h1 {
    font-size: 22px; font-weight: 700; letter-spacing: 1.5px;
    text-transform: uppercase; color: var(--gold);
    display: flex; align-items: center; gap: 8px;
  }
  .hdr .sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .hdr .sub a { color: var(--gold); text-decoration: none; }

  /* ── layout ── */
  .wrap { max-width: 640px; margin: 0 auto; padding: 0 16px 32px; }

  /* ── cards ── */
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 16px; margin-bottom: 14px;
  }
  .card-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 1.2px; color: var(--muted); margin-bottom: 12px;
  }

  /* ── inputs ── */
  input[type="text"], input[type="password"] {
    width: 100%; background: var(--surface); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 14px; font-family: var(--mono); font-size: 14px;
  }
  input:focus { outline: none; border-color: var(--gold); }
  ::placeholder { color: var(--muted); }

  /* ── buttons ── */
  .btn-row { display: flex; gap: 8px; margin-top: 10px; }
  .btn-row > * { flex: 1; }
  button, .btn {
    display: inline-flex; align-items: center; justify-content: center;
    gap: 6px; font-family: var(--font); font-size: 14px; font-weight: 600;
    border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; cursor: pointer;
    background: var(--surface); color: var(--text);
    transition: border-color .15s, color .15s, background .15s;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    min-height: 48px;            /* mobile tap target */
  }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: .45; pointer-events: none; }
  .btn-gold { background: var(--gold); color: #0b0d10; border-color: var(--gold); }
  .btn-gold:active { background: var(--gold-d); }
  .btn-danger:active { border-color: var(--red); color: var(--red); }
  .btn-ghost { background: transparent; }

  /* ── endpoint grid ── */
  .ep-grid { display: grid; gap: 10px; }
  .ep-options {
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px 16px;
    margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
  }
  .ep-options .label {
    color: var(--muted); font-size: 11px; font-weight: 600;
    letter-spacing: 1px; text-transform: uppercase;
  }
  .ep-card {
    display: flex; align-items: center; gap: 14px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 16px;
    cursor: pointer; transition: border-color .15s;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation; min-height: 64px;
  }
  .ep-card:active { border-color: var(--gold); background: #1a2030; }
  .ep-card .icon { font-size: 28px; flex-shrink: 0; width: 40px; text-align: center; }
  .ep-card .info { flex: 1; min-width: 0; }
  .ep-card .info .name { font-weight: 700; font-size: 16px; }
  .ep-card .info .desc { font-size: 12px; color: var(--muted); }
  .ep-card .arrow { color: var(--muted); font-size: 18px; flex-shrink: 0; }
  .ep-card.loading { opacity: .6; pointer-events: none; }
  .ep-card.loading .arrow::after { content: '⏳'; }

  /* ── advisor ── */
  .advisor-head {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 12px; margin-bottom: 14px;
  }
  .advisor-head .card-title { margin-bottom: 3px; }
  .advisor-sub { color: var(--muted); font-size: 12px; }
  .advisor-controls { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }
  .advisor-controls select {
    max-width: 180px; min-height: 38px; background: var(--surface); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px; padding: 7px 28px 7px 10px;
    font-family: var(--font); font-size: 12px;
  }
  .advisor-controls select:focus { outline: none; border-color: var(--gold); }
  .advisor-refresh {
    min-height: 38px; padding: 7px 12px; font-size: 12px; flex-shrink: 0;
  }
  .advisor-loading, .advisor-empty {
    display: flex; gap: 12px; align-items: flex-start;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px;
  }
  .advisor-empty .state-icon {
    display: grid; place-items: center; width: 32px; height: 32px;
    border-radius: 50%; background: rgba(74,158,74,.15); color: var(--green);
    font-weight: 700; flex-shrink: 0;
  }
  .advisor-empty.error .state-icon {
    background: rgba(201,68,68,.15); color: var(--red);
  }
  .advisor-empty h3 { font-size: 15px; margin-bottom: 3px; }
  .advisor-empty p { color: var(--muted); font-size: 13px; }
  .advisor-known { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .advisor-chip {
    border: 1px solid var(--border); border-radius: 999px; padding: 4px 8px;
    color: var(--muted); font-size: 11px;
  }
  .advisor-projects { display: grid; gap: 10px; }
  .advisor-project {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px;
  }
  .advisor-project-top {
    display: flex; justify-content: space-between; align-items: center;
    gap: 8px; margin-bottom: 8px;
  }
  .advisor-rank {
    color: var(--gold); font-family: var(--mono); font-size: 11px;
    text-transform: uppercase; letter-spacing: .8px;
  }
  .advisor-score {
    border: 1px solid var(--gold-d); color: var(--gold); border-radius: 999px;
    padding: 3px 8px; font-family: var(--mono); font-size: 11px;
  }
  .advisor-project h3 { font-size: 17px; margin-bottom: 4px; }
  .advisor-project .why { color: var(--muted); font-size: 13px; }
  .advisor-stop {
    margin-top: 10px; padding: 8px 10px; border-left: 2px solid var(--gold);
    background: rgba(200,168,78,.07); color: var(--text); font-size: 12px;
  }
  .advisor-project details { margin-top: 10px; border-top: 1px solid var(--border); }
  .advisor-project summary {
    color: var(--gold); cursor: pointer; padding-top: 10px;
    font-size: 12px; font-weight: 600;
  }
  .advisor-breakdown { display: grid; gap: 6px; margin-top: 9px; }
  .advisor-component {
    display: grid; grid-template-columns: 34px 1fr; gap: 8px;
    color: var(--muted); font-size: 12px;
  }
  .advisor-component .points { color: var(--green); font-family: var(--mono); }
  .advisor-notes { margin-top: 10px; color: var(--muted); font-size: 11px; }
  .advisor-notes strong { color: var(--text); }
  .advisor-policy {
    color: var(--muted); font-family: var(--mono); font-size: 10px;
    margin-top: 10px; text-align: right;
  }
  @media (max-width: 520px) {
    .advisor-head { flex-direction: column; }
    .advisor-controls { width: 100%; }
    .advisor-controls select { flex: 1; max-width: none; min-width: 0; }
  }

  /* ── key status ── */
  .key-badge {
    display: inline-flex; align-items: center; gap: 6px;
    font-family: var(--mono); font-size: 13px; padding: 4px 0;
  }
  .key-badge .dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }
  .key-badge .dot.on  { background: var(--green); }
  .key-badge .dot.off { background: var(--red); }

  /* ── output area ── */
  #output-wrap { display: none; }
  #output-wrap.visible { display: block; }
  .output-bar {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 8px; margin-bottom: 8px;
  }
  .output-bar .label { font-size: 13px; color: var(--muted); }
  .output-bar .actions { display: flex; gap: 6px; }
  .output-bar button { min-height: 40px; padding: 8px 14px; font-size: 13px; }
  pre#output {
    background: #080a0d; color: #c4cad0;
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 14px; font-family: var(--mono); font-size: 12px;
    line-height: 1.6; max-height: 55vh; overflow: auto;
    white-space: pre; -webkit-overflow-scrolling: touch;
  }

  /* ── dumps list ── */
  .dump-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 0; border-bottom: 1px solid var(--border);
    font-family: var(--mono); font-size: 12px; gap: 10px;
  }
  .dump-item:last-child { border-bottom: none; }
  .dump-item .fname { color: var(--text); word-break: break-all; flex: 1; }
  .dump-item .meta  { color: var(--muted); white-space: nowrap; }
  .dump-item a {
    color: var(--gold); text-decoration: none; font-family: var(--font);
    font-size: 13px; padding: 6px 10px; border: 1px solid var(--border);
    border-radius: 6px; flex-shrink: 0;
  }

  /* ── toggle ── */
  .toggle {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: var(--muted); cursor: pointer;
    user-select: none; padding: 4px 0;
  }
  .toggle input { accent-color: var(--gold); width: 18px; height: 18px; }

  /* ── toast ── */
  .toast {
    position: fixed; bottom: calc(20px + var(--safe-b)); left: 50%;
    transform: translateX(-50%) translateY(16px);
    background: var(--card); border: 1px solid var(--border);
    color: var(--text); padding: 10px 20px; border-radius: 10px;
    font-size: 13px; font-weight: 600;
    box-shadow: 0 8px 30px rgba(0,0,0,.6);
    opacity: 0; transition: all .25s; pointer-events: none; z-index: 100;
    text-align: center; max-width: 90vw;
  }
  .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .toast.err { border-color: var(--red); }
  .toast.ok  { border-color: var(--green); }

  /* ── spinner for buttons ── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 16px; height: 16px; border: 2px solid var(--muted);
    border-top-color: var(--gold); border-radius: 50%;
    animation: spin .6s linear infinite; flex-shrink: 0;
  }
</style>
</head>
<body>

<div class="hdr">
  <h1>⚔ Tacticus Dumper</h1>
  <div class="sub">
    Self-hosted API data export &middot;
    <a href="https://api.tacticusgame.com/" target="_blank">Get API Key</a>
  </div>
</div>

<div class="wrap">

  <!-- KEY CARD -->
  <div class="card">
    <div class="card-title">API Key</div>
    <input id="key-input" type="password" placeholder="Paste your Tacticus API key…"
           autocomplete="off" autocapitalize="off" spellcheck="false">
    <div class="btn-row">
      <button class="btn-gold" id="btn-save">Save Key</button>
      <button class="btn-danger" id="btn-clear">Clear</button>
      <button class="btn-ghost" id="btn-eye" style="flex:0; min-width:48px;">👁</button>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-top:10px;">
      <div class="key-badge" id="key-status">
        {% if has_key %}
          <span class="dot on"></span> {{ masked }}
        {% else %}
          <span class="dot off"></span> No key saved
        {% endif %}
      </div>
      <label class="toggle">
        <input type="checkbox" id="auto-save" {% if auto_save %}checked{% endif %}>
        Auto-save dumps
      </label>
    </div>
  </div>

  <!-- ENDPOINTS CARD -->
  <div class="card">
    <div class="card-title">Fetch &amp; Download</div>
    <div class="ep-options">
      <span class="label">Optional endpoints</span>
      <label class="toggle">
        <input type="checkbox" id="show-guild" {% if show_guild %}checked{% endif %}>
        Guild
      </label>
      <label class="toggle">
        <input type="checkbox" id="show-guild-raid" {% if show_guild_raid %}checked{% endif %}>
        Guild Raid
      </label>
    </div>
    <div class="ep-grid">
      {% for key, ep in endpoints.items() %}
      <div class="ep-card" data-endpoint="{{ key }}" role="button" tabindex="0">
        <div class="icon">{{ ep.icon }}</div>
        <div class="info">
          <div class="name">{{ ep.label }}</div>
          <div class="desc">{{ ep.desc }}</div>
        </div>
        <div class="arrow">›</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- ADVISOR CARD -->
  <div class="card" id="advisor-card">
    <div class="advisor-head">
      <div>
        <div class="card-title">Guild Raid Advisor</div>
        <div class="advisor-sub" id="advisor-freshness">
          Uses saved Player data — no officer access required
        </div>
      </div>
      <div class="advisor-controls">
        <select id="advisor-dump" aria-label="Player dump for Advisor">
          <option value="">Latest player dump</option>
        </select>
        <button class="btn-ghost advisor-refresh" id="btn-advisor-refresh">Refresh</button>
      </div>
    </div>
    <div id="advisor-content" aria-live="polite">
      <div class="advisor-loading"><span class="spinner"></span>Checking your latest roster…</div>
    </div>
  </div>

  <!-- OUTPUT CARD -->
  <div class="card" id="output-wrap">
    <div class="output-bar">
      <div class="label" id="output-meta"></div>
      <div class="actions">
        <button id="btn-copy">Copy</button>
        <button id="btn-dl" class="btn-gold">Download</button>
      </div>
    </div>
    <pre id="output"></pre>
  </div>

  <!-- DUMPS CARD -->
  <div class="card">
    <div class="card-title">Saved Dumps</div>
    <div id="dumps-list" style="color:var(--muted); font-size:13px;"><em>Loading…</em></div>
  </div>

</div>

<div class="toast" id="toast"></div>

<script>
const $ = id => document.getElementById(id);
let lastFetch = null;

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;'
})[char]);

function toast(msg, kind='ok') {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast show ' + kind;
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2200);
}

async function api(url, opts={}) {
  const res = await fetch(url, { headers:{'Content-Type':'application/json'}, ...opts });
  const body = await res.json().catch(() => ({ok:false, error:'Bad response'}));
  if (!res.ok || body.ok === false) throw new Error(body.error || 'HTTP '+res.status);
  return body;
}

// ── Key management ──
$('btn-save').onclick = async () => {
  const k = $('key-input').value.trim();
  if (!k) { toast('Paste a key first.','err'); return; }
  try {
    await api('/api/key', { method:'POST', body: JSON.stringify({api_key:k}) });
    toast('Key saved.');
    $('key-input').value = '';
    setTimeout(() => location.reload(), 350);
  } catch(e) { toast(e.message,'err'); }
};

$('btn-clear').onclick = async () => {
  if (!confirm('Clear the saved API key?')) return;
  try {
    await api('/api/key', { method:'DELETE' });
    toast('Key cleared.');
    setTimeout(() => location.reload(), 350);
  } catch(e) { toast(e.message,'err'); }
};

$('btn-eye').onclick = () => {
  const el = $('key-input');
  el.type = el.type === 'password' ? 'text' : 'password';
};

$('auto-save').onchange = async e => {
  try {
    await api('/api/settings', { method:'POST', body: JSON.stringify({auto_save: e.target.checked}) });
    toast('Setting updated.');
  } catch(e) { toast(e.message,'err'); }
};

async function updateEndpointVisibility(setting, checked) {
  try {
    await api('/api/settings', {
      method:'POST',
      body: JSON.stringify({[setting]: checked})
    });
    location.reload();
  } catch(e) {
    toast(e.message,'err');
  }
}

$('show-guild').onchange = e => updateEndpointVisibility('show_guild', e.target.checked);
$('show-guild-raid').onchange = e => updateEndpointVisibility('show_guild_raid', e.target.checked);

// ── Advisor ──
function advisorActionLabel(action) {
  if (action.type === 'ability_level') {
    return `Raise ${action.ability.id} to level ${action.ability.target_level}`;
  }
  if (action.type === 'rank') return `Rank up to ${action.rank.target_label}`;
  if (action.type === 'unlock') return `Unlock ${action.character.name}`;
  return `${action.type === 'ascension' ? 'Ascend' : 'Promote'} to ${action.progression.target_label}`;
}

function renderAdvisor(data) {
  const content = $('advisor-content');
  const imported = data.source?.imported_at ? new Date(data.source.imported_at) : null;
  $('advisor-freshness').textContent = imported && !Number.isNaN(imported.valueOf())
    ? `Player dump from ${imported.toLocaleString()} · no officer access required`
    : 'Uses saved Player data — no officer access required';

  if (!data.projects?.length) {
    const known = (data.coverage?.known_owned_characters || []).map(character =>
      `<span class="advisor-chip">${escapeHtml(character.name)} · no ready action</span>`
    ).join('');
    content.innerHTML = `<div class="advisor-empty">
      <span class="state-icon">✓</span>
      <div>
        <h3>No ready project right now</h3>
        <p>${escapeHtml(data.message)}</p>
        ${known ? `<div class="advisor-known">${known}</div>` : ''}
      </div>
    </div>`;
  } else {
    content.innerHTML = `<div class="advisor-projects">${data.projects.map(project => {
      const action = project.action;
      const components = (project.components || []).map(component =>
        `<div class="advisor-component"><span class="points">+${component.points}</span><span>${escapeHtml(component.reason)}</span></div>`
      ).join('');
      const assumptions = (project.assumptions || []).map(note => `<li>${escapeHtml(note)}</li>`).join('');
      const costs = (project.opportunity_costs || []).map(note => `<li>${escapeHtml(note)}</li>`).join('');
      return `<article class="advisor-project">
        <div class="advisor-project-top">
          <span class="advisor-rank">Project ${project.rank} · ${escapeHtml(action.character.name)}</span>
          <span class="advisor-score">Score ${project.score}</span>
        </div>
        <h3>${escapeHtml(advisorActionLabel(action))}</h3>
        <p class="why">${escapeHtml(project.why)}</p>
        <div class="advisor-stop"><strong>Stop:</strong> ${escapeHtml(project.stopping_point)}</div>
        <details>
          <summary>Why this project</summary>
          <div class="advisor-breakdown">${components}</div>
          ${assumptions ? `<div class="advisor-notes"><strong>Assumptions</strong><ul>${assumptions}</ul></div>` : ''}
          ${costs ? `<div class="advisor-notes"><strong>Opportunity costs</strong><ul>${costs}</ul></div>` : ''}
        </details>
      </article>`;
    }).join('')}</div>`;
  }
  content.insertAdjacentHTML('beforeend',
    `<div class="advisor-policy">${escapeHtml(data.policy.id)} · reviewed ${escapeHtml(data.policy.last_reviewed)}</div>`
  );
}

async function refreshAdvisor() {
  const button = $('btn-advisor-refresh');
  button.disabled = true;
  $('advisor-content').innerHTML = '<div class="advisor-loading"><span class="spinner"></span>Checking your latest roster…</div>';
  try {
    const selectedDump = $('advisor-dump').value;
    const query = selectedDump ? `?dump=${encodeURIComponent(selectedDump)}` : '';
    renderAdvisor(await api('/api/advisor/recommendations' + query));
  } catch(e) {
    $('advisor-content').innerHTML = `<div class="advisor-empty error">
      <span class="state-icon">!</span>
      <div><h3>Advisor needs a Player dump</h3><p>${escapeHtml(e.message)} Fetch Player data, then refresh the advisor.</p></div>
    </div>`;
  } finally {
    button.disabled = false;
  }
}

$('btn-advisor-refresh').onclick = refreshAdvisor;
$('advisor-dump').onchange = refreshAdvisor;

// ── Endpoint cards ──
document.querySelectorAll('.ep-card').forEach(card => {
  card.onclick = async () => {
    const ep = card.dataset.endpoint;
    card.classList.add('loading');
    $('output-wrap').classList.add('visible');
    $('output').textContent = '// Fetching ' + ep + '…';
    $('output-meta').textContent = 'Fetching…';
    try {
      const res = await api('/api/fetch/' + ep);
      lastFetch = { endpoint: ep, data: res.data };
      const pretty = JSON.stringify(res.data, null, 2);
      $('output').textContent = pretty;
      const ts = new Date().toLocaleTimeString();
      const note = res.saved ? ' · saved as ' + res.saved : '';
      $('output-meta').textContent = '✔ ' + ep + ' · ' + ts + note;
      $('btn-copy').disabled = false;
      $('btn-dl').disabled = false;
      toast(ep + ' fetched.');
      await refreshDumps();
      if (ep === 'player') {
        $('advisor-dump').value = '';
        refreshAdvisor();
      }
      // scroll to output
      $('output-wrap').scrollIntoView({ behavior:'smooth', block:'start' });
    } catch(e) {
      $('output').textContent = '// Error: ' + e.message;
      $('output-meta').textContent = '✘ Failed';
      toast(e.message,'err');
    } finally {
      card.classList.remove('loading');
    }
  };
});

// ── Copy / Download ──
$('btn-copy').onclick = async () => {
  if (!lastFetch) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastFetch.data, null, 2));
    toast('Copied!');
  } catch(e) { toast('Copy failed','err'); }
};

$('btn-dl').onclick = () => {
  if (!lastFetch) return;
  window.location.href = '/api/download/' + lastFetch.endpoint;
};

// ── Dumps list ──
async function refreshDumps() {
  try {
    const res = await api('/api/dumps');
    const selector = $('advisor-dump');
    const selected = selector.value;
    const playerFiles = res.files.filter(file => file.name.startsWith('player_'));
    selector.replaceChildren(new Option('Latest player dump', ''));
    playerFiles.slice(0, 30).forEach(file => {
      const modified = file.mtime_iso ? new Date(file.mtime_iso) : null;
      const label = modified && !Number.isNaN(modified.valueOf())
        ? modified.toLocaleString()
        : file.name;
      selector.add(new Option(label, file.name));
    });
    if ([...selector.options].some(option => option.value === selected)) {
      selector.value = selected;
    }
    const el = $('dumps-list');
    if (!res.files.length) { el.innerHTML = '<em>No dumps yet.</em>'; return; }
    el.innerHTML = res.files.slice(0, 30).map(f =>
      `<div class="dump-item">
         <span class="fname">${f.name}</span>
         <span class="meta">${(f.size/1024).toFixed(0)} KB</span>
         <a href="/api/dumps/${encodeURIComponent(f.name)}" download>↓</a>
       </div>`
    ).join('');
  } catch(e) {
    $('dumps-list').innerHTML = '<em>Error loading dumps</em>';
  }
}
refreshDumps();
refreshAdvisor();
</script>
</body>
</html>
"""

# ── run ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  Tacticus Dumper — http://{host}:{port}")
    print(f"  Auth:   {'enabled' if AUTH_USER else 'DISABLED (set AUTH_USER & AUTH_PASS)'}")
    print(f"  Data:   {DATA_DIR}\n")
    app.run(host=host, port=port, debug=False)
