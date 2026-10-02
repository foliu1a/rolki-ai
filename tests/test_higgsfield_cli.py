# -*- coding: utf-8 -*-
"""Czyste funkcje wrappera (bez odpalania CLI): parsowanie JSON, kredyty, koszt, URL wyniku, flagi."""
import os

import pytest

import higgsfield_cli as hf


def test_parsuj_json_z_postepem_przed():
    assert hf._parsuj_json('Uploading... 100%\n{"id": "a"}') == {"id": "a"}
    assert hf._parsuj_json("") is None
    with pytest.raises(hf.HiggsfieldBlad):
        hf._parsuj_json("tylko tekst")


@pytest.mark.parametrize("dane,oczekiwane", [
    ({"credits": 1234}, 1234),
    ({"workspace": {"balance": 99.0}}, 99),
    ({"plan": "ultra"}, None),
    ("zle", None),
])
def test_wyciagnij_kredyty(dane, oczekiwane):
    assert hf._wyciagnij_kredyty(dane) == oczekiwane


@pytest.mark.parametrize("dane,oczekiwane", [
    (45, 45),
    ({"cost": 72}, 72),
    ({"data": {"estimated_credits": 21}}, 21),
    ([{"credits": 10}], 10),
    ({"ok": True}, None),
    (True, None),
])
def test_wyciagnij_koszt(dane, oczekiwane):
    assert hf._wyciagnij_koszt(dane) == oczekiwane


def test_wyniki_url_rozne_ksztalty():
    job = {
        "id": "j1",
        "status": "completed",
        "results": {"raw": {"url": "https://cdn.x/a.mp4?sig=1"}, "min": "https://cdn.x/a_min.mp4"},
        "input": {"thumbnail": "https://cdn.x/thumb"},
        "jobs": [{"video_url": "https://cdn.x/a.mp4?sig=1"}],
    }
    assert hf.wyniki_url(job) == ["https://cdn.x/a.mp4?sig=1", "https://cdn.x/a_min.mp4"]
    assert hf.wyniki_url({"status": "completed"}) == []


def test_job_id_i_status():
    assert hf.job_id_z({"job_set_id": 7}) == "7"
    assert hf.job_id_z(None) is None
    assert hf.status_joba({"state": "COMPLETED"}) == "completed"


def test_flagi(tmp_path):
    plik = tmp_path / "ref.png"
    plik.write_bytes(b"x")
    flagi = hf._flagi(
        {"prompt": "a b", "duration": 6, "generate_audio": False, "pusty": "", "brak": None},
        {"video": "uuid-v", "image": [str(plik), "uuid-2", ""], "start_image": "s"},
    )
    assert flagi == [
        "--prompt", "a b", "--duration", "6", "--generate_audio", "false",
        "--video", "uuid-v", "--image", os.path.abspath(str(plik)), "--image", "uuid-2",
        "--start-image", "s",
    ]


def test_komenda_podglad_cytuje():
    k = hf.komenda_podglad("seedance_2_5", {"prompt": 'ona "mowi"'})
    assert k.startswith("higgsfield generate create seedance_2_5 --prompt")
    assert k.endswith("--wait")
    assert '"ona \\"mowi\\""' in k
