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
    wyniki_url(job)         -> [url, ...]
    pobierz(url, sciezka)   -> sciezka
"""
import json
import os
import re
import shutil
import subprocess
import sys
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
                "CLI Higgsfield nie ma wybranego workspace (zwykle = niezalogowane). "
                "Odpal: higgsfield auth login, a przy kilku workspace'ach: higgsfield workspace list"
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
    args = ["model", "list"]
    if typ in ("image", "video", "audio", "text"):
        args.append(f"--{typ}")
    return _uruchom(args)


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
    """Tworzy job. Z wait=True blokuje do konca i zwraca obiekt joba z URL-ami wyniku."""
    args = ["generate", "create", jst] + _flagi(params, media)
    if wait:
        args += ["--wait", "--wait-timeout", wait_timeout, "--wait-interval", wait_interval]
    dane = _uruchom(args, timeout=TIMEOUT_GENERACJA)
    if isinstance(dane, list):
        dane = dane[0] if dane else {}
    return dane if isinstance(dane, dict) else {"surowe": dane}


def job(job_id):
    dane = _uruchom(["generate", "get", str(job_id)])
    if isinstance(dane, list):
        dane = dane[0] if dane else {}
    return dane


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
    if not isinstance(job_obj, dict):
        return None
    for k in ("status", "state"):
        if job_obj.get(k):
            return str(job_obj[k]).lower()
    return None


_WZORZEC_URL = re.compile(
    r"https?://[^\s\"']+\.(?:mp4|mov|webm|png|jpg|jpeg|webp|gif|mp3|wav|glb)(?:\?[^\s\"']*)?",
    re.I,
)


def wyniki_url(job_obj):
    """Wyciaga URL-e plikow wynikowych z obiektu joba (odporne na ksztalt JSON-a)."""
    urls = []

    def zbierz(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and v.startswith("http") and (
                    k in ("url", "video_url", "image_url", "result_url", "raw", "min")
                    or _WZORZEC_URL.match(v)
                ):
                    urls.append(v)
                else:
                    zbierz(v)
        elif isinstance(o, list):
            for v in o:
                zbierz(v)
        elif isinstance(o, str) and o.startswith("http") and _WZORZEC_URL.match(o):
            urls.append(o)

    zbierz(job_obj)
    widziane, wynik = set(), []
    for u in urls:
        if u not in widziane:
            widziane.add(u)
            wynik.append(u)
    return wynik


def pobierz(url, sciezka):
    os.makedirs(os.path.dirname(os.path.abspath(sciezka)), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "rolki-ai/1.0"})
    with urllib.request.urlopen(req, timeout=600) as odp, open(sciezka, "wb") as f:
        shutil.copyfileobj(odp, f)
    return sciezka


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
