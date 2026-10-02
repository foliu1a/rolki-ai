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


def test_ksztalt_cli_1_1_26():
    """Prawdziwy ksztalt z `generate create --wait --json` (lista jobow) i bez --wait (lista UUID)."""
    job = {"created_at": "2026-10-01T00:00:00Z", "display_name": "Seedance 2.5", "id": "1111", "job_type": "seedance_2_5",
           "min_result_url": "https://cdn/MIN.mp4", "params": {"medias": [{"data": {"id": "u1"}}], "prompt": "p"},
           "result_url": "https://cdn/RESULT.mp4", "status": "completed", "thumbnail_url": "https://cdn/THUMB.jpg"}
    assert hf.wyniki_url(job) == ["https://cdn/RESULT.mp4", "https://cdn/MIN.mp4"]
    assert hf.job_udany(job) and hf.job_id_z(job) == "1111"
    padl = dict(job, status="nsfw", result_url=None, min_result_url=None)
    assert hf.wyniki_url(padl) == [] and hf.job_nieudany(padl)
    bez_url = dict(job, result_url=None, min_result_url=None)
    assert hf.wyniki_url(bez_url) == [] and hf.job_udany(bez_url)


def test_generuj_bez_wait_zwraca_id(monkeypatch):
    monkeypatch.setattr(hf, "_uruchom", lambda args, timeout=0: ["9999-aaaa"])
    assert hf.generuj("seedance_2_5", {"prompt": "x"}, wait=False) == {"id": "9999-aaaa", "status": "queued"}
    monkeypatch.setattr(hf, "_uruchom", lambda args, timeout=0: [{"id": "1", "status": "completed", "result_url": "https://c/r.mp4"}])
    assert hf.generuj("seedance_2_5", {"prompt": "x"})["result_url"] == "https://c/r.mp4"


def test_doczytaj_url(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    odpowiedzi = [{"id": "j1", "status": "completed", "result_url": None},
                  {"id": "j1", "status": "completed", "result_url": "https://c/late.mp4"}]
    monkeypatch.setattr(hf, "job", lambda jid: odpowiedzi.pop(0))
    job, urls = hf.doczytaj_url({"id": "j1", "status": "completed", "result_url": None})
    assert urls == ["https://c/late.mp4"] and job["result_url"] == "https://c/late.mp4"
    # nie odpytuje, gdy URL juz jest albo job nieudany
    monkeypatch.setattr(hf, "job", lambda jid: (_ for _ in ()).throw(AssertionError("nie powinno pytac")))
    assert hf.doczytaj_url({"id": "j2", "status": "completed", "result_url": "https://c/x.mp4"})[1] == ["https://c/x.mp4"]
    assert hf.doczytaj_url({"id": "j3", "status": "failed"})[1] == []


def test_prompt_na_drut_skleja_akapity():
    from dostawcy import higgsfield as dh
    assert dh._prompt_na_drut("akapit 1\n\n\nakapit 2\n  \nakapit 3\n") == "akapit 1\nakapit 2\nakapit 3"
    _, params, _ = dh.przygotuj({"prompt": "a\n\nb", "images": []})
    assert params["prompt"] == "a\nb"
