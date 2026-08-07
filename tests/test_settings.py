import json
from pathlib import Path

import pytest

import app as app_module


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(app_module, "CONFIG_PATH", config_path)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client, config_path


def test_optional_endpoints_are_visible_by_default(client):
    test_client, _ = client

    html = test_client.get("/").get_data(as_text=True)

    assert 'data-endpoint="player"' in html
    assert 'data-endpoint="guild"' in html
    assert 'data-endpoint="guildRaid"' in html


def test_optional_endpoint_settings_hide_cards_independently(client):
    test_client, config_path = client

    response = test_client.post(
        "/api/settings",
        json={"show_guild": False, "show_guild_raid": True},
    )

    assert response.status_code == 200
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "show_guild": False,
        "show_guild_raid": True,
    }
    html = test_client.get("/").get_data(as_text=True)
    assert 'data-endpoint="player"' in html
    assert 'data-endpoint="guild"' not in html
    assert 'data-endpoint="guildRaid"' in html

    response = test_client.post("/api/settings", json={"show_guild": True})

    assert response.status_code == 200
    assert 'data-endpoint="guild"' in test_client.get("/").get_data(as_text=True)


def test_optional_endpoint_settings_can_hide_both_cards(client):
    test_client, _ = client
    test_client.post(
        "/api/settings",
        json={"show_guild": False, "show_guild_raid": False},
    )

    html = test_client.get("/").get_data(as_text=True)

    assert 'data-endpoint="player"' in html
    assert 'data-endpoint="guild"' not in html
    assert 'data-endpoint="guildRaid"' not in html


def test_advisor_card_is_available_without_optional_guild_endpoints(client):
    test_client, _ = client
    test_client.post(
        "/api/settings",
        json={"show_guild": False, "show_guild_raid": False},
    )

    html = test_client.get("/").get_data(as_text=True)

    assert 'id="advisor-card"' in html
    assert 'id="advisor-dump"' in html
    assert "no officer access required" in html
    assert "/api/advisor/recommendations" in html
    assert "encodeURIComponent(selectedDump)" in html
    assert "No ready project right now" in html
    assert 'id="history-card"' in html
    assert 'id="history-before"' in html
    assert 'id="history-after"' in html
    assert "/api/advisor/history" in html
    assert "No changes between these snapshots" in html
    assert "Advisor queue" in html
    assert 'id="show-guild"' in html
    assert 'id="show-guild-raid"' in html


def test_settings_reject_non_boolean_values(client):
    test_client, config_path = client

    response = test_client.post("/api/settings", json={"show_guild": "false"})

    assert response.status_code == 400
    assert response.get_json() == {
        "ok": False,
        "error": "show_guild must be a boolean.",
    }
    assert not config_path.exists()
