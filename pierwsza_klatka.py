# -*- coding: utf-8 -*-
"""pierwsza_klatka.py - 3.5: "pierwsza klatka" (start frame) rolek z promptu.

Feedback usera po rolce #7 Noemi (Seedance t2v, sklepik pod blokiem): kamera za blisko (~2 m, wypelnia kadr, statycznie), wnetrze
wymyslone zamiast prawdziwego polskiego sklepu, napisy polamane ("OTVORNE", "KAVA", ceny "19.99"). Dlatego rolka z promptu robi
sie w DWOCH krokach:

  1) klatka startowa = ZDJECIE z modelu obrazu, ktory dobrze pisze tekst (domyslnie GPT Image 2.5, high, 2K, 9:16): persona daleko
     (6-10 m, ok. 1/4-1/3 wysokosci kadru), zaslonieta pierwszym planem, prawdziwe polskie realia miejsca i napisy po polsku (ceny
     z przecinkiem), bez marek. Prompt buduje scenariusz.prompt_klatki() (czysta funkcja). Gdy user wrzucil wlasne zdjecia miejsca
     do Pulpit\\ROLKI AI\\tla\\<id miejsca>\\, jedno z nich (kopia bez EXIF/GPS) jest obrazem 1, a model tylko WSTAWIA w nie persone.
     Opcjonalna kontrola klatki darmowym modelem wizyjnym OpenRouter (wzor instagram_rolki.py) -> {ok, powod}; zla = nowa klatka,
     max `max_dodatkowych` (2) dodatkowe proby, kazda platna (~3 kr) i liczona w budzecie. Bez klucza OpenRouter - bez kontroli.
  2) wideo (fabryka._rolka) = Seedance 2.5 omni_reference + start_image (klatka) + image_references (zdjecia persony - tozsamosc).
     Wan 3.0 Prime / Gemini: start_image NIE laczy sie z referencjami (regula `model get`), wiec (3.5.2, platny test #9 "w ogole
     nie podobna") tryb "tlo": krok 1 robi ZDJECIE SAMEGO MIEJSCA bez persony (scenariusz.prompt_tla, bez zdjec, plik
     NNN_<nazwa>.tlo.png; zdjecie usera z tla/<miejsce> = gotowe tlo, 0 kr), krok 2 = image_references: zdjecia persony (+ stroj)
     + tlo jako OSTATNI obraz, bez start_image. Kontrola AI tla: osobne pytanie (PYTANIE_TLA - brak bohaterki, ludzie w tle ok).

Pieniadze jak wszedzie: znacznik w_toku (faza "klatka") PRZED wyslaniem, wszystko wgrane przed 'wysylam' (pierwszy obraz swiezym
uploadem = obraz_id do odnalezienia joba na `generate list --image`), create bez --wait, job_id zapisany od razu, NIGDY drugi
create po 'wysylam' (blad = szukamy joba, nie ma = czekamy 60 min, potem "sprawdz w apce"), cena jeszcze raz przed KAZDYM
wyslaniem (wyzsza niz zatwierdzona = nic nie idzie), limit dzienny z rezerwa (klatka + wideo), min_kredyty. Klatka gotowa, a
wideo przerwane = wznowienie bierze TE SAMA klatke (p["klatka"]["plik"]), nie robi nowej.

Stan w pomysle: z_promptu.klatka = zamrozona konfiguracja (model, parametry, prompt, obrazy, tlo, kontrola, max_dodatkowych,
mode_wideo, refy_w_wideo, wycena); p["klatka"] = {plik, ok, powod, zrodlo, zaakceptowana, kr, proby: [{nr, job_id, status, kr,
plik, ok, powod, zrodlo, czas}]}.
"""
import base64
import io
import os
import re
import time

import baza
import dostawcy
import sekrety

# modele obrazu na klatke (wszystkie przez CLI Higgsfield; ceny `generate cost` 2026-10-08, 9:16 2K):
#   gpt_image_2_5 high 2,75 kr | nano_banana_pro 2 kr | gpt_image_2 high 6,5 kr | seedream_v5_pro 2,5 kr
MODELE = {
    "gpt_image_2_5": {"nazwa": "GPT Image 2.5", "opis": "najlepiej pisze tekst (polecany), ok. 2,75 kr",
                      "parametry": {"aspect_ratio": "9:16", "resolution": "2k", "quality": "high"}},
    "nano_banana_pro": {"nazwa": "Nano Banana Pro", "opis": "dobra twarz, do 14 zdjęć, ok. 2 kr",
                        "parametry": {"aspect_ratio": "9:16", "resolution": "2k"}},
    "gpt_image_2": {"nazwa": "GPT Image 2", "opis": "ten z apki Higgsfield, ok. 6,5 kr",
                    "parametry": {"aspect_ratio": "9:16", "resolution": "2k", "quality": "high"}},
    "seedream_v5_pro": {"nazwa": "Seedream 5.0 Pro", "opis": "najwierniejsza twarz, do 10 zdjęć, ok. 2,5 kr",
                        "parametry": {"aspect_ratio": "9:16", "resolution": "2k"}},
}
MODEL_DOMYSLNY = "gpt_image_2_5"
MAX_DODATKOWYCH = 2                 # tyle NOWYCH klatek po odrzuceniu przez kontrole (kazda platna ~3 kr)
MAX_ZAPASOWYCH_NSFW = 2             # 3.5.1: tyle innych modeli klatki po odrzuceniu przez filtr tresci (NSFW = 0 kr)
FOLDER_TEL = "tla"                  # Pulpit\ROLKI AI\tla\<id miejsca>\ - prawdziwe zdjecia miejsc od usera
CZAS_NA_KLATKE = "15m"
DLUGI_BOK_OCENY = 1280              # klatka do modelu wizyjnego: JPEG, dluzszy bok max (2K PNG to kilka MB base64)

SYSTEM_OCENY = ("You check the first frame of a hidden-camera phone video before an expensive video is generated from it. "
                "Answer in Polish.")
