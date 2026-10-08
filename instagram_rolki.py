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

# AI: darmowe modele multimodalne OpenRouter. 3.5.1: lista DYNAMICZNA - GET /models (z kluczem, 0 zl, cache 1 h): id konczace
# sie na ":free" z "image" w architecture.input_modalities, bez modeli typu guard/content-safety; najpierw MODELE_VISION
# (preferowana kolejnosc, sprawdzone 2026-10-08 jako dostepne za darmo), potem reszta. Stara lista (qwen2.5-vl, llama-3.2-vision,
# gemini-2.0-flash-exp) dawala juz tylko 404 "unavailable for free". Model z takim 404 wypada z cache (nastepny w kolejce).
# Wspolne dla filtra rolek z IG i kontroli pierwszej klatki (ocen_vision). Klucz: panel -> Konta -> OpenRouter.
LLM_API = "https://openrouter.ai/api/v1"
MODELE_VISION = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]
POMIJANE_VISION = re.compile(r"guard|safety|shield|moderat", re.I)    # klasyfikatory tresci, nie oceniaja kadru
TIMEOUT_LLM_S = 60              # modele rozumujace (nemotron omni) odpowiadaja ok. 20 s
MAX_TOKENOW_VISION = 1500       # rozumujace zjadaja tokeny na myslenie - przy 200 oddawaly pusta tresc (finish=length)
MAX_PROB_LLM = 3                # tyle modeli z prawdziwym bledem (timeout, zla odpowiedz) na jedna ocene
MAX_404_LLM = 8                 # + tyle szybkich odmow (404/403 niedostepny za darmo, 429 chwilowo przeciazony)
CACHE_MODELI_S = 3600
CACHE_BEZ_LISTY_S = 300         # lista /models nie przyszla -> preferowane na 5 min, potem znow pytamy
_cache_modeli = {"czas": 0.0, "modele": None, "waznosc": CACHE_MODELI_S}


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
            blad = json.loads(surowe)["error"]
            msg = str(blad.get("message") or "")
            surowy = str((blad.get("metadata") or {}).get("raw") or "")
        except (ValueError, KeyError, TypeError, AttributeError):
            msg, surowy = surowe[:200], ""
        if e.code == 429:
            # 3.5.1: dzienny limit darmowych zapytan konta (koniec na dzis) vs chwilowo przeciazony model (nastepny model)
            dzienny = "per-day" in (msg + surowy).lower() or "per day" in (msg + surowy).lower()
            raise RuntimeError("dzienny limit darmowych zapytan OpenRouter" if dzienny else
                               "OpenRouter 429: darmowy model chwilowo przeciazony")
        podpowiedz = {401: "zly klucz OpenRouter", 402: "OpenRouter chce doladowania"}
        raise RuntimeError(podpowiedz.get(e.code) or f"OpenRouter {e.code}: {msg}"[:200])
    except (OSError, ValueError) as e:
        raise RuntimeError(f"brak polaczenia z OpenRouter ({e})")


def _darmowe_obrazkowe(dane):
    """Z odpowiedzi GET /models: id darmowych (":free") modeli przyjmujacych obrazek, bez guard/content-safety (kolejnosc listy)."""
    wynik = []
    for m in dane if isinstance(dane, list) else []:
        mid = str((m or {}).get("id") or "") if isinstance(m, dict) else ""
        if not mid.endswith(":free") or POMIJANE_VISION.search(mid) or mid in wynik:
            continue
        arch = m.get("architecture") or {}
        wejscia = arch.get("input_modalities")
        if wejscia is None:
            wejscia = (arch.get("modality") or "").split("->")[0]       # stary format "text+image->text"
        if "image" in (wejscia if isinstance(wejscia, str) else " ".join(map(str, wejscia))):
            wynik.append(mid)
    return wynik


