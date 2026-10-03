# -*- coding: utf-8 -*-
"""
Wrapper na oficjalne CLI Higgsfield (@higgsfield/cli) - subprocess + --json.

Zero zaleznosci poza stdlib. CLI ma byc zainstalowane globalnie przez npm
(`npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli`) i zalogowane
(`higgsfield auth login` - robi to uzytkownik, otwiera sie przegladarka).

Najwazniejsze funkcje:
    zalogowany()            -> bool
    konto()                 -> {"email", "plan", "credits", ...}
    kredyty()               -> int
    model(jst)              -> schema modelu (parametry, media, aspect_ratios, durations)
    koszt(jst, params, media)   -> int (kredyty, bez tworzenia joba)
    generuj(jst, params, media, wait=True) -> job dict (z URL wyniku)
    wyniki_url(job)         -> [url, ...]  (najpewniejszy pierwszy, bez wejsc i miniatur)
    status_joba(job)        -> "completed" | "failed" | ...   job_udany(job) / job_nieudany(job) / blad_joba(job)
    pobierz(url, sciezka)   -> sciezka
    glosy()                 -> lista glosow do TTS / voice-change
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

# Timeouty (sekundy) dla subprocess - CLI samo ma --wait-timeout, to jest tylko bezpiecznik.
TIMEOUT_KROTKI = 60
TIMEOUT_UPLOAD = 15 * 60
TIMEOUT_GENERACJA = 45 * 60


class HiggsfieldBlad(Exception):
    pass


class NieZalogowany(HiggsfieldBlad):
    pass


class BrakCLI(HiggsfieldBlad):
    pass


def sciezka_cli():
    """Zwraca sciezke do binarki CLI. Preferuje hf.exe z paczki npm (omija shim .cmd)."""
    kandydaci = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        baza = os.path.join(appdata, "npm", "node_modules", "@higgsfield", "cli", "vendor")
        kandydaci.append(os.path.join(baza, "hf.exe"))
        kandydaci.append(os.path.join(baza, "hf"))
    for k in kandydaci:
        if os.path.isfile(k):
            return k
    # UWAGA: nie szukamy `hf` w PATH - to na tej maszynie jest CLI Hugging Face.
    for nazwa in ("higgsfield", "higgs"):
        znaleziony = shutil.which(nazwa)
        if znaleziony:
            return znaleziony
    raise BrakCLI(
        "Nie znaleziono CLI Higgsfield. Zainstaluj: "
        "npm install -g --allow-scripts=@higgsfield/cli @higgsfield/cli"
    )


def _uruchom(args, timeout=TIMEOUT_KROTKI, json_out=True):
    """Odpala CLI, zwraca sparsowany JSON (albo surowy tekst gdy json_out=False)."""
    cmd = [sciezka_cli()] + list(args)
    if json_out:
        cmd.append("--json")
    cmd.append("--no-color")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise HiggsfieldBlad(f"CLI nie odpowiedzialo w {timeout}s: {' '.join(args[:3])}")

    out = proc.stdout or ""
    err = proc.stderr or ""
    if proc.returncode != 0:
        tekst = (err + "\n" + out).strip()
        if re.search(r"not authenticated|session expired|auth login", tekst, re.I):
            raise NieZalogowany(
                "CLI Higgsfield nie jest zalogowane. Odpal w terminalu: higgsfield auth login"
            )
        if re.search(r"no workspace selected", tekst, re.I):
            raise NieZalogowany(
                "CLI Higgsfield nie ma wybranego workspace. Po `auth login` odpal: "
                "higgsfield workspace list, potem higgsfield workspace set <id>"
            )
        raise HiggsfieldBlad(tekst or f"CLI zwrocilo kod {proc.returncode}")

    if not json_out:
        return out
    return _parsuj_json(out)


def _parsuj_json(tekst):
    tekst = tekst.strip()
    if not tekst:
        return None
    try:
        return json.loads(tekst)
    except json.JSONDecodeError:
        pass
    # CLI czasem drukuje postep przed JSON-em - bierzemy ostatni blok zaczynajacy sie od { lub [
    for i in range(len(tekst)):
        if tekst[i] in "{[":
            try:
                return json.loads(tekst[i:])
            except json.JSONDecodeError:
                continue
    raise HiggsfieldBlad(f"Nie umiem sparsowac odpowiedzi CLI:\n{tekst[:800]}")


# ---------------- konto ----------------

def konto():
    dane = _uruchom(["account", "status"])
    return dane if isinstance(dane, dict) else {"surowe": dane}


def zalogowany():
    try:
        konto()
        return True
    except NieZalogowany:
        return False


def _wyciagnij_kredyty(dane):
    """Odporne szukanie liczby kredytow w odpowiedzi account status."""
    if not isinstance(dane, dict):
        return None
    for klucz in ("credits", "available_credits", "balance", "credit_balance"):
        if klucz in dane and isinstance(dane[klucz], (int, float)):
            return int(dane[klucz])
    for v in dane.values():
        if isinstance(v, dict):
            w = _wyciagnij_kredyty(v)
            if w is not None:
                return w
    return None


def kredyty():
    w = _wyciagnij_kredyty(konto())
    if w is None:
        raise HiggsfieldBlad(
            "account status nie zwrocilo pola z kredytami - sprawdz `higgsfield account status --json`"
        )
    return w


# ---------------- modele ----------------

def modele(typ=None):
    """Lista modeli z CLI (dicty z job_type/name/type). Wymaga logowania."""
    args = ["model", "list"]
    if typ in ("image", "video", "audio", "text"):
        args.append(f"--{typ}")
    dane = _uruchom(args)
    if isinstance(dane, dict):
        for k in ("items", "models", "data"):
            if isinstance(dane.get(k), list):
                return dane[k]
    return dane if isinstance(dane, list) else []


def model(jst):
    return _uruchom(["model", "get", jst])


# ---------------- budowanie flag ----------------

# Nazwy rol mediow -> flaga CLI. Wartosc moze byc sciezka/UUID albo lista.
_FLAGI_MEDIA = {
    "video": "--video",
    "image": "--image",
    "audio": "--audio",
    "start_image": "--start-image",
    "end_image": "--end-image",
    "image_references": "--image-references",
    "video_references": "--video-references",
    "audio_references": "--audio-references",
}


def _flagi(params=None, media=None):
    flagi = []
    for k, v in (params or {}).items():
        if v is None or v == "":
            continue
        flaga = "--" + str(k)
        if isinstance(v, bool):
            flagi += [flaga, "true" if v else "false"]
        else:
            flagi += [flaga, str(v)]
    for rola, wartosc in (media or {}).items():
        flaga = _FLAGI_MEDIA.get(rola, "--" + rola.replace("_", "-"))
        if wartosc is None or wartosc == "":
            continue
        lista = wartosc if isinstance(wartosc, (list, tuple)) else [wartosc]
        for w in lista:
            if not w:
                continue
            w = str(w)
            if os.path.exists(w):
                w = os.path.abspath(w)
            flagi += [flaga, w]
    return flagi


def _cytuj(s):
    if s.startswith('"'):
        return s
    if " " in s or '"' in s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def komenda_podglad(jst, params=None, media=None, wait=True):
    """Zwraca komende jako string (do --dry-run / logow)."""
    czesci = ["higgsfield", "generate", "create", jst] + _flagi(params, media)
    if wait:
        czesci.append("--wait")
    return " ".join(_cytuj(c) for c in czesci)


# ---------------- koszt / generacja ----------------

def koszt(jst, params=None, media=None):
    """Szacunek kredytow bez tworzenia joba. Zwraca int (albo None gdy CLI nie podalo liczby)."""
    dane = _uruchom(["generate", "cost", jst] + _flagi(params, media), timeout=TIMEOUT_UPLOAD)
    return _wyciagnij_koszt(dane)


def _wyciagnij_koszt(dane):
    if isinstance(dane, bool):
        return None
    if isinstance(dane, (int, float)):
        return int(dane)
    if isinstance(dane, dict):
        for k in ("credits", "cost", "estimated_credits", "estimated_cost", "price", "total"):
            if k in dane and isinstance(dane[k], (int, float)) and not isinstance(dane[k], bool):
                return int(dane[k])
        for v in dane.values():
            w = _wyciagnij_koszt(v)
            if w is not None:
                return w
    if isinstance(dane, list) and dane:
        return _wyciagnij_koszt(dane[0])
    return None


def generuj(jst, params=None, media=None, wait=True, wait_timeout="30m", wait_interval="5s"):
    """Tworzy job. Z wait=True blokuje do konca i zwraca obiekt joba:
    {id, job_type, display_name, status, created_at, params, result_url, min_result_url, thumbnail_url?}
    (CLI 1.1.26 z --wait --json drukuje liste takich obiektow; bez --wait - liste UUID-ow jako stringi)."""
    args = ["generate", "create", jst] + _flagi(params, media)
    if wait:
        args += ["--wait", "--wait-timeout", wait_timeout, "--wait-interval", wait_interval]
    dane = _uruchom(args, timeout=TIMEOUT_GENERACJA)
    if isinstance(dane, list):
        dane = dane[0] if dane else {}
    if isinstance(dane, str):
        # bez --wait: sam identyfikator joba
        return {"id": dane, "status": "queued"}
    return dane if isinstance(dane, dict) else {"surowe": dane}


def job(job_id):
    dane = _uruchom(["generate", "get", str(job_id)])
    if isinstance(dane, list):
        dane = dane[0] if dane else {}
    return dane


def doczytaj_url(job_obj, proby=5, odstep=8):
    """Job 'completed', ale result_url == null (CLI widzi tylko result_url/min_result_url, a backend czasem
    dopisuje link chwile po zakonczeniu). Odpytuje `generate get <id>` kilka razy. Zwraca (job, urls)."""
    urls = wyniki_url(job_obj)
    jid = job_id_z(job_obj)
    if urls or not jid or not job_udany(job_obj):
        return job_obj, urls
    for i in range(proby):
        time.sleep(odstep * (i + 1))
        try:
            swiezy = job(jid)
        except HiggsfieldBlad:
            continue
        if isinstance(swiezy, dict) and swiezy:
            job_obj = swiezy
            urls = wyniki_url(job_obj)
            if urls or job_nieudany(job_obj):
                break
    return job_obj, urls


def czekaj(job_id, timeout="30m", interval="5s"):
    dane = _uruchom(
        ["generate", "wait", str(job_id), "--timeout", timeout, "--interval", interval, "--quiet"],
        timeout=TIMEOUT_GENERACJA,
    )
    if isinstance(dane, list):
        dane = dane[0] if dane else {}
    return dane


def job_id_z(job_obj):
    if not isinstance(job_obj, dict):
        return None
    for k in ("id", "job_id", "job_set_id"):
        if job_obj.get(k):
            return str(job_obj[k])
    return None


def status_joba(job_obj):
    """Status joba (lowercase). API zwraca `job_status` albo `status`, czasem tylko w jobs[0]."""
    if not isinstance(job_obj, dict):
        return None
    for k in ("job_status", "status", "state"):
        if job_obj.get(k):
            return str(job_obj[k]).lower()
    for k in ("data", "job", "job_set"):
        w = status_joba(job_obj.get(k))
        if w:
            return w
    jobs = job_obj.get("jobs")
    if isinstance(jobs, list) and jobs:
        return status_joba(jobs[0])
    return None


# Statusy jobow w CLI 1.1.26: queued, pending, in_progress, completed, failed, nsfw, ip_detected, canceled
STATUSY_OK = ("completed", "succeeded", "success", "done", "finished")
STATUSY_BLAD = ("failed", "error", "cancelled", "canceled", "rejected", "nsfw", "ip_detected", "moderated")
STATUSY_W_TOKU = ("queued", "pending", "in_progress", "processing", "running")


def job_udany(job_obj):
    return (status_joba(job_obj) or "") in STATUSY_OK


def job_nieudany(job_obj):
    return (status_joba(job_obj) or "") in STATUSY_BLAD


def blad_joba(job_obj):
    """Powod bledu z obiektu joba (fail_reason / error / detail), albo ''."""
    if not isinstance(job_obj, dict):
        return ""
    for k in ("fail_reason", "error", "detail", "message", "reason"):
        v = job_obj.get(k)
        if isinstance(v, str) and v.strip():
            typ = job_obj.get("fail_reason_type")
            return f"{typ}: {v.strip()}" if isinstance(typ, str) and typ else v.strip()
        if isinstance(v, dict):
            w = blad_joba(v)
            if w:
                return w
    jobs = job_obj.get("jobs")
    if isinstance(jobs, list):
        for j in jobs:
            w = blad_joba(j)
            if w:
                return w
    return ""


_WZORZEC_URL = re.compile(
    r"https?://[^\s\"']+\.(?:mp4|mov|webm|png|jpg|jpeg|webp|gif|mp3|wav|glb)(?:\?[^\s\"']*)?",
    re.I,
)

# Poddrzewa JSON-a joba, w ktorych siedza WEJSCIA (nasze referencje, filmik zrodlowy) - nie wyniki.
_KLUCZE_WEJSCIA = ("input", "inputs", "params", "request", "references", "image_references", "video_references",
                   "audio_references", "media_inputs", "start_image", "end_image", "source", "prompt")
# Klucze z linkami, ktore nigdy nie sa wynikiem (miniatury, podglady, upload).
_KLUCZE_SMIECI = ("thumbnail", "preview", "avatar", "upload_url", "example", "icon", "logo")
# Priorytet klucza z linkiem: nizszy = pewniejszy wynik.
_PRIORYTET_KLUCZA = {
    "result_url": 0, "video_url": 0, "image_url": 0, "audio_url": 0, "output_url": 0,
    "url": 1, "urls": 1, "image_urls": 1, "video_urls": 1,
    "min_result_url": 3, "video_s3_url": 4, "s3_url": 4,
}


def wyniki_url(job_obj):
    """Linki do plikow wynikowych joba, najpewniejszy pierwszy.

    Odporne na ksztalt JSON-a: results.raw.url / result_url / jobs[].results[] / urls[].
    Pomija poddrzewa z wejsciami (zeby nie zwrocic naszego filmiku zrodlowego) i miniatury.
    """
    kandydaci = []      # (priorytet, kolejnosc, url)
    wejsciowe = set()   # linki z wejsc - wykluczamy je z wynikow

    def _wejscie(o):
        if isinstance(o, dict):
            for v in o.values():
                _wejscie(v)
        elif isinstance(o, list):
            for v in o:
                _wejscie(v)
        elif isinstance(o, str) and o.startswith("http"):
            wejsciowe.add(o)

    def _zbierz(o, klucz=None, rodzic=None):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = str(k).lower()
                if kl in _KLUCZE_WEJSCIA:
                    _wejscie(v)
                    continue
                if any(sm in kl for sm in _KLUCZE_SMIECI):
                    continue
                _zbierz(v, kl, klucz)
        elif isinstance(o, list):
            for v in o:
                _zbierz(v, klucz, rodzic)
        elif isinstance(o, str) and o.startswith("http"):
            if klucz is None:
                return
            prio = _PRIORYTET_KLUCZA.get(klucz)
            if prio is None:
                if not _WZORZEC_URL.match(o):
                    return
                prio = 2
            if klucz == "url" and rodzic == "min":
                prio = 3
            elif klucz == "url" and rodzic == "raw":
                prio = 0
            elif prio == 1 and _WZORZEC_URL.match(o):
                prio = 1
            elif prio == 1:
                prio = 2
            kandydaci.append((prio, len(kandydaci), o))

    _zbierz(job_obj)
    widziane, wynik = set(), []
    for prio, _, u in sorted(kandydaci):
        if u in widziane or u in wejsciowe:
            continue
        widziane.add(u)
        wynik.append(u)
    return wynik


def pobierz(url, sciezka):
    os.makedirs(os.path.dirname(os.path.abspath(sciezka)), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "rolki-ai/1.0"})
    with urllib.request.urlopen(req, timeout=600) as odp, open(sciezka, "wb") as f:
        shutil.copyfileobj(odp, f)
    return sciezka


# ---------------- upload (zeby nie slac tych samych referencji przy kazdym jobie) ----------------

def upload(plik):
    """Wgrywa plik, zwraca {"id", "type", "url"}. UUID mozna podac zamiast sciezki w media flagach."""
    dane = _uruchom(["upload", "create", os.path.abspath(plik)], timeout=TIMEOUT_UPLOAD)
    if not isinstance(dane, dict) or not dane.get("id"):
        raise HiggsfieldBlad(f"upload create nie zwrocil id: {dane}")
    return dane


# ---------------- glosy (text-to-speech / voice-change) ----------------

def glosy():
    """Lista glosow: id -> --voice-id, Voice Type (preset/element) -> --voice-type."""
    dane = _uruchom(["voices", "list"])
    if isinstance(dane, dict):
        for k in ("items", "voices", "data"):
            if isinstance(dane.get(k), list):
                return dane[k]
    return dane if isinstance(dane, list) else []


def joby(typ=None, ile=20):
    """Ostatnie joby (--video/--image/--audio)."""
    args = ["generate", "list", "--size", str(ile)]
    if typ in ("image", "video", "audio", "text"):
        args.append(f"--{typ}")
    dane = _uruchom(args)
    if isinstance(dane, dict):
        for k in ("items", "jobs", "data"):
            if isinstance(dane.get(k), list):
                return dane[k]
    return dane if isinstance(dane, list) else []


# ---------------- Soul ID ----------------

def soul_lista():
    return _uruchom(["soul-id", "list"])


def soul_utworz(nazwa, zdjecia, cinematic=False):
    args = ["soul-id", "create", "--name", nazwa, "--soul-cinematic" if cinematic else "--soul-2"]
    for z in zdjecia:
        args += ["--image", os.path.abspath(z)]
    return _uruchom(args, timeout=TIMEOUT_UPLOAD)


def soul_czekaj(soul_id):
    return _uruchom(["soul-id", "wait", str(soul_id)], timeout=TIMEOUT_GENERACJA)


if __name__ == "__main__":
    # Szybki test: python higgsfield_cli.py
    if sys.platform == "win32":
        sys.stdout.reconfigure(errors="replace")
    try:
        print("CLI:", sciezka_cli())
        k = konto()
        print("Konto:", json.dumps(k, ensure_ascii=False)[:400])
        print("Kredyty:", _wyciagnij_kredyty(k))
    except HiggsfieldBlad as e:
        print("[BLAD]", e)