PYTANIE_OCENY = (
    "To pierwsza klatka nagrania telefonem z ukrycia, z której zrobimy wideo. Oceń ją. DOBRA klatka: (1) młoda kobieta jest "
    "DALEKO od aparatu – mała postać, zajmuje najwyżej ok. 1/3 wysokości kadru; to NIE jest zbliżenie, plan średni ani portret; "
    "(2) jest dokładnie JEDNA wyraźna postać tej kobiety (nie dwie takie same); (3) napisy, które da się przeczytać, są poprawnym "
    "polskim (bez bełkotu, literówek i wymyślonych słów), ceny z przecinkiem jak „4,99 zł” – drobne, nieczytelne z daleka napisy "
    "są w porządku; (4) wygląda jak zwykłe zdjęcie z telefonu, nie jak sesja zdjęciowa ani reklama; (5) kobieta NIE jest "
    "wyższa od mężczyzn obok i ma normalne, codzienne proporcje (nie jak modelka, nogi nie wydłużone), a jej skala pasuje do "
    "ludzi, drzwi i lad. "
    'Odpowiedz TYLKO obiektem JSON: {"ok": true/false, "powod": "krótko po polsku, max 100 znaków"}.'
)
# 3.5.2: kontrola zdjecia SAMEGO miejsca (tryb tla, Wan/Gemini) - bohaterki ma NIE byc, ludzie w tle sa w porzadku
SYSTEM_OCENY_TLA = ("You check a background photo (only the place, before the main person is added) used as a reference for an "
                    "expensive hidden-camera phone video. Answer in Polish.")
PYTANIE_TLA = (
    "To zdjęcie samego miejsca (tło), z którego zrobimy wideo z ukrycia – bohaterkę dodamy dopiero w wideo. Oceń je. DOBRE tło: "
    "(1) wygląda jak prawdziwe miejsce w Polsce (polskie realia, nie wymyślone wnętrze ani render); (2) NIE ma na nim głównej "
    "bohaterki – nikt nie stoi na pierwszym planie ani w centrum uwagi, nikt nie pozuje i nie jest wyeksponowany; zwykli ludzie "
    "w tle, przy bokach albo za ladą są w porządku; (3) napisy, które da się przeczytać, są poprawnym polskim (bez bełkotu, "
    "literówek i wymyślonych słów), ceny z przecinkiem jak „4,99 zł” – drobne, nieczytelne z daleka napisy są w porządku; "
    "(4) wygląda jak zwykłe zdjęcie z telefonu, nie jak sesja zdjęciowa ani reklama; (5) ludzie mają normalne proporcje i "
    "prawdziwą skalę względem drzwi, lad i półek (nikt nie jest nienaturalnie wysoki ani wyciągnięty). "
    'Odpowiedz TYLKO obiektem JSON: {"ok": true/false, "powod": "krótko po polsku, max 100 znaków"}.'
)


class NieWyszla(Exception):
    """Klatka nie powstala / odrzucona / bezpiecznik - rolka konczy sie bledem, wideo NIE idzie (0 kr na wideo).
    powod: nsfw | ip | klatka | inny (pomysl.powod)."""

    def __init__(self, tekst, powod="inny", job_id=None, status=""):
        super().__init__(tekst)
        self.tekst, self.powod, self.job_id, self.status = tekst, powod, job_id, status


class WrocDoKolejki(Exception):
    """Wysylanie klatki przerwane, zanim cokolwiek poszlo - rolka wraca do 'nowy' (nic nie zeszlo)."""


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _zdarzenie(log, slug, typ, tekst, **dane):
    (log or _log)(tekst)
    try:
        baza.dziennik_zapisz(typ, tekst, modelka=slug, **dane)
    except OSError:
        pass


# ---------------- ustawienia, modele, tla ----------------

def ustawienia():
    """Ustawienia globalne `pierwsza_klatka` (panel: Ustawienia -> Autopilot -> Rolki z promptu - pierwsza klatka):
    {wlaczona, model, kontrola, max_dodatkowych} - sprawdzone wartosci."""
    u = dict(baza.ustawienia_globalne().get("pierwsza_klatka") or {})
    dom = baza.USTAWIENIA_GLOBALNE_DOMYSLNE["pierwsza_klatka"]
    try:
        dod = max(0, min(MAX_DODATKOWYCH, int(u.get("max_dodatkowych", dom["max_dodatkowych"]))))
    except (TypeError, ValueError):
        dod = dom["max_dodatkowych"]
    zapas = u.get("zapas_nsfw", dom["zapas_nsfw"])
    zapas = [m for m in dict.fromkeys(zapas) if m in MODELE] if isinstance(zapas, list) else list(dom["zapas_nsfw"])
    return {"wlaczona": bool(u.get("wlaczona", dom["wlaczona"])),
            "model": u.get("model") if u.get("model") in MODELE else dom["model"],
            "kontrola": bool(u.get("kontrola", dom["kontrola"])), "max_dodatkowych": dod, "zapas_nsfw": zapas}


def sprawdz_ustawienia(v):
    """Zmiany z panelu -> sprawdzone wartosci (ValueError po polsku)."""
    if not isinstance(v, dict):
        raise ValueError("pierwsza_klatka musi byc slownikiem.")
    wynik = {}
    for k, x in v.items():
        if k in ("wlaczona", "kontrola"):
            wynik[k] = bool(x) if not isinstance(x, str) else x.strip().lower() in ("1", "true", "tak", "wl", "on")
        elif k == "model":
            if x not in MODELE:
                raise ValueError(f"Model pierwszej klatki: {', '.join(MODELE)}.")
            wynik[k] = x
        elif k == "max_dodatkowych":
            try:
                n = int(x)
            except (TypeError, ValueError):
                raise ValueError("Ile dodatkowych klatek: liczba 0-2.")
            if not 0 <= n <= MAX_DODATKOWYCH:
                raise ValueError(f"Ile dodatkowych klatek: od 0 do {MAX_DODATKOWYCH}.")
            wynik[k] = n
        elif k == "zapas_nsfw":
            lista = [s.strip() for s in x.split(",") if s.strip()] if isinstance(x, str) else x
            if not isinstance(lista, list) or any(m not in MODELE for m in lista):
                raise ValueError(f"Zapas po NSFW klatki: lista modeli z {', '.join(MODELE)}.")
            wynik[k] = list(dict.fromkeys(lista))
        else:
            raise ValueError(f"Nieznane ustawienie pierwsza_klatka.{k}.")
    return wynik


def max_obrazow(model):
    """Ile zdjec przyjmuje model klatki (z reguly schematu jak w swapie; None = bez limitu w schemacie)."""
    import zdjecia_swap
    if model in zdjecia_swap.MODELE:
        return zdjecia_swap.chipy(zdjecia_swap.schemat(model))["max_obrazow"]
    return None