def modele_vision():
    """Darmowe modele wizyjne OpenRouter do oceny obrazka (cache 1 h): GET /models -> ":free" + "image" na wejsciu, bez
    guard/safety; najpierw MODELE_VISION (preferowana kolejnosc), potem reszta z listy. Lista nie przyszla = MODELE_VISION
    (na 5 min). Pusta lista darmowych obrazkowych = tez MODELE_VISION (moze OpenRouter ich nie wypisuje, a dzialaja)."""
    c = _cache_modeli
    if c["modele"] is not None and time.time() - c["czas"] < c.get("waznosc", CACHE_MODELI_S):
        return c["modele"]
    try:
        dostepne = _darmowe_obrazkowe((_http_json("GET", LLM_API + "/models", timeout=15) or {}).get("data") or [])
        modele = [m for m in MODELE_VISION if m in dostepne] + [m for m in dostepne if m not in MODELE_VISION]
        waznosc = CACHE_MODELI_S
        if not modele:
            modele = list(MODELE_VISION)
    except RuntimeError:
        modele, waznosc = list(MODELE_VISION), CACHE_BEZ_LISTY_S
    c.update(czas=time.time(), modele=modele, waznosc=waznosc)
    return modele


def _rodzaj_bledu(blad):
    """Klasa bledu modelu wizyjnego (sprawdzone na zywo 2026-10-08):
    'zniknal'    - 404 "unavailable for free" / "No endpoints found", 403 "only available on agentic harnesses" (inkling):
                   ten model u nas nie zadziala - wypada z cache, nastepny (nie liczy sie do MAX_PROB_LLM);
    'przeciazony'- 429 "temporarily rate-limited upstream" (gemma 4 przez Google AI Studio) - nastepny, bez liczenia;
    'koniec'     - zly klucz, brak srodkow, dzienny limit darmowych zapytan - nie ma sensu pytac innych;
    'inny'       - timeout, zla odpowiedz (np. model rozumujacy bez JSON) - liczy sie do MAX_PROB_LLM."""
    t = str(blad).lower()
    if "zly klucz" in t or "doladowania" in t or "dzienny limit" in t:
        return "koniec"
    if ("openrouter 404" in t or "unavailable for free" in t or "no endpoints found" in t
            or "agentic harness" in t):
        return "zniknal"
    if "openrouter 429" in t or "rate-limited" in t:
        return "przeciazony"
    return "inny"


def odrzuc_model(model):
    """Model oddal 404 "unavailable for free" - wypada z cache modeli wizyjnych (do nastepnego odswiezenia listy)."""
    c = _cache_modeli
    if c["modele"] is not None and model in c["modele"]:
        c["modele"] = [m for m in c["modele"] if m != model]


def ocen_vision(zapytaj, data_url, log=None):
    """WSPOLNE dla filtra rolek z IG i kontroli pierwszej klatki: kolejne darmowe modele wizyjne (modele_vision), az ktorys
    odpowie. zapytaj(model, data_url) -> {"ok", "powod"} (RuntimeError/ValueError = blad). Model z 404 "unavailable for free"
    wypada z cache i nie liczy sie do MAX_PROB_LLM (max MAX_404_LLM takich na raz); zly klucz / brak srodkow = koniec.
    Zwraca ({"ok", "powod", "zrodlo": "openrouter:<model>"}, "") albo (None, "opis bledow")."""
    bledy, prawdziwe, szybkie = [], 0, 0
    for model in list(modele_vision()):
        if prawdziwe >= MAX_PROB_LLM or szybkie >= MAX_404_LLM:
            break
        try:
            w = zapytaj(model, data_url)
        except (RuntimeError, ValueError) as e:
            bledy.append(f"{model.split('/')[-1]}: {e}")
            rodzaj = _rodzaj_bledu(e) if isinstance(e, RuntimeError) else "inny"
            if rodzaj == "koniec":
                break
            if rodzaj == "zniknal":
                odrzuc_model(model)
                if log:
                    log(f"model wizyjny {model} niedostepny dla nas za darmo - wypada z listy, probuje nastepny")
            if rodzaj in ("zniknal", "przeciazony"):
                szybkie += 1
                continue
            prawdziwe += 1
            continue
        return {"ok": bool(w["ok"]), "powod": w.get("powod") or "", "zrodlo": f"openrouter:{model}"}, ""
    return None, ("; ".join(bledy) or "brak darmowych modeli wizyjnych na OpenRouter")[:300]


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
        "temperature": 0.2, "max_tokens": MAX_TOKENOW_VISION,
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
    w, bledy = ocen_vision(lambda m, d: _zapytaj_vision(m, d), data_url, log=log)
    if w is None:
        log("AI-ocena niedostepna (" + bledy[:200] + ") - decyduja heurystyki")
    return w


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
