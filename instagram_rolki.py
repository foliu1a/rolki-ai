# -*- coding: utf-8 -*-
"""Zrodlo klipow z Instagrama: pobierz najnowsze rolki z publicznych profili (przez Apify, dostawcy/instagram.py),
AI odsiewa slabe, dobre laduja we wrzutni persony (`tu wrzucasz rolki\\<Persona>`) - stamtad bierze je istniejacy
character swap (skanuj -> generuj).

Obieg (jeden kandydat):
  dedup (shortcode juz widziany? -> pomijamy)  ->  wstepnie po metadanych (dlugosc)  ->  pobranie pliku z CDN IG
  ->  heurystyki z ffprobe (pionowy kadr, 3-60 s, nie za mala rozdzielczosc)  ->  AI (OpenRouter, darmowy model
  multimodalny: jedna kobieta, pion, bez napisow, dlonie nie zaslaniaja twarzy, wyrazny ruch -> {ok, powod})
  ->  AKCEPT: plik do zrodla_dir persony (round-robin po personach z referencjami).

Bez klucza OpenRouter AI-ocena jest wylaczona - decyduja same heurystyki (z wpisem w logu). Widziane shortcode'y
pamietamy w <dane>/instagram_widziane.json (poza gitem), zeby nie pobierac drugi raz tego samego i liczyc dzienny limit.
Nic nie wydaje kredytow Higgsfielda; Apify ma darmowy limit, a i tak wolamy go tylko gdy user wklei klucz.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

import baza
import klatki
import sekrety
from dostawcy import BladDostawcy, BrakKlucza
from dostawcy import instagram

PLIK_WIDZIANE = "instagram_widziane.json"       # <dane>/instagram_widziane.json (obok stan.json) - dedup + dzienny licznik
STAGING = "_ig_staging"                         # pobieramy tu NAJPIERW (modelki/_ig_staging); do wrzutni leca tylko zaakceptowane

# heurystyki (bez AI): co uznajemy za dobry klip do swapa
MIN_CZAS_S, MAX_CZAS_S = 3.0, 60.0
MIN_KROTKI_BOK = 360            # najkrotszy bok w px - mniej = za slaba jakosc do swapa

# AI: darmowe modele multimodalne OpenRouter (nazwy bywaja zmieniane - podmien, gdy OpenRouter je wycofa; GET /models
# odfiltruje te, ktorych juz nie ma albo nie przyjmuja obrazka). Klucz: panel -> Konta -> OpenRouter (bez weryfikacji dowodem).
LLM_API = "https://openrouter.ai/api/v1"
MODELE_VISION = [
    "qwen/qwen2.5-vl-72b-instruct:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "google/gemini-2.0-flash-exp:free",
]
TIMEOUT_LLM_S = 30
MAX_PROB_LLM = 3
_cache_modeli = {"czas": 0.0, "modele": None}


def _log(msg):
    print(time.strftime("%H:%M:%S"), "[instagram]", msg, flush=True)


# ---------------- dedup + dzienny licznik ----------------

def _plik_widziane():
    return os.path.join(os.path.dirname(baza.PLIK_STANU), PLIK_WIDZIANE)


def widziane():
    """{shortcode: {czas, akcja: pobrana|odrzucona, slug, plik, powod}}."""
    d = baza._wczytaj_json(_plik_widziane(), {})
    return d if isinstance(d, dict) else {}


def juz_widziany(shortcode):
    return str(shortcode) in widziane()


def oznacz(shortcode, akcja, **pola):
    """Zapisuje, ze shortcode zostal obsluzony (pobrana / odrzucona) - dedup i dzienny licznik. czas = teraz."""
    plik = _plik_widziane()
    with baza._rmw(plik):
        d = baza._wczytaj_json(plik, {})
        if not isinstance(d, dict):
            d = {}
        d[str(shortcode)] = dict({"czas": baza._teraz(), "akcja": akcja}, **pola)
        # nie puchnijmy w nieskonczonosc - trzymamy ostatnie 5000 (po czasie)
        if len(d) > 5000:
            for sc in sorted(d, key=lambda k: str(d[k].get("czas") or ""))[:len(d) - 5000]:
                d.pop(sc, None)
        baza._zapisz_json(plik, d)


def pobrane_z_dnia(dzien=None):
    """Ile rolek z IG pobrano (zaakceptowano) danego dnia LOKALNEGO - osobny licznik od generacji."""
    dzien = dzien or baza._dzis()
    return sum(1 for w in widziane().values()
               if isinstance(w, dict) and w.get("akcja") == "pobrana" and baza.dzien_lokalny(w.get("czas")) == dzien)


# ---------------- heurystyki (bez AI) ----------------

def heurystyka_meta(rolka):
    """Wstepna ocena z samych metadanych Apify (przed pobraniem pliku) - odrzuca tylko oczywiscie zle dlugosci.
    Zwraca powod odrzucenia albo None (mozna pobierac)."""
    czas = rolka.get("czas_s")
    if isinstance(czas, (int, float)) and czas > 0:
        if czas < MIN_CZAS_S:
            return f"za krotka ({czas:g} s < {MIN_CZAS_S:g} s)"
        if czas > MAX_CZAS_S:
            return f"za dluga ({czas:g} s > {MAX_CZAS_S:g} s)"
    return None


def filtr_heurystyki(inf):
    """Heurystyki z ffprobe (info z klatki.info): (ok, powod). Pionowy kadr, 3-60 s, nie za mala rozdzielczosc."""
    szer, wys, czas = int(inf.get("szer") or 0), int(inf.get("wys") or 0), float(inf.get("czas") or 0)
    if szer <= 0 or wys <= 0:
        return False, "nie moge odczytac wymiarow wideo"
    if szer >= wys:
        return False, f"kadr nie jest pionowy ({szer}x{wys})"
    if not (MIN_CZAS_S <= czas <= MAX_CZAS_S):
        return False, f"dlugosc {czas:g} s poza zakresem {MIN_CZAS_S:g}-{MAX_CZAS_S:g} s"
    if min(szer, wys) < MIN_KROTKI_BOK:
        return False, f"za mala rozdzielczosc ({szer}x{wys})"
    return True, ""


# ---------------- AI filtr (OpenRouter, darmowy model multimodalny) ----------------

def _http_json(metoda, url, cialo=None, timeout=TIMEOUT_LLM_S):
    """Jedno zapytanie do OpenRouter (podmieniane w testach). Rzuca RuntimeError z polskim opisem. Wzor: asystent.py."""
    klucz = sekrety.klucz("openrouter")
    naglowki = {"Content-Type": "application/json", "User-Agent": "rolki-ai/3.4", "X-Title": "rolki-ai"}
    if klucz:
        naglowki["Authorization"] = f"Bearer {klucz}"
    req = urllib.request.Request(url, data=json.dumps(cialo).encode("utf-8") if cialo is not None else None,
                                 method=metoda, headers=naglowki)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as odp:
            return json.loads(odp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        surowe = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            msg = json.loads(surowe)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = surowe[:200]
        podpowiedz = {401: "zly klucz OpenRouter", 402: "OpenRouter chce doladowania",
                      429: "darmowe modele OpenRouter przeciazone albo dzienny limit"}
        raise RuntimeError(podpowiedz.get(e.code) or f"OpenRouter {e.code}: {msg}"[:200])
    except (OSError, ValueError) as e:
        raise RuntimeError(f"brak polaczenia z OpenRouter ({e})")


def modele_vision():
    """MODELE_VISION, ktore OpenRouter nadal ma i przyjmuja obrazek (GET /models, cache 1 h); blad listy = cala lista."""
    c = _cache_modeli
    if c["modele"] is not None and time.time() - c["czas"] < 3600:
        return c["modele"]
    try:
        dane = (_http_json("GET", LLM_API + "/models", timeout=15) or {}).get("data") or []
        obrazkowe = set()
        for m in dane:
            arch = m.get("architecture") or {}
            wejscia = arch.get("input_modalities") or arch.get("modality") or ""
            if "image" in (wejscia if isinstance(wejscia, str) else " ".join(wejscia)):
                obrazkowe.add(m.get("id"))
        modele = [m for m in MODELE_VISION if m in obrazkowe] or list(MODELE_VISION)
    except RuntimeError:
        modele = list(MODELE_VISION)
    c.update(czas=time.time(), modele=modele)
    return modele


SYSTEM_VISION = (
    "You check whether a short vertical video is a good source clip for a face/body swap of a single woman. "
    "You are shown a contact sheet with 1-2 frames from the clip. Answer in Polish."
)
PYTANIE_VISION = (
    "Oceń tę rolkę jako materiał źródłowy do podmiany postaci. Dobra rolka to: dokładnie JEDNA osoba (kobieta), kadr "
    "pionowy, BEZ napisów/tekstu na ekranie, dłonie NIE zasłaniają twarzy, wyraźnie widać postać i ruch. Odrzuć, gdy: "
    "nikogo nie widać, kilka osób, mężczyzna, dużo tekstu/napisów, twarz zasłonięta, sam przedmiot/jedzenie/krajobraz. "
    'Odpowiedz TYLKO obiektem JSON: {"ok": true/false, "powod": "krótko po polsku, max 100 znaków"}.'
)


def _json_z_tekstu(tekst):
    t = re.sub(r"^```(?:json)?|```$", "", (tekst or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("brak JSON w odpowiedzi")
    return json.loads(m.group(0))


def _zapytaj_vision(model, data_url, timeout=TIMEOUT_LLM_S):
    """Jedno zapytanie multimodalne do OpenRouter -> {"ok": bool, "powod": str}. Seam do podmiany w testach."""
    odp = _http_json("POST", LLM_API + "/chat/completions", {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_VISION},
            {"role": "user", "content": [
                {"type": "text", "text": PYTANIE_VISION},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        "temperature": 0.2, "max_tokens": 200,
    }, timeout=timeout)
    if isinstance(odp, dict) and odp.get("error"):
        raise RuntimeError(f"OpenRouter: {str((odp['error'] or {}).get('message', odp['error']))[:200]}")
    try:
        tresc = odp["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("dziwna odpowiedz z OpenRouter")
    w = _json_z_tekstu(tresc)
    if not isinstance(w, dict) or "ok" not in w:
        raise ValueError("odpowiedz bez pola ok")
    return {"ok": bool(w["ok"]), "powod": str(w.get("powod") or "")[:200]}


def _data_url(sciezka_jpg):
    with open(sciezka_jpg, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return "data:image/jpeg;base64," + b64


def filtr_ai(klatka_jpg, log=None):
    """AI-ocena rolki z arkusza klatek. Zwraca {"ok", "powod", "zrodlo": "openrouter:<model>"} albo None, gdy AI jest
    niedostepne (brak klucza OpenRouter / caly czas blad / zly plik) - wtedy decyduja same heurystyki."""
    log = log or (lambda *_: None)
    if not sekrety.klucz("openrouter"):
        return None
    try:
        data_url = _data_url(klatka_jpg)
    except OSError:
        return None
    bledy = []
    for model in modele_vision()[:MAX_PROB_LLM]:
        try:
            w = _zapytaj_vision(model, data_url)
        except (RuntimeError, ValueError) as e:
            bledy.append(f"{model.split('/')[-1]}: {e}")
            if "zly klucz" in str(e) or "doladowania" in str(e):
                break
            continue
        return {"ok": bool(w["ok"]), "powod": w.get("powod") or "", "zrodlo": f"openrouter:{model}"}
    if bledy:
        log("AI-ocena niedostepna (" + "; ".join(bledy)[:200] + ") - decyduja heurystyki")
    return None


# ---------------- pobierz + filtruj + zapisz (round-robin po personach) ----------------

def _bezpieczna(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s or "")).strip("_") or "rolka"


def _unikalna(sciezka):
    if not os.path.exists(sciezka):
        return sciezka
    baza_, ext = os.path.splitext(sciezka)
    i = 2
    while os.path.exists(f"{baza_}_{i}{ext}"):
        i += 1
    return f"{baza_}_{i}{ext}"


def _folder_staging():
    folder = os.path.join(baza.KATALOG_MODELEK, STAGING)   # nazwa z "_" - lista_modelek() ja pomija (to nie persona)
    os.makedirs(folder, exist_ok=True)
    return folder


def pobierz_filtruj_zapisz(profile, persony, limit, na_profil=5, *, przez_apify=False, uzyj_ai=True, log=None, stop=None):
    """Pobiera kandydatow z `profile` (Apify), filtruje (dedup -> metadane -> pobranie -> heurystyki -> AI), zaakceptowane
    zapisuje round-robin do zrodla_dir person. `limit` = ile MAX zaakceptowac teraz (dzienny limit liczy wywolujacy).
    Zwraca {"zapisane": [(slug, plik, rolka)], "odrzucone": [(shortcode, powod)], "pominiete": int, "kandydaci": int,
    "ai": bool, "profile_blad": str|None}. Bez klucza Apify -> BrakKlucza; blad Apify -> BladDostawcy."""
    log = log or _log
    wynik = {"zapisane": [], "odrzucone": [], "pominiete": 0, "kandydaci": 0, "ai": False, "profile_blad": None}
    if int(limit or 0) <= 0 or not persony:
        return wynik
    rolki = instagram.rolki_z_profili(profile, na_profil=na_profil)   # moze rzucic BrakKlucza / BladDostawcy
    wynik["kandydaci"] = len(rolki)
    if not rolki:
        return wynik
    staging = _folder_staging()
    # round-robin: zacznij od persony po ostatnio uzytej (rozklad rowny tez miedzy przebiegami)
    start = pobrane_z_dnia_total() % len(persony)
    idx = 0
    ai_zgloszony = False
    for rolka in rolki:
        if stop is not None and stop.is_set():
            break
        if len(wynik["zapisane"]) >= int(limit):
            break
        sc = rolka.get("shortcode")
        if not sc or juz_widziany(sc):
            wynik["pominiete"] += 1
            continue
        if not rolka.get("video_url"):
            oznacz(sc, "odrzucona", powod="brak adresu wideo")
            wynik["odrzucone"].append((sc, "brak adresu wideo"))
            continue
        powod_meta = heurystyka_meta(rolka)
        if powod_meta:
            oznacz(sc, "odrzucona", powod=powod_meta)
            wynik["odrzucone"].append((sc, powod_meta))
            log(f"IG {sc}: odrzucona ({powod_meta})")
            continue
        nazwa = f"ig_{_bezpieczna(rolka.get('autor'))}_{_bezpieczna(sc)}.mp4"
        tmp = os.path.join(staging, nazwa)
        try:
            if przez_apify:
                instagram.pobierz_przez_apify(rolka, tmp)
            else:
                instagram.pobierz(rolka["video_url"], tmp)
        except BladDostawcy as e:
            instagram._sprzataj(tmp)
            oznacz(sc, "odrzucona", powod="pobieranie: " + str(e)[:150])
            wynik["odrzucone"].append((sc, "pobieranie"))
            log(f"IG {sc}: nie pobralem - {e}")
            continue
        try:
            inf = klatki.info(tmp)
        except Exception as e:
            instagram._sprzataj(tmp)
            oznacz(sc, "odrzucona", powod="nieczytelny plik")
            wynik["odrzucone"].append((sc, "nieczytelny plik"))
            log(f"IG {sc}: nieczytelny plik ({e})")
            continue
        ok, powod = filtr_heurystyki(inf)
        if not ok:
            instagram._sprzataj(tmp)
            oznacz(sc, "odrzucona", powod=powod)
            wynik["odrzucone"].append((sc, powod))
            log(f"IG {sc}: odrzucona ({powod})")
            continue
        if uzyj_ai and sekrety.klucz("openrouter"):
            ocena = None
            arkusz = os.path.join(staging, _bezpieczna(sc) + "_arkusz.jpg")
            try:
                klatki.arkusz(tmp, arkusz, ile=2, kolumny=2)
                ocena = filtr_ai(arkusz, log=log)
            except Exception as e:
                log(f"IG {sc}: nie zrobilem arkusza do AI ({e}) - decyduja heurystyki")
            finally:
                instagram._sprzataj(arkusz)
            if ocena is not None:
                wynik["ai"] = True
                if not ocena["ok"]:
                    instagram._sprzataj(tmp)
                    oznacz(sc, "odrzucona", powod="AI: " + (ocena["powod"] or "slaba"))
                    wynik["odrzucone"].append((sc, "AI: " + (ocena["powod"] or "slaba")))
                    log(f"IG {sc}: AI odrzucilo ({ocena['powod']})")
                    continue
        elif uzyj_ai and not ai_zgloszony:
            ai_zgloszony = True
            log("AI-ocena wylaczona (brak klucza OpenRouter) - decyduja same heurystyki")
        slug = persony[(start + idx) % len(persony)]
        idx += 1
        cel = _unikalna(os.path.join(baza.folder_zrodel(slug), nazwa))
        try:
            os.replace(tmp, cel)
        except OSError:
            import shutil
            shutil.move(tmp, cel)
        oznacz(sc, "pobrana", slug=slug, plik=os.path.basename(cel), autor=rolka.get("autor"), url=rolka.get("url"))
        wynik["zapisane"].append((slug, cel, rolka))
        log(f"IG {sc}: zapisana do {slug} ({os.path.basename(cel)})")
    return wynik


def pobrane_z_dnia_total():
    """Ile w ogole rolek z IG pobralismy (do rownego round-robina miedzy przebiegami)."""
    return sum(1 for w in widziane().values() if isinstance(w, dict) and w.get("akcja") == "pobrana")