def folder_tel():
    """Pulpit\\ROLKI AI\\tla - prawdziwe zdjecia miejsc od usera (zdjecia telefonem), podfolder = id miejsca."""
    return os.path.join(baza.pulpit(), FOLDER_TEL)


def tla_miejsca(miejsce_id):
    """Zdjecia usera dla miejsca (Pulpit\\ROLKI AI\\tla\\<id miejsca>\\*.jpg|png|webp), posortowane. Brak = []."""
    folder = os.path.join(folder_tel(), str(miejsce_id or ""))
    if not miejsce_id or not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
            if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU) and os.path.isfile(os.path.join(folder, n))]


def przygotuj_foldery_tel():
    """Start panelu: Pulpit\\ROLKI AI\\tla\\<id miejsca>\\ dla kazdego miejsca z katalogu (user widzi, gdzie wrzucac zdjecia).
    Zwraca sciezke folderu tla. Bledy (brak praw) nie wywalaja."""
    import scenariusz
    root = folder_tel()
    try:
        os.makedirs(root, exist_ok=True)
        for mid in scenariusz.MIEJSCA:
            os.makedirs(os.path.join(root, mid), exist_ok=True)
    except OSError:
        pass
    return root


def stan_tel():
    """Dla panelu: {folder, miejsca: {id: liczba zdjec}} (tylko miejsca, gdzie cos lezy)."""
    import scenariusz
    return {"folder": folder_tel(), "miejsca": {mid: len(tla_miejsca(mid)) for mid in scenariusz.MIEJSCA if tla_miejsca(mid)}}


def kopia_tla(slug, tlo):
    """Zdjecie usera -> kopia obrocona wg EXIF, BEZ metadanych (GPS z telefonu nie leci do Higgsfielda), dluzszy bok max 3072:
    modelki/<slug>/tla_kopie/<czas>_<nazwa>.jpg. ValueError = to nie jest zdjecie."""
    import zdjecia_swap
    folder = os.path.join(baza.folder_modelki(slug), "tla_kopie")
    os.makedirs(folder, exist_ok=True)
    return zdjecia_swap.zapisz_zrodlo(slug, tlo, folder=folder)


# ---------------- stan klatki w pomysle ----------------

def konfiguracja(p):
    zp = (p or {}).get("z_promptu") or {}
    return zp.get("klatka") if isinstance(zp.get("klatka"), dict) else None


def stan(p):
    return dict(p.get("klatka")) if isinstance((p or {}).get("klatka"), dict) else {}


def tryb_tla(kl):
    """3.5.2: konfiguracja klatki w trybie "tlo" (Wan/Gemini): zdjecie SAMEGO miejsca jako ostatnia referencja wideo."""
    return isinstance(kl, dict) and kl.get("tryb") == "tlo"


def co_to(kl):
    """Nazwa kroku do dziennika: 'zdjecie tla' (tryb tla) albo 'pierwsza klatka'."""
    return "zdjecie tla" if tryb_tla(kl) else "pierwsza klatka"


def gotowa(p):
    """Sciezka klatki, ktora moze isc do wideo (przeszla kontrole, bez kontroli albo user ja zaakceptowal) - albo None.
    3.5.2: w trybie tla zdjecie usera z tla/<miejsce> (kopia bez EXIF) jest gotowym tlem - nic do generowania (0 kr)."""
    st = stan(p)
    plik = st.get("plik")
    if plik and os.path.isfile(plik) and (st.get("ok") is not False or st.get("zaakceptowana")):
        return plik
    kl = konfiguracja(p)
    if tryb_tla(kl) and kl.get("tlo") and os.path.isfile(kl["tlo"]):
        return kl["tlo"]
    return None


def potrzebna(p):
    """Rolka ma pierwsza klatke w konfiguracji, a gotowej klatki jeszcze nie ma (trzeba ja zrobic - i zaplacic)."""
    return bool(konfiguracja(p)) and not gotowa(p)


def cena(kl, swieza=False):
    """Cena jednej klatki (ulamkowa, np. 2.75) z `generate cost` (0 kr, bez mediow, cache 1 h jak swap)."""
    import zdjecia_swap
    return zdjecia_swap.cena(kl["model"], kl["parametry"], swieza=swieza)


def do_limitu(k):
    import zdjecia_swap
    return zdjecia_swap.do_limitu(k)


def wycena_rolki(p, k_wideo, swieza=False):
    """(kr razem do zatwierdzenia = wideo + klatka w gore, kr klatki (ulamek) albo None, ile max z dodatkowymi klatkami).
    Klatka gotowa / brak klatki w konfiguracji = sama cena wideo."""
    kl = konfiguracja(p)
    if not kl or not potrzebna(p) or k_wideo is None:
        return k_wideo, None, k_wideo
    k = cena(kl, swieza=swieza)
    if k is None:
        return None, None, None
    jedna = do_limitu(k)
    dodatkowe = int(kl.get("max_dodatkowych") or 0) if kl.get("kontrola") and sekrety.klucz("openrouter") else 0
    return k_wideo + jedna, k, k_wideo + jedna * (1 + dodatkowe)


def _plik_klatki(slug, p, nr, url):
    """NNN_<nazwa>.klatka.png - albo (3.5.2, tryb tla) NNN_<nazwa>.tlo.png; kolejne proby z -2, -3."""
    import fabryka
    rozsz = os.path.splitext(str(url or "").split("?")[0])[1].lower()
    if rozsz == ".jpeg":
        rozsz = ".jpg"
    if rozsz not in (".png", ".jpg", ".webp"):
        rozsz = ".png"
    dopisek = "" if nr <= 1 else f"-{nr}"
    rodzaj = "tlo" if tryb_tla(konfiguracja(p)) else "klatka"
    return os.path.join(baza.folder_wynikow(slug), f"{int(p['id']):03d}_{fabryka._nazwa_wyniku(p)}.{rodzaj}{dopisek}{rozsz}")


def _zapisz_stan(slug, pid, **pola):
    with baza._rmw(baza._plik_pomyslow(slug)):
        p = baza.pomysl(slug, pid)
        st = stan(p)
        st.update(pola)
        return baza.aktualizuj_pomysl(slug, pid, klatka=st)


def _dopisz_probe(slug, pid, wpis):
    with baza._rmw(baza._plik_pomyslow(slug)):
        p = baza.pomysl(slug, pid)
        st = stan(p)
        proby = list(st.get("proby") or [])
        wpis = dict(wpis, czas=baza._teraz())
        for i, w in enumerate(proby):
            if wpis.get("job_id") and w.get("job_id") == wpis["job_id"]:
                proby[i] = {**w, **wpis}
                break
        else:
            proby.append(wpis)
        st["proby"] = proby
        st["kr"] = sum(int(x.get("kr") or 0) for x in proby)
        return baza.aktualizuj_pomysl(slug, pid, klatka=st)


def akceptuj(slug, pid):
    """User: "Zrob wideo z tej klatki" - klatka odrzucona przez kontrole idzie jednak do wideo. Rolka wraca do 'nowy'."""
    p = baza.pomysl(slug, pid)
    st = stan(p)
    if p.get("status") == "w_toku":
        raise ValueError("Ta rolka jeszcze sie robi.")
    if not st.get("plik") or not os.path.isfile(st["plik"]):
        raise ValueError("Ta rolka nie ma klatki do uzycia.")
    st.update(zaakceptowana=True)
    p = baza.aktualizuj_pomysl(slug, pid, klatka=st, status="nowy" if p.get("status") == "blad" else p.get("status"),
                               notatki="" if p.get("status") == "blad" else p.get("notatki"))
    baza.dziennik_zapisz("info", f"#{pid}: pierwsza klatka zaakceptowana recznie ({os.path.basename(st['plik'])}) - wideo ruszy "
                         f"od niej", modelka=slug, pomysl=pid)
    return p


def wyczysc_odrzucona(slug, pid):
    """'Sprobuj jeszcze raz' rolki, ktorej klatka nie przeszla kontroli albo (3.5.1) filtr tresci odrzucil ja we wszystkich
    modelach: nastepnym razem nowe klatki od wybranego modelu (stare pliki zostaja)."""
    p = baza.pomysl(slug, pid)
    st = stan(p)
    filtr = not st.get("plik") and bool(_odrzucone_filtrem(st)) if st else False
    if st and ((st.get("ok") is False and not st.get("zaakceptowana")) or filtr):
        st.update(plik=None, ok=None, powod="", proby_poprzednie=(st.get("proby_poprzednie") or []) + (st.get("proby") or []),
                  proby=[], kr=0)
        baza.aktualizuj_pomysl(slug, pid, klatka=st)


# ---------------- kontrola klatki (darmowy model wizyjny OpenRouter) ----------------

def _jpg_data_url(plik):
    from PIL import Image
    with Image.open(plik) as im:
        im = im.convert("RGB")
        im.thumbnail((DLUGI_BOK_OCENY, DLUGI_BOK_OCENY))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _zapytaj_vision(model, data_url, pytanie=None):
    """Jedno zapytanie do OpenRouter -> {"ok", "powod"} (seam do podmiany w testach). Wzor: instagram_rolki._zapytaj_vision.
    pytanie = PYTANIE_TLA (3.5.2, zdjecie samego miejsca) albo None = pytanie o pierwsza klatke."""
    import instagram_rolki as ig
    tla = pytanie == PYTANIE_TLA
    odp = ig._http_json("POST", ig.LLM_API + "/chat/completions", {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_OCENY_TLA if tla else SYSTEM_OCENY},
                     {"role": "user", "content": [{"type": "text", "text": pytanie or PYTANIE_OCENY},
                                                  {"type": "image_url", "image_url": {"url": data_url}}]}],
        "temperature": 0.1, "max_tokens": ig.MAX_TOKENOW_VISION})
    if isinstance(odp, dict) and odp.get("error"):
        raise RuntimeError(f"OpenRouter: {str((odp['error'] or {}).get('message', odp['error']))[:200]}")
    try:
        tresc = odp["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("dziwna odpowiedz z OpenRouter")
    w = ig._json_z_tekstu(tresc)
    if not isinstance(w, dict) or "ok" not in w:
        raise ValueError("odpowiedz bez pola ok")
    return {"ok": bool(w["ok"]), "powod": str(w.get("powod") or "")[:200]}


def ocen(plik, log=None, tlo=False):
    """Kontrola klatki: ({"ok", "powod", "zrodlo"}, "") albo (None, czemu bez kontroli) - brak klucza OpenRouter, blad AI, plik
    nie do otwarcia. 0 kr (darmowe modele). tlo=True (3.5.2): zdjecie SAMEGO miejsca - prawdziwe polskie miejsce, napisy po
    polsku, BRAK glownej bohaterki (ludzie w tle ok), ujecie z telefonu."""
    if not sekrety.klucz("openrouter"):
        return None, "brak klucza OpenRouter (Ustawienia -> Konta)"
    try:
        data_url = _jpg_data_url(plik)
    except Exception as e:          # PIL rzuca rozne wyjatki
        return None, f"nie umiem otworzyc klatki ({e})"
    import instagram_rolki as ig
    # 3.5.1: ta sama dynamiczna lista darmowych modeli wizyjnych co filtr rolek z IG (404 "unavailable for free" = nastepny)
    zapytaj = (lambda m, d: _zapytaj_vision(m, d, PYTANIE_TLA)) if tlo else (lambda m, d: _zapytaj_vision(m, d))
    w, bledy = ig.ocen_vision(zapytaj, data_url, log=log)
    if w is None:
        return None, "AI niedostepne (" + bledy[:200] + ")"
    return w, ""


# ---------------- generacja klatki (znacznik w_toku faza "klatka", job_id od razu, wznawianie) ----------------

def _zlecenie(slug, kl):
    par = dict(kl.get("parametry") or {})
    obrazy = [o for o in (kl.get("obrazy") or []) if o]
    return {"slug": slug, "prompt": kl["prompt"], "video": None, "images": obrazy, "obraz_swiezy": obrazy[0] if obrazy else None,
            "duration": None, "aspect_ratio": par.pop("aspect_ratio", "9:16"), "resolution": par.pop("resolution", None),
            "model": kl["model"], "mode": None, "generate_audio": None, "soul_id": "", "parametry": par, "dostawca": "higgsfield"}


def _bezpieczniki(slug, d, kl_lim, k_wideo):
    """Przed KAZDA klatka: limit dnia (wydane + rezerwy w toku + ta klatka + wideo) i saldo - rezerwy - klatka - wideo >= min."""
    import fabryka
    ust = baza.ustawienia_modelki(slug)
    min_k, _max = fabryka.bezpiecznik(ust, "higgsfield")
    limit = baza.limit_dzienny("higgsfield")
    wydano = baza.wydano_z_rezerwa("higgsfield")
    if limit and wydano + kl_lim + k_wideo > limit:
        return (f"dzis wydano {wydano} z {limit} kr - klatka ({kl_lim} kr) i wideo ({k_wideo} kr) przekroczylyby dzienny limit")
    try:
        saldo = d.saldo()
    except dostawcy.BladDostawcy as e:
        return f"nie moge sprawdzic salda Higgsfield ({e})"
    if saldo is not None:
        rezerwa = baza.koszt_w_toku("higgsfield")
        if saldo - rezerwa - kl_lim - k_wideo < min_k:
            return f"po klatce i wideo zostaloby {saldo - rezerwa - kl_lim - k_wideo} kr, a minimum to {min_k} kr"
    return None


def _wyslij(slug, pid, d, kl, nr, k_wideo, log):
    """Wysyla JEDNA klatke: swieza cena (wyzsza niz zatwierdzona = nic), bezpieczniki, znacznik w_toku faza 'klatka' PRZED
    wyslaniem, create bez --wait, job_id zapisany od razu. Zwraca (job, kl_lim). Rzuca NieWyszla / fabryka.JobTrwa."""
    import fabryka
    brak = [os.path.basename(o) for o in kl.get("obrazy") or [] if not os.path.isfile(o)]
    if brak:
        raise NieWyszla(f"pierwsza klatka: brakuje zdjec ({', '.join(brak)}) - zrob rolke jeszcze raz w 'Z promptu'")
    try:
        k = cena(kl, swieza=True)
    except dostawcy.BladDostawcy as e:
        raise NieWyszla(f"pierwsza klatka: Higgsfield nie podal ceny ({e}) - nic nie wyslalem")
    if k is None:
        raise NieWyszla("pierwsza klatka: Higgsfield nie podal ceny - nic nie wyslalem")
    if kl.get("wycena") is not None and float(k) > float(kl["wycena"]) + 1e-9:
        raise NieWyszla(f"cena klatki wzrosla z {kl['wycena']} do {k} kr - nic nie wyslalem (0 kr)")
    kl_lim = do_limitu(k)
    powod = _bezpieczniki(slug, d, kl_lim, k_wideo)
    if powod:
        raise NieWyszla(f"pierwsza klatka nr {nr} nie poszla: {powod} (0 kr)")
    baza.zacznij_w_toku(slug, pid, faza="klatka", dostawca=d.NAZWA, model=kl["model"], koszt=kl_lim + int(k_wideo or 0),
                        koszt_klatki=kl_lim, klucz=f"klatka-{slug}-{pid}-{nr}", nr=nr)

    def znacznik(**pola):
        if pola.get("wysylam"):
            pola.setdefault("wysylam_od", fabryka._teraz_iso())
        baza.ustaw_w_toku(slug, pid, **pola)
    with fabryka._WYSYLANIE_LOCK:
        fabryka._WYSYLANIE.add((slug, pid))
    try:
        try:
            job, blad = d.zlec(_zlecenie(slug, kl), znacznik=znacznik, log=log), None
        except dostawcy.BladDostawcy as e:
            job, blad = None, e
        if job is None:
            powod_odrz = fabryka.powod_odrzucenia("", str(blad))
            marker = baza.pomysl(slug, pid).get("w_toku") or {}
            if powod_odrz in fabryka.POWODY_ZAPASU:
                raise NieWyszla(f"pierwsza klatka odrzucona przez filtr Higgsfield ({powod_odrz}): {blad}", powod_odrz)
            if marker.get("wysylam") and not fabryka._blad_trwaly(blad):
                job = _szukaj(slug, pid, d, marker, blad, log, prompt=kl.get("prompt"))
            else:
                raise NieWyszla(f"pierwsza klatka nie poszla ({str(blad)[:200]}) - nic nie zeszlo")
        baza.ustaw_w_toku(slug, pid, job_id=job["job_id"], etap="czeka", wyslano=fabryka._teraz_iso())
        _zdarzenie(log, slug, "info", f"#{pid}: {co_to(kl)} nr {nr} {'wyslane' if tryb_tla(kl) else 'wyslana'} ({MODELE.get(kl['model'], {}).get('nazwa', kl['model'])}, "
                   f"~{k} kr), job {job['job_id']}", pomysl=pid)
        return job, kl_lim
    finally:
        with fabryka._WYSYLANIE_LOCK:
            fabryka._WYSYLANIE.discard((slug, pid))


def _znajdz_job(d, marker, prompt=None):
    """Job klatki z przerwanego wysylania: po obraz_id (swiezo wgrany 1. obraz) albo - 3.5.2, zdjecie tla bez zadnych zdjec - po
    prompcie i czasie na liscie jobow obrazu, z pominieciem jobow znanych fabryce. None = nie widac. Rzuca BladDostawcy."""
    if marker.get("obraz_id"):
        return d.znajdz(marker.get("model") or "", obraz_id=marker["obraz_id"])
    if prompt:
        return d.znajdz(marker.get("model") or "", prompt=prompt, od=marker.get("wysylam_od") or marker.get("od"),
                        pomin=baza.znane_job_id(d.NAZWA), typ="image")
    return None


def _szukaj(slug, pid, d, marker, blad, log, prompt=None):
    """Create zwrocil blad po 'wysylam' - job MOGL powstac: szukamy go po obraz_id albo prompcie (po 5 s i 15 s). Nie ma ->
    JobTrwa (NIGDY drugie wysylanie)."""
    import fabryka
    for pauza in (5, 15):
        time.sleep(pauza)
        try:
            znaleziony = _znajdz_job(d, marker, prompt)
        except dostawcy.BladDostawcy as e:
            log(f"#{pid}: nie moge sprawdzic listy jobow ({e})")
            break
        if znaleziony:
            _zdarzenie(log, slug, "info", f"#{pid}: job klatki {znaleziony['job_id']} jednak powstal - czekam na niego", pomysl=pid)
            return znaleziony
    _zdarzenie(log, slug, "uwaga", f"#{pid}: wysylanie klatki zwrocilo blad ({str(blad)[:200]}), a joba nie widac na liscie - NIE "
               f"wysylam drugi raz; sprawdzam przy kolejnych przebiegach przez {fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S // 60} min",
               pomysl=pid)
    raise fabryka.JobTrwa("nie wiadomo, czy job klatki powstal")


def _wznow(slug, pid, d, marker, log, prompt=None):
    """Znacznik faza 'klatka' sprzed restartu/STOP/limitu czasu: TEN job (albo szukanie go). Zwraca (gotowy job | None, job_id).
    Rzuca WrocDoKolejki (nic nie poszlo), fabryka.JobTrwa (czekamy dalej), NieWyszla (niepewne po 60 min - 'sprawdz w apce').
    prompt (3.5.2): zdjecie tla bez zadnych zdjec nie ma obraz_id - szukamy joba po prompcie."""
    import fabryka
    jid = marker.get("job_id")
    kl_lim = int(marker.get("koszt_klatki") or 0)
    if jid:
        _zdarzenie(log, slug, "info", f"#{pid}: wznawiam pierwsza klatke - job {jid} byl juz wyslany (bez wysylania nowego)", pomysl=pid)
        wiek = fabryka._wiek_s(marker.get("od"))
        if wiek is not None and wiek > fabryka.MAX_GODZIN_W_TOKU * 3600:
            try:
                teraz = d.sprawdz(jid)
            except dostawcy.BladDostawcy:
                teraz = {"job_id": jid, "status": ""}
            if not d.koncowy(teraz.get("status") or ""):
                if kl_lim:
                    baza.dopisz_wydatek(kl_lim, d.NAZWA, job_id=jid)      # job byl wyslany - na wszelki wypadek (raz na job)
                raise NieWyszla(f"job klatki {jid} nie skonczyl sie w {fabryka.MAX_GODZIN_W_TOKU} h - {fabryka.sprawdz_w_apce()} "
                                f"Wideo NIE poszlo.", job_id=jid)
            return teraz, jid
        return None, jid
    if not marker.get("wysylam"):
        baza.aktualizuj_pomysl(slug, pid, status="nowy", w_toku=None)
        _zdarzenie(log, slug, "info", f"#{pid}: wysylanie klatki nie zaczelo sie przed przerwaniem - rolka wraca do kolejki (0 kr)",
                   pomysl=pid)
        raise WrocDoKolejki()
    wiek = fabryka._wiek_s(marker.get("wysylam_od") or marker.get("od"))
    try:
        znaleziony = _znajdz_job(d, marker, prompt)
    except dostawcy.BladDostawcy as e:
        if wiek is not None and wiek > fabryka.MAX_GODZIN_W_TOKU * 3600:
            _niepewne(slug, pid, marker, f"od {fabryka.MAX_GODZIN_W_TOKU} h nie da sie sprawdzic listy jobow: {e}")
        log(f"#{pid}: nie moge sprawdzic, czy przerwane wysylanie klatki utworzylo job ({e}) - sprobuje pozniej, nic nie wysylam")
        raise fabryka.JobTrwa("lista jobow niedostepna")
    if not znaleziony:
        if wiek is None or wiek < fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S:
            log(f"#{pid}: wysylanie klatki przerwane {int(wiek or 0)} s temu, joba nie widac - czekam, nic nie wysylam drugi raz")
            raise fabryka.JobTrwa("job klatki jeszcze niewidoczny")
        _niepewne(slug, pid, marker, f"po {fabryka.OKNO_NIEPEWNEGO_WYSLANIA_S // 60} min joba klatki dalej nie widac na liscie")
    jid = znaleziony["job_id"]
    baza.ustaw_w_toku(slug, pid, job_id=jid, etap="czeka")
    _zdarzenie(log, slug, "info", f"#{pid}: odnaleziony job klatki {jid} z przerwanego wysylania - czekam na niego", pomysl=pid)
    return (znaleziony if d.koncowy(znaleziony.get("status") or "") else None), jid


def _niepewne(slug, pid, marker, przyczyna):
    import fabryka
    k = int(marker.get("koszt_klatki") or 0)
    if k:
        baza.dopisz_wydatek(k, "higgsfield", job_id=f"niepewne:{marker.get('klucz') or pid}")
    raise NieWyszla(f"Wysylanie pierwszej klatki przerwane ({przyczyna}) - nie wiadomo, czy powstala. {fabryka.sprawdz_w_apce()}"
                    + (f" {k} kr wliczone do dzisiejszego limitu na wszelki wypadek." if k else "") + " Wideo NIE poszlo.")


def _rozlicz(slug, pid, d, w, kl_lim, model, log):
    kr = int(d.koszt_joba(w, kl_lim) or 0)
    jid = w.get("job_id")
    if kr:
        juz = baza.rozliczony(jid, d.NAZWA)
        wydano = baza.dopisz_wydatek(kr, d.NAZWA, job_id=jid)
        if not juz:
            baza.dziennik_zapisz("kredyty", f"#{pid}: {kr} kr (pierwsza klatka, {model}), dzis {wydano}/{baza.limit_dzienny(d.NAZWA)}",
                                 modelka=slug, pomysl=pid, kredyty=kr, dostawca=d.NAZWA)
    return kr


# ---------------- 3.5.1: zapas po odrzuceniu klatki przez filtr tresci (NSFW, 0 kr) ----------------

def lancuch_modeli(kl):
    """Kolejnosc modeli klatki, gdy filtr tresci (NSFW) ja odrzuci: wybrany -> ustawienie zapas_nsfw (domyslnie Seedream 5.0 Pro,
    Nano Banana Pro) bez powtarzania wybranego, max MAX_ZAPASOWYCH_NSFW zapasowe."""
    zapas = [m for m in dict.fromkeys(ustawienia()["zapas_nsfw"]) if m != kl["model"] and m in MODELE]
    return [kl["model"]] + zapas[:MAX_ZAPASOWYCH_NSFW]


def _wariant(kl, model):
    """Konfiguracja klatki dla innego modelu (zapas po NSFW): ten sam prompt i zdjecia, parametry tego modelu."""
    if model == kl["model"] or model not in MODELE:
        return kl
    return dict(kl, model=model, nazwa_modelu=MODELE[model]["nazwa"], parametry=dict(MODELE[model]["parametry"]),
                zapas_po_nsfw=True)


def _nazwa(model):
    return MODELE.get(model, {}).get("nazwa", model)


def _odrzucone_filtrem(st):
    """Modele, ktorych klatke odrzucil filtr tresci w tej rundzie (proby z 'filtr': 'nsfw')."""
    return [x.get("model") for x in st.get("proby") or [] if x.get("filtr") == "nsfw"]


def _proby_kontroli(st):
    """Klatki, ktore licza sie do limitu kontroli AI (1 + max_dodatkowych) - bez odrzuconych przez filtr tresci (0 kr)."""
    return [x for x in st.get("proby") or [] if x.get("job_id") and not x.get("filtr")]


def _zapas(kl, model):
    """Czy model z zapasu moze zrobic te klatke: zdjecia sie mieszcza, cena (`generate cost`, 0 kr) nie wyzsza niz zatwierdzona
    klatka (w gore do pelnych kr). Zwraca (wariant z wycena, "") albo (None, czemu nie)."""
    maks = max_obrazow(model)
    n = len([o for o in kl.get("obrazy") or [] if o])
    if maks and n > maks:
        return None, f"przyjmuje max {maks} zdjec, a klatka ma {n}"
    w = _wariant(kl, model)
    try:
        k = cena(w, swieza=True)
    except dostawcy.BladDostawcy as e:
        return None, f"Higgsfield nie podal ceny ({e})"
    if k is None:
        return None, "Higgsfield nie podal ceny"
    if kl.get("wycena") is not None and do_limitu(k) > do_limitu(kl["wycena"]):
        return None, f"kosztuje {k} kr, a zatwierdzona klatka {kl['wycena']} kr"
    w["wycena"] = k
    return w, ""


def _model_do_proby(slug, pid, kl, st, log):
    """Konfiguracja na nastepna klatke: wybrany model, a gdy filtr go odrzucil - pierwszy uzyteczny z zapasu (bez powtorek).
    None = nic nie zostalo."""
    odrz = set(_odrzucone_filtrem(st))
    if kl["model"] not in odrz:
        return kl
    for m in lancuch_modeli(kl)[1:]:
        if m in odrz:
            continue
        w, czemu = _zapas(kl, m)
        if w:
            return w
        _zdarzenie(log, slug, "uwaga", f"#{pid}: zapas klatki {_nazwa(m)} pominiety - {czemu}", pomysl=pid)
    return None


def _po_filtrze(slug, pid, kl, kl_akt, st, blad, log):
    """Filtr tresci odrzucil klatke modelu kl_akt (0 kr). Asystent zapamietuje odrzucenie (stroj -> nsfw), a gdy jest zapas -
    wpis "klatka odrzucona przez filtr X - probuje Y" i konfiguracja nastepnej klatki. None = bez zapasu (rolka -> blad nsfw)."""
    try:
        import asystent
        asystent.zapisz_odrzucenie(slug, baza.pomysl(slug, pid), "nsfw", zrodlo=f"klatka:{kl_akt['model']}")
    except Exception as e:          # nauka asystenta nie moze zatrzymac rolki
        (log or _log)(f"#{pid}: asystent nie zapisal odrzucenia klatki ({e})")
    nastepny = _model_do_proby(slug, pid, kl, st, log)
    if nastepny is None:
        return None
    _zdarzenie(log, slug, "uwaga", f"#{pid}: klatka odrzucona przez filtr {_nazwa(kl_akt['model'])} (NSFW, 0 kr) - probuje "
               f"{_nazwa(nastepny['model'])} (~{nastepny.get('wycena')} kr)", pomysl=pid, powod="nsfw")
    return nastepny


def przygotuj(slug, pid, log=None, stop=None, timeout=CZAS_NA_KLATKE, k_wideo=0):
    """Klatka dla rolki #pid: gotowa -> od razu; znacznik faza 'klatka' -> dokoncz TEN job; inaczej nowa (cena i bezpieczniki
    przed kazda). Kontrola AI (gdy wlaczona i jest klucz OpenRouter): zla = nowa klatka, max `max_dodatkowych` dodatkowych.
    3.5.1: filtr tresci (NSFW, 0 kr) odrzucil klatke -> od razu kolejny model z `lancuch_modeli` (max 2 zapasowe, bez powtorek);
    w budzecie liczy sie tylko to, co przeszlo. Zwraca sciezke klatki. Rzuca NieWyszla (rolka -> blad, wideo NIE idzie),
    WrocDoKolejki, fabryka.JobTrwa (zostaje w toku), fabryka.Przerwano (STOP)."""
    import fabryka
    log = log or _log
    p = baza.pomysl(slug, pid)
    kl = konfiguracja(p)
    if not kl:
        raise NieWyszla("rolka nie ma konfiguracji pierwszej klatki")
    plik = gotowa(p)
    if plik:
        return plik
    d = dostawcy.dostawca("higgsfield")
    marker = p.get("w_toku") if p.get("status") == "w_toku" and (p.get("w_toku") or {}).get("faza") == "klatka" else None
    max_dod = int(kl.get("max_dodatkowych") or 0) if kl.get("kontrola") else 0
    nastepny = None
    while True:
        fabryka._sprawdz_stop(stop)
        st = stan(baza.pomysl(slug, pid))
        if marker:
            kl_akt = _wariant(kl, marker.get("model") or kl["model"])      # wznowienie: TEN job (takze klatki z zapasu)
            gotowy_job, jid = _wznow(slug, pid, d, marker, log, prompt=kl_akt.get("prompt"))
            kl_lim = int(marker.get("koszt_klatki") or 0) or do_limitu(kl_akt.get("wycena") or 0)
            nr = int(marker.get("nr") or len(st.get("proby") or []) + 1)
            marker = None
        else:
            kl_akt = nastepny or _model_do_proby(slug, pid, kl, st, log)
            nastepny = None
            if kl_akt is None:
                raise NieWyszla(f"pierwsza klatka odrzucona przez filtr tresci (NSFW) we wszystkich modelach ("
                                f"{', '.join(_nazwa(m) for m in dict.fromkeys(_odrzucone_filtrem(st)))}) - wideo NIE poszlo, "
                                f"0 kr", "nsfw")
            nr = len(st.get("proby") or []) + 1
            if len(_proby_kontroli(st)) + 1 > 1 + max_dod:
                raise NieWyszla(f"pierwsza klatka: wykorzystane {len(_proby_kontroli(st))} proby", "klatka")
            try:
                job, kl_lim = _wyslij(slug, pid, d, kl_akt, nr, k_wideo, log)
            except NieWyszla as e:
                if e.powod != "nsfw":
                    raise
                # filtr odrzucil juz przy wysylaniu (job nie powstal, 0 kr) -> zapas, gdy jest
                _dopisz_probe(slug, pid, {"nr": nr, "job_id": None, "status": "nsfw", "kr": 0, "plik": None, "ok": False,
                                          "powod": e.tekst[:200], "model": kl_akt["model"], "filtr": "nsfw"})
                nastepny = _po_filtrze(slug, pid, kl, kl_akt, stan(baza.pomysl(slug, pid)), e.tekst, log)
                if nastepny is None:
                    raise
                continue
            jid, gotowy_job = job["job_id"], job.get("gotowy")
        w = fabryka._czekaj(slug, pid, d, jid, timeout, log, stop, gotowy=gotowy_job)      # JobTrwa / Przerwano -> w toku
        kr = _rozlicz(slug, pid, d, w, kl_lim, kl_akt["model"], log)
        status = w.get("status") or ""
        if not d.udany(status) or not w.get("urls"):
            powod = fabryka.powod_odrzucenia(status, w.get("blad")) or "inny"
            wpis = {"nr": nr, "job_id": jid, "status": status, "kr": kr, "plik": None, "ok": False,
                    "powod": (w.get("blad") or status)[:200], "model": kl_akt["model"]}
            if powod == "nsfw":
                wpis["filtr"] = "nsfw"
            _dopisz_probe(slug, pid, wpis)
            if powod == "nsfw":
                nastepny = _po_filtrze(slug, pid, kl, kl_akt, stan(baza.pomysl(slug, pid)), w.get("blad"), log)
                if nastepny is not None:
                    continue
            co = {"nsfw": "odrzucona przez filtr tresci (NSFW)", "ip": "odrzucona - model wykryl znana marke/postac (IP)"}.get(
                powod, f"nie wyszla (status {status or '?'}{', bez URL' if d.udany(status) else ''})")
            modele = list(dict.fromkeys(_odrzucone_filtrem(stan(baza.pomysl(slug, pid))))) if powod == "nsfw" else []
            gdzie = f" w {len(modele)} modelach ({', '.join(_nazwa(m) for m in modele)})" if len(modele) > 1 else ""
            raise NieWyszla(f"{co_to(kl)}: {co}{gdzie} - wideo NIE poszlo, nic nie wysylam drugi raz. {w.get('blad') or ''}".strip(),
                            powod, job_id=jid, status=status)
        cel = _plik_klatki(slug, baza.pomysl(slug, pid), nr, w["urls"][0])
        try:
            d.pobierz(w["urls"][0], cel)
        except Exception as e:
            # job zaplacony - zostaje w toku: nastepny przebieg pobierze go jeszcze raz (bez nowego joba, rozliczenie raz na job)
            _zdarzenie(log, slug, "blad", f"#{pid}: pobranie klatki nie wyszlo ({e}) - sprobuje przy nastepnym przebiegu", pomysl=pid)
            raise fabryka.JobTrwa("pobranie klatki")
        baza.aktualizuj_pomysl(slug, pid, job_id=None)         # job klatki rozliczony; job_id pomyslu dostanie wideo
        if (baza.pomysl(slug, pid).get("w_toku") or {}).get("faza") == "klatka":
            baza.ustaw_w_toku(slug, pid, koszt=int(k_wideo or 0))   # klatka juz w wydatkach - w rezerwie zostaje tylko wideo
        if kl.get("kontrola"):
            ocena, czemu = ocen(cel, log, tlo=tryb_tla(kl))
        else:
            ocena, czemu = None, "kontrola wylaczona w ustawieniach"
        wpis = {"nr": nr, "job_id": jid, "status": status, "kr": kr, "plik": cel, "ok": (ocena or {}).get("ok"),
                "powod": (ocena or {}).get("powod") or "", "zrodlo": (ocena or {}).get("zrodlo") or "", "model": kl_akt["model"]}
        _dopisz_probe(slug, pid, wpis)
        z_zapasu = "" if kl_akt["model"] == kl["model"] else f", zapas {_nazwa(kl_akt['model'])}"
        if ocena is None:
            _zdarzenie(log, slug, "info", f"#{pid}: {'zdjecie tla gotowe' if tryb_tla(kl) else 'pierwsza klatka gotowa'} ({os.path.basename(cel)}, {kr} kr{z_zapasu}) - bez "
                       f"kontroli AI: {czemu}", pomysl=pid)
            _zapisz_stan(slug, pid, plik=cel, ok=None, powod="", zrodlo="bez kontroli: " + czemu, model=kl_akt["model"])
            return cel
        if ocena["ok"]:
            _zdarzenie(log, slug, "ok", f"#{pid}: {co_to(kl)} OK ({os.path.basename(cel)}, {kr} kr{z_zapasu}; kontrola: "
                       f"{ocena['powod'] or 'w porzadku'})", pomysl=pid)
            _zapisz_stan(slug, pid, plik=cel, ok=True, powod=ocena["powod"], zrodlo=ocena["zrodlo"], model=kl_akt["model"])
            return cel
        _zapisz_stan(slug, pid, plik=cel, ok=False, powod=ocena["powod"], zrodlo=ocena["zrodlo"], model=kl_akt["model"])
        zrobione = len(_proby_kontroli(stan(baza.pomysl(slug, pid))))
        if zrobione >= 1 + max_dod:
            raise NieWyszla(f"kontrola odrzucila {'zdjecie tla' if tryb_tla(kl) else 'pierwsza klatke'} {zrobione}x (ostatnio: {ocena['powod'] or 'bez powodu'}) - wideo "
                            f"NIE poszlo (0 kr na wideo). Zobacz klatke; 'Zrob wideo z tej klatki' albo 'Sprobuj jeszcze raz'.",
                            "klatka", job_id=jid, status=status)
        _zdarzenie(log, slug, "uwaga", f"#{pid}: kontrola odrzucila {'zdjecie tla' if tryb_tla(kl) else 'klatke'} nr {nr} ({ocena['powod'] or 'bez powodu'}) - robie nowa "
                   f"(proba {zrobione + 1} z {1 + max_dod})", pomysl=pid)
        if kl_akt is not kl:
            nastepny = kl_akt           # nastepna klatka tym samym modelem z zapasu (wybrany odpadl na filtrze)
