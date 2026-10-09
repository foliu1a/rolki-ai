# -*- coding: utf-8 -*-
"""asystent.py - "Agent AI w tle" zakladki Z promptu (feedback usera 2026-10-07).

User pisze krotko po polsku, co ma sie dziac (albo "Losuj"), a asystent SAM dobiera reszte: miejsce (prawdziwa galeria/dworzec/
dzielnica), stroj ze wspolnej biblioteki strojow (3.1: ulubione czesciej, rotacja bez powtorek; pusta biblioteka = odwazny stroj na
pore roku), kamere z ukrycia, reakcje zdziwienia ludzi, komentarz zza kamery (forma pod osobe nagrywajaca: chlopak/dziewczyna),
wlosy, dlugosc i model - i tlumaczy wybor jednym zdaniem. Uczy sie z tego, co wyszlo:
  * ocena usera na karcie rolki ("Dobra" / "Slaba"; usuniecie gotowej rolki = slaba - app.py dopisuje ja do archiwum),
  * odrzucenia filtrow: NSFW -> unika tego stroju, IP -> unika tego obiektu (a przy powtorce: nazw w ogole, `nazwy: "opisowe"`),
  * gotowa rolka bez oceny = lekki plus.
Wszystko liczone z pomysly.json (+ modelki/<slug>/asystent_archiwum.json dla usunietych) - zero osobnej bazy do pilnowania.
3.6: uwagi usera do ocen ("Co wyszlo zle?") w asystent_uwagi.json obok stan.json -> REGULY_UWAG (stale poprawki promptu, panel
"Asystent pamieta") + ostatnie uwagi w prompcie LLM; ton komentarzy persony (ostre domyslnie / lagodne).

Mozg: DARMOWY model z OpenRouter (klucz w panelu: Ustawienia -> Konta -> OpenRouter; user nie zrobi weryfikacji dowodem do
Anthropic). Jedno male zapytanie (~1,5 tys. tokenow), JSON na wyjsciu, kazde pole sprawdzane z katalogiem scenariusz.py.
Brak klucza / blad / zly JSON / limit darmowych modeli = REGULY (dobierz_regulami) - funkcja dziala zawsze, tez offline.
Nic tu nie wydaje kredytow: asystent tylko wypelnia opcje; cene liczy potem darmowa wycena, a rolka idzie dopiero po "Zrob rolke".
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

import baza
import scenariusz as sc
import sekrety

LLM_API = "https://openrouter.ai/api/v1"
# darmowe modele OpenRouter (te same co w tg-glosowki, zmierzone 2026-09-24: pierwsze odpowiadaly w 3-5 s); openrouter/free na
# koncu sam szuka wolnego modelu. Znikajace modele odfiltrowuje GET /models (cache 1 h).
MODELE_LLM = [
    "nex-agi/nex-n2.5-mini:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "z-ai/glm-5.2:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "openrouter/free",
]
TIMEOUT_LLM_S = 25
MAX_PROB_LLM = 3
_cache_modeli = {"czas": 0.0, "modele": None}

PLIK_ARCHIWUM = "asystent_archiwum.json"
OCENY = ("dobra", "slaba")

# miejsca "z ludzmi, ktorzy moga zareagowac" - gdy pomysl nie mowi gdzie (kolejnosc nie ma znaczenia, wagi daje nauka)
MIEJSCA_REAKCJI = ("galeria_foodcourt", "galeria_pasaz", "dyskont", "sklep_osiedlowy", "drogeria", "przystanek", "tramwaj", "metro",
                   "dworzec", "przejscie_dla_pieszych", "nowy_swiat", "piotrkowska", "rynek_krakow", "plac_zamkowy", "bulwary",
                   "piekarnia", "poczta", "stacja_paliw", "rynek_wroclaw", "krupowki")
# reakcje zdziwienia pasujace do typu miejsca (pierwsza = najbardziej naturalna)
_SKLEPY_Z_KASA = ("dyskont", "sklep_osiedlowy", "drogeria", "stacja_paliw", "piekarnia", "kebab", "poczta")
_KOMUNIKACJA = ("przystanek", "tramwaj", "metro", "dworzec", "peron", "pociag", "przejscie_podziemne", "przejscie_dla_pieszych")
_OSIEDLE = ("osiedle", "klatka", "silownia_plenerowa", "orlik", "dzialki")


def reakcje_dla_miejsca(miejsce_id):
    if miejsce_id in _SKLEPY_Z_KASA:
        return ["kasjerka_zamiera", "szepcze_patrzac", "dwa_razy", "para_kreci_glowa"]
    if miejsce_id in ("galeria_foodcourt", "galeria_pasaz"):
        return ["para_kreci_glowa", "dwa_razy", "szepcze_patrzac", "szturcha_kolege", "mama_odciaga"]
    if miejsce_id in _KOMUNIKACJA:
        return ["para_kreci_glowa", "szturcha_kolege", "dwa_razy", "szepcze_patrzac"]
    if miejsce_id in _OSIEDLE:
        return ["para_kreci_glowa", "mama_odciaga", "szturcha_kolege"]
    return ["dwa_razy", "mama_odciaga", "para_kreci_glowa", "szturcha_kolege", "szepcze_patrzac"]


# ---------------- nauka: co wyszlo, co nie ----------------

def _plik_archiwum(slug):
    return os.path.join(baza.folder_modelki(slug), PLIK_ARCHIWUM)


def _wybory_pomyslu(p):
    """Wybory rolki z promptu, z ktorych asystent sie uczy (z zamrozonego z_promptu)."""
    zp = p.get("z_promptu") if isinstance(p.get("z_promptu"), dict) else {}
    u = zp.get("ustalone") or {}
    return {"miejsce": zp.get("miejsce"), "obiekt": zp.get("obiekt") or u.get("obiekt"), "nazwy": zp.get("nazwy") or "opisowe",
            "stroj": zp.get("stroj_id") or u.get("stroj_id"), "kamera": zp.get("kamera"), "reakcja": zp.get("reakcja"),
            "model": zp.get("model"), "glos": zp.get("glos")}


def _wynik_pomyslu(p):
    ocena = p.get("ocena")
    if ocena in OCENY:
        return ocena
    if p.get("status") == "blad":
        return p.get("powod") if p.get("powod") in ("nsfw", "ip") else "blad"
    if p.get("status") in ("gotowe", "wygenerowany", "postprodukcja"):
        return "gotowe"
    return "czeka"


def archiwizuj_usuniety(slug, p):
    """Usunieta rolka z promptu zostaje w nauce (app.py wola to przy DELETE). Gotowa bez oceny = 'slaba' (user ja wyrzucil)."""
    if not (isinstance(p, dict) and p.get("typ") == "prompt"):
        return
    wynik = _wynik_pomyslu(p)
    if wynik in ("gotowe", "czeka"):
        wynik = "slaba" if wynik == "gotowe" else None
    if not wynik:
        return
    plik = _plik_archiwum(slug)
    with baza._rmw(plik):
        dane = baza._wczytaj_json(plik, {"wyniki": []})
        dane.setdefault("wyniki", []).append({"pid": p.get("id"), "czas": baza._teraz(), "wybory": _wybory_pomyslu(p),
                                              "wynik": wynik})
        dane["wyniki"] = dane["wyniki"][-300:]
        baza._zapisz_json(plik, dane)


def zapisz_odrzucenie(slug, p, wynik="nsfw", zrodlo=""):
    """3.5.1: filtr odrzucil KROK rolki (np. pierwsza klatke), a rolka idzie dalej zapasem (inny model klatki) - asystent i tak
    zapamietuje odrzucenie tych wyborow (stroj -> nsfw), jak przy rolce zakonczonej bledem nsfw. Wpis w archiwum nauki."""
    if not (isinstance(p, dict) and p.get("typ") == "prompt") or wynik not in ("nsfw", "ip"):
        return
    plik = _plik_archiwum(slug)
    with baza._rmw(plik):
        dane = baza._wczytaj_json(plik, {"wyniki": []})
        dane.setdefault("wyniki", []).append({"pid": p.get("id"), "czas": baza._teraz(), "wybory": _wybory_pomyslu(p),
                                              "wynik": wynik, "zrodlo": zrodlo})
        dane["wyniki"] = dane["wyniki"][-300:]
        baza._zapisz_json(plik, dane)


def historia(slug):
    """[{wybory, wynik}] rolek z promptu persony (z kolejki + archiwum usunietych)."""
    wpisy = [{"wybory": _wybory_pomyslu(p), "wynik": _wynik_pomyslu(p), "pid": p.get("id")}
             for p in baza.lista_pomyslow(slug) if p.get("typ") == "prompt"]
    arch = baza._wczytaj_json(_plik_archiwum(slug), {"wyniki": []})
    return wpisy + [w for w in arch.get("wyniki") or [] if isinstance(w, dict)]


PUNKTY = {"dobra": 3, "gotowe": 1, "slaba": -3}


# ---------------- 3.6: uwagi usera do ocenionych rolek ("Co wyszlo zle?" / "Co bylo dobre?") ----------------
# Plik asystent_uwagi.json obok stan.json (wspolny dla person, poza gitem): kazda uwaga = ocena + tekst usera + wybory rolki.
# Reguly bez LLM rozpoznaja typowe uwagi po slowach (PL, z ogonkami i bez) -> STALE poprawki promptu (scenariusz.POPRAWKI_PROMPTU,
# zdanie o wzroscie, miks glosu/otoczenia w komentarz_glos). Nieznane uwagi ida tylko do LLM (ostatnie ~10 w jego prompcie).
# Zakres "persona" (wzrost, twarz) = tylko persona z uwagi; "wszystkie" = kazda rolka z promptu. Panel: "Asystent pamieta"
# (Z promptu) - lista aktywnych poprawek i uwag z przyciskiem Usun.
PLIK_UWAG = "asystent_uwagi.json"
MAX_UWAG_LLM = 10
REGULY_UWAG = [   # (klucz, nazwa PL do panelu, zakres, wzorzec na tekscie bez ogonkow, co robi)
    ("dystans", "Kamera dalej od niej", "wszystkie",
     r"za blisk|\bblisko|zbliz|wypelnia|za duza w kadrze|caly kadr|portret",
     "prompt wideo i zdjęcia: ona 8–12 m od telefonu, mała postać, nigdy zbliżenie"),
    ("wzrost", "Mocniej pilnuje wzrostu", "persona",
     r"za wysok|\bwysok|tyczk|olbrzym|gigant|dlugie nogi|za dlug\w* nog|wyzsza od|za duza od",
     "prompt wideo i zdjęcia: nigdy wyższa od mężczyzn obok, zwykłe proporcje"),
    ("tozsamosc", "Mocniej trzyma twarz", "persona",
     r"nie\s*(?:jest\s+)?podobn|niepodobn|nie ona\b|\btwarz|inna osoba|inna dziewczyn|nie przypomina|nie jej twarz",
     "prompt wideo i zdjęcia: twarz dokładnie jak na zdjęciach persony"),
    ("napisy", "Mniej i mniejsze napisy", "wszystkie",
     r"napis|literk|\blitery|szyld|belkot|krzaki",
     "prompt wideo i zdjęcia: najwyżej 1–2 małe napisy, reszta za daleko do czytania"),
    ("glos", "Bardziej surowy głos (jak z telefonu)", "wszystkie",
     r"\bglos(?:u|em|ie|y|ik)?\b|studyj|lektor|radiow|jak z radia|jak w reklamie",
     "miks komentarza: niższy bitrate, więcej pokoju, głos ledwo nad otoczeniem"),
    ("kroki", "Ciszej jej kroki i buty", "wszystkie",
     r"\bkrok|\bbut(?:y|ow|ami)?\b|obcas|stuka|stukot|tupot|tupie|\bglosn",
     "prompt dźwięku + miks: jej kroki prawie niesłyszalne, mocniejsze ujarzmienie pików otoczenia"),
    ("tlo", "Więcej polskich realiów w tle", "wszystkie",
     r"\btl[oaeu]\b|nierealn|wymyslon|nie\s*polsk|jak w grze|render|sztuczn\w* (?:tl|miejsc|sklep)|jak z ameryki",
     "prompt wideo i zdjęcia: zwykłe, trochę zużyte polskie miejsce, nie salon ani render"),
]
REGULY_PO_KLUCZU = {r[0]: r for r in REGULY_UWAG}
# po slowie-kluczu stoi pochwala ("twarz ok", "glos super") = to nie skarga
_POCHWALA_PO = re.compile(r"^\W*(?:\w+\W+)?(?:ok|okej|dobr\w*|super|spoko|idealn\w*|git|fajn\w*|swietn\w*|w porzadku|bomba|"
                          r"zajebi\w*|sztos|perfekt\w*|piekn\w*)\b")
# przy ocenie "Dobra" reguly dzialaja tylko, gdy tekst brzmi jak skarga ("dobra, ale za wysoka")
_SKARGA = re.compile(r"\b(?:ale|za|nie|zle|zly|zla|slab\w*|popraw\w*|gorzej|minus|szkoda|brakuje)\b")


def _plik_uwag():
    return os.path.join(os.path.dirname(baza.PLIK_STANU), PLIK_UWAG)


def _norm(tekst):
    return re.sub(r"\s+", " ", sc._bez_ogonkow(tekst or "").lower()).strip()


def rozpoznaj_uwage(tekst, ocena="slaba"):
    """Klucze poprawek z tekstu uwagi (reguly bez LLM, PL z ogonkami i bez). Przy 'dobra' tylko, gdy tekst brzmi jak skarga."""
    t = _norm(tekst)
    if not t or (ocena == "dobra" and not _SKARGA.search(t)):
        return []
    wynik = []
    o_glosie = re.search(REGULY_PO_KLUCZU["glos"][3], t)
    for klucz, _, _, wzorzec, _ in REGULY_UWAG:
        for m in re.finditer(wzorzec, t):
            if _POCHWALA_PO.match(t[m.end():m.end() + 25]):
                continue
            if klucz == "kroki" and m.group(0).startswith("glosn") and o_glosie:
                continue            # "glos za glosny" = o komentarzu, nie o krokach
            wynik.append(klucz)
            break
    return wynik


def _wczytaj_uwagi():
    dane = baza._wczytaj_json(_plik_uwag(), {"uwagi": []}) or {}
    return [u for u in (dane.get("uwagi") or []) if isinstance(u, dict)]


def zapisz_uwage(slug, p, ocena, tekst):
    """Uwaga usera do ocenionej rolki (zastepuje wczesniejsza uwage tej rolki). Zwraca wpis."""
    wyb = _wybory_pomyslu(p)
    zp = p.get("z_promptu") if isinstance(p.get("z_promptu"), dict) else {}
    try:
        imie = baza.profil_modelki(slug).get("nazwa") or slug
    except (OSError, ValueError):
        imie = slug
    wpis = {"id": f"u{int(time.time() * 1000)}-{p.get('id')}", "persona": slug, "persona_nazwa": imie, "pid": p.get("id"),
            "ocena": ocena, "tekst": tekst, "data": baza._teraz(), "poprawki": rozpoznaj_uwage(tekst, ocena),
            "model": wyb.get("model"), "miejsce": wyb.get("miejsce"), "stroj": wyb.get("stroj"), "kamera": wyb.get("kamera"),
            "reakcja": wyb.get("reakcja"), "komentarz": zp.get("komentarz") or "",
            "tekst_usera": ((zp.get("opcje") or {}).get("tekst") or p.get("opis") or "")[:200]}
    plik = _plik_uwag()
    with baza._rmw(plik):
        dane = baza._wczytaj_json(plik, {"uwagi": []}) or {}
        uwagi = [u for u in (dane.get("uwagi") or []) if isinstance(u, dict)
                 and not (u.get("persona") == slug and u.get("pid") == p.get("id") and not u.get("usunieta"))]
        uwagi.append(wpis)
        dane["uwagi"] = uwagi[-300:]
        baza._zapisz_json(plik, dane)
    return wpis


def usun_uwagi_rolki(slug, pid):
    """Cofnieta ocena / ocena bez tekstu = uwaga tej rolki znika (z regul i z LLM)."""
    plik = _plik_uwag()
    if not os.path.isfile(plik):
        return
    with baza._rmw(plik):
        dane = baza._wczytaj_json(plik, {"uwagi": []}) or {}
        dane["uwagi"] = [u for u in (dane.get("uwagi") or []) if isinstance(u, dict)
                         and not (u.get("persona") == slug and u.get("pid") == pid)]
        baza._zapisz_json(plik, dane)


def uwagi_aktywne():
    """Uwagi, ktorych user nie usunal (najstarsze pierwsze)."""
    return [u for u in _wczytaj_uwagi() if not u.get("usunieta")]


def poprawki_dla(slug):
    """Klucze aktywnych poprawek dla rolek persony: zakres 'wszystkie' z uwag o kazdej personie, 'persona' tylko z jej uwag."""
    wynik = set()
    for u in uwagi_aktywne():
        for k in u.get("poprawki") or []:
            r = REGULY_PO_KLUCZU.get(k)
            if r and (r[2] == "wszystkie" or u.get("persona") == slug):
                wynik.add(k)
    return [r[0] for r in REGULY_UWAG if r[0] in wynik]


def pamiec(slug=None):
    """Panel "Asystent pamieta": aktywne poprawki (z uwag, z ktorych wynikaja) + ostatnie uwagi (to czyta tez LLM)."""
    uwagi = uwagi_aktywne()
    poprawki = []
    for klucz, nazwa, zakres, _, efekt in REGULY_UWAG:
        zrodla = [u for u in uwagi if klucz in (u.get("poprawki") or [])]
        if not zrodla:
            continue
        persony = sorted({u.get("persona_nazwa") or u.get("persona") or "" for u in zrodla})
        dotyczy = (slug is None or zakres == "wszystkie" or any(u.get("persona") == slug for u in zrodla))
        poprawki.append({"klucz": klucz, "nazwa": nazwa, "zakres": zakres, "efekt": efekt, "dotyczy": dotyczy,
                         "persony": persony if zakres == "persona" else [],
                         "z_uwag": [{"id": u.get("id"), "tekst": u.get("tekst"), "persona": u.get("persona_nazwa"),
                                     "pid": u.get("pid")} for u in zrodla[-3:]]})
    lista = [{k: u.get(k) for k in ("id", "persona", "persona_nazwa", "pid", "ocena", "tekst", "data", "poprawki", "miejsce",
                                     "model")} for u in reversed(uwagi[-30:])]
    return {"poprawki": poprawki, "uwagi": lista}


def usun_z_pamieci(poprawka=None, uwaga=None):
    """Panel: Usun poprawke (znika ze WSZYSTKICH uwag - tekst zostaje dla LLM) albo cala uwage (z regul i z LLM).
    Zwraca pamiec(). ValueError, gdy nie ma czego usunac."""
    plik = _plik_uwag()
    zmiana = False
    with baza._rmw(plik):
        dane = baza._wczytaj_json(plik, {"uwagi": []}) or {}
        for u in dane.get("uwagi") or []:
            if not isinstance(u, dict) or u.get("usunieta"):
                continue
            if uwaga and u.get("id") == uwaga:
                u["usunieta"], zmiana = True, True
            if poprawka and poprawka in (u.get("poprawki") or []):
                u["poprawki"] = [k for k in u["poprawki"] if k != poprawka]
                u.setdefault("poprawki_usuniete", []).append(poprawka)
                zmiana = True
        if zmiana:
            baza._zapisz_json(plik, dane)
    if not zmiana:
        raise ValueError("Nie ma takiej poprawki ani uwagi (moze juz usunieta).")
    return pamiec()


def uwagi_dla_llm(limit=MAX_UWAG_LLM):
    """Ostatnie uwagi usera (najnowsze pierwsze) jako linie do promptu LLM."""
    linie = []
    for u in reversed(uwagi_aktywne()[-limit:]):
        jak = "liked" if u.get("ocena") == "dobra" else "disliked"
        szczegoly = ", ".join(str(x) for x in (u.get("miejsce"), u.get("model"), u.get("kamera")) if x)
        linie.append(f"- {jak} {u.get('persona_nazwa') or u.get('persona')} #{u.get('pid')} ({szczegoly}): „{u.get('tekst')}”")
    return linie


def nauka(slug):
    """Wnioski z historii: punkty per wybor (stroj/miejsce/obiekt/kamera/reakcja/model), stroje odrzucone przez NSFW,
    obiekty i miejsca odrzucone przez IP (ze WSZYSTKICH person - filtr IP nie zalezy od twarzy) + liczniki."""
    n = {"punkty": {k: {} for k in ("stroj", "miejsce", "obiekt", "kamera", "reakcja", "model")},
         "nsfw_stroje": set(), "ip_obiekty": set(), "ip_miejsca": set(), "ip_z_nazwami": 0, "ocenione": 0, "razem": 0}
    for w in historia(slug):
        wyb, wynik = w.get("wybory") or {}, w.get("wynik")
        n["razem"] += 1
        if wynik in PUNKTY:
            n["ocenione"] += wynik in OCENY
            for k in n["punkty"]:
                if wyb.get(k):
                    n["punkty"][k][wyb[k]] = n["punkty"][k].get(wyb[k], 0) + PUNKTY[wynik]
        elif wynik == "nsfw" and wyb.get("stroj"):
            n["nsfw_stroje"].add(wyb["stroj"])
    for inna in set(baza.lista_modelek()) | {slug}:
        for w in historia(inna):
            wyb = w.get("wybory") or {}
            if w.get("wynik") == "ip":
                if wyb.get("nazwy") == "prawdziwe":
                    n["ip_z_nazwami"] += 1
                    if wyb.get("obiekt"):
                        n["ip_obiekty"].add(wyb["obiekt"])
                    if wyb.get("miejsce"):
                        n["ip_miejsca"].add(wyb["miejsce"])
    return n


def _etykieta(rodzaj, wartosc):
    """Id z katalogu -> polska etykieta (do panelu)."""
    if rodzaj == "stroj":
        bib = baza.stroj_biblioteki(wartosc)
        if bib:
            return bib["nazwa"]
        return (sc.STROJE_ODWAZNE.get(wartosc) or (wartosc,))[0]
    if rodzaj == "miejsce":
        return (sc.MIEJSCA.get(wartosc) or {}).get("nazwa", wartosc)
    if rodzaj == "obiekt":
        for lista in (sc.GALERIE, sc.DWORCE, sc.STACJE_METRA, sc.DZIELNICE, sc.MIASTA):
            if wartosc in lista:
                return lista[wartosc][0]
    return wartosc


def opis_nauki(n, dla_llm=False):
    """Krotko po polsku: co sie sprawdzilo, co nie (panel; dla_llm=True - z id z katalogu, zeby model mogl ich uzyc)."""
    def naj(k, znak):
        pozycje = sorted(n["punkty"][k].items(), key=lambda x: -x[1] * znak)
        return [i for i, pkt in pozycje if pkt * znak > 0][:3]

    def lista(rodzaj, ids):
        return ", ".join(i if dla_llm else _etykieta(rodzaj, i) for i in ids)
    czesci = []
    for rodzaj, dobre, slabe in (("stroj", "sprawdzone stroje", "słabe stroje"), ("miejsce", "dobre miejsca", "słabe miejsca")):
        if naj(rodzaj, 1):
            czesci.append(f"{dobre}: {lista(rodzaj, naj(rodzaj, 1))}")
        if naj(rodzaj, -1):
            czesci.append(f"{slabe}: {lista(rodzaj, naj(rodzaj, -1))}")
    if n["nsfw_stroje"]:
        czesci.append("filtr NSFW odrzucił stroje: " + lista("stroj", sorted(n["nsfw_stroje"])))
    if n["ip_obiekty"]:
        czesci.append("filtr IP odrzucił nazwy: " + lista("obiekt", sorted(n["ip_obiekty"])))
    return "; ".join(czesci)


def _waga(n, k, wartosc):
    return max(0.2, 1.0 + 0.35 * n["punkty"][k].get(wartosc, 0))


def _losuj_wazone(los, opcje, wagi):
    razem = sum(wagi)
    x = los.random() * razem
    for o, w in zip(opcje, wagi):
        x -= w
        if x <= 0:
            return o
    return opcje[-1]


# ---------------- reguly (dzialaja zawsze, tez bez internetu) ----------------

def dobierz_regulami(slug, tekst="", pomysl_id=None, zablokowane=None, sezon=None, los=None, n=None):
    """Opcje rolki dobrane regulami + nauka. `zablokowane` = pola ustawione recznie przez usera (zostaja). Zwraca (opcje, powody)."""
    los = los or random.Random()
    zab = dict(zablokowane or {})
    n = n or nauka(slug)
    sezon = sezon if sezon in sc.SEZONY else (zab.get("sezon") if zab.get("sezon") in sc.SEZONY else sc.sezon_z_daty())
    powody = []
    tekst = (tekst or "").strip()
    pomysl = sc.POMYSLY_PO_ID.get(pomysl_id or "")
    if not pomysl and tekst:
        pomysl = next((p for p in sc.POMYSLY if sc._bez_ogonkow(p["pl"]).strip(" .") == sc._bez_ogonkow(tekst).strip(" .")), None)
    analiza = sc.pomysl_z_tekstu(tekst) if tekst else {"miejsce": None, "czynnosci": [], "reakcja": None}

    # miejsce: recznie > z pomyslu/tekstu > wazone losowanie z miejsc "z ludzmi" (bez miejsc odrzuconych przez IP 2x)
    if zab.get("miejsce") in sc.MIEJSCA:
        miejsce = zab["miejsce"]
    elif pomysl or analiza["miejsce"]:
        miejsce = (pomysl or {}).get("miejsce") or analiza["miejsce"]
        powody.append("miejsce z Twojego pomysłu")
    else:
        kand = [m for m in MIEJSCA_REAKCJI if sezon in (sc.MIEJSCA[m].get("sezony") or (sezon,))]
        miejsce = _losuj_wazone(los, kand, [_waga(n, "miejsce", m) for m in kand])
        powody.append("dużo ludzi, którzy mogą zareagować")

    # prawdziwa nazwa (galeria/dworzec/dzielnica) albo opis, gdy filtr IP juz odrzucal nazwy
    if zab.get("nazwy") in sc.NAZWY_TRYBY:
        nazwy = zab["nazwy"]
    elif miejsce in n["ip_miejsca"] or n["ip_z_nazwami"] >= 2:
        nazwy = "opisowe"
        powody.append("bez nazw – filtr IP odrzucił je wcześniej")
    else:
        nazwy = "prawdziwe"
    obiekt = None
    if nazwy == "prawdziwe" and sc.obiekty_miejsca(miejsce):
        chce = zab.get("obiekt") if zab.get("obiekt") in sc.obiekty_miejsca(miejsce) else None
        obiekt = sc.wybierz_obiekt(miejsce, tekst, los, chce=chce, unikaj=n["ip_obiekty"])

    # stroj (3.1): z biblioteki strojow (goth) - waga (ulubione 3x) x nauka z ocen x rotacja (bez ostatnio uzytych), bez
    # odrzuconych przez NSFW. Pusta biblioteka = jak dawniej: odwazny na pore roku.
    bib = None
    if zab.get("stroj") and zab["stroj"] not in ("biblioteka",):
        stroj = zab["stroj"]
    else:
        bib = baza.losuj_stroj_biblioteki(slug, los=los, unikaj=n["nsfw_stroje"],
                                          mnozniki={s["id"]: _waga(n, "stroj", s["id"]) for s in baza.stroje_biblioteki()})
        if bib:
            stroj = f"biblioteka:{bib['id']}"
            if n["punkty"]["stroj"].get(bib["id"], 0) > 0:
                powody.append("ten strój już się sprawdził")
            elif bib["ulubiony"]:
                powody.append("jeden z Twoich ulubionych strojów")
            elif n["nsfw_stroje"]:
                powody.append("omijam stroje odrzucone przez filtr")
            else:
                powody.append("strój z biblioteki (goth)")
        else:
            kand = [s for s in sc.stroje_odwazne_na(sezon) if s not in n["nsfw_stroje"]] or sc.stroje_odwazne_na(sezon)
            sid = _losuj_wazone(los, sorted(kand), [_waga(n, "stroj", s) for s in sorted(kand)])
            stroj = f"odwazny:{sid}"
            if n["punkty"]["stroj"].get(sid, 0) > 0:
                powody.append("ten strój już się sprawdził")
            elif n["nsfw_stroje"]:
                powody.append("omijam stroje odrzucone przez filtr")
            else:
                powody.append(f"odważny strój na {sc.SEZONY[sezon]['nazwa'].lower()}")

    kamera = zab["kamera"] if zab.get("kamera") in sc.KAMERY else sc.kamera_ukryta(miejsce)
    if not zab.get("kamera"):
        powody.append("kamera z ukrycia, jak w prawdziwych nagraniach")

    # reakcja: to, co user napisal (smiech, krzywo...) - inaczej zdziwienie pasujace do miejsca
    if zab.get("reakcja") in sc.REAKCJE and zab["reakcja"] != "losowa":
        reakcja = zab["reakcja"]
    elif analiza.get("reakcja"):
        reakcja = analiza["reakcja"]
    else:
        kand = reakcje_dla_miejsca(miejsce)
        reakcja = _losuj_wazone(los, kand, [_waga(n, "reakcja", r) * (1.6 if i == 0 else 1.0) for i, r in enumerate(kand)])

    # kto nagrywa (mowi komentarz): recznie > ustawienie persony; linie reakcji sa neutralne, reczne dopasowujemy do mowiacego
    ust = baza.ustawienia_modelki(slug)
    nagrywa = zab["nagrywa"] if zab.get("nagrywa") in sc.NAGRYWA else (
        ust.get("nagrywa") if ust.get("nagrywa") in sc.NAGRYWA else sc.NAGRYWA_DOMYSLNIE)
    # 3.6: ton komentarzy persony (ostre = domyslnie, potoczny wulgarny polski jak z prawdziwych nagran; lagodne = linie reakcji)
    ton = sc.ton_komentarzy(slug, zab.get("komentarze_ton"))
    if zab.get("komentarz"):
        komentarz = sc.dopasuj_do_mowiacego(zab["komentarz"], nagrywa)
    elif ton == "ostre":
        komentarz = _wybierz(los, sc.komentarze_dla(nagrywa, "ostre"))
    else:
        linie = sc.LINIE_REAKCJI.get(reakcja) or ["Widziałaś to?", "No ja nie mogę…"]
        komentarz = _wybierz(los, linie)

    # 3.5.2: tez gotowy wariant (seedance_2_5_480p = Seedance 480p 10 s) - zbuduj() wymusza jego rozdzielczosc i dlugosc
    model = zab.get("model") if zab.get("model") in sc.MODELE or zab.get("model") in sc.WARIANTY_MODELI else (
        (ust.get("z_promptu") or {}).get("model") or sc.MODEL_DOMYSLNY)
    try:
        mi = sc.model_info(model)
    except ValueError:
        model, mi = sc.MODEL_DOMYSLNY, sc.MODELE[sc.MODEL_DOMYSLNY]
    if model in sc.WARIANTY_MODELI:
        mi = dict(mi, dlugosci=(sc.WARIANTY_MODELI[model]["dlugosc"],))
    dl = zab.get("dlugosc")
    try:
        dl = int(dl) if dl else 10
    except (TypeError, ValueError):
        dl = 10
    if dl not in mi["dlugosci"]:
        dl = 10 if 10 in mi["dlugosci"] else mi["dlugosci"][0]
    opcje = {"tekst": tekst or (pomysl or {}).get("pl", ""), "pomysl_id": (pomysl or {}).get("id") or "", "miejsce": miejsce,
             "nazwy": nazwy, "obiekt": obiekt or "", "stroj": stroj, "kamera": kamera, "reakcja": reakcja, "komentarz": komentarz,
             "nagrywa": nagrywa, "komentarze_ton": ton, "glos": zab.get("glos") if zab.get("glos") in sc.GLOSY else "auto",
             "wymowa": zab.get("wymowa") if zab.get("wymowa") in sc.WYMOWY else "fonetyczna",
             "wlosy": zab.get("wlosy") if isinstance(zab.get("wlosy"), dict) else {"kolor": "wlasne", "fryzura": "wlasna", "grzywka": "wlasna"},
             "model": model, "dlugosc": dl, "rozdzielczosc": zab.get("rozdzielczosc") or "auto",
             "sezon": zab.get("sezon") or "auto", "pora": zab.get("pora") or "auto"}
    return opcje, powody


def _wybierz(los, lista):
    return lista[los.randrange(len(lista))]


# ---------------- OpenRouter (darmowy model) ----------------

def _http_json(metoda, url, cialo=None, timeout=TIMEOUT_LLM_S):
    """Jedno zapytanie do OpenRouter (podmieniane w testach). Rzuca RuntimeError z polskim opisem."""
    klucz = sekrety.klucz("openrouter")
    naglowki = {"Content-Type": "application/json", "User-Agent": "rolki-ai/3.0", "X-Title": "rolki-ai"}
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


def modele_llm():
    """MODELE_LLM, ktore OpenRouter nadal ma (GET /models, cache 1 h); blad listy = cala lista bez filtra."""
    c = _cache_modeli
    if c["modele"] is not None and time.time() - c["czas"] < 3600:
        return c["modele"]
    try:
        dostepne = {m.get("id") for m in (_http_json("GET", LLM_API + "/models", timeout=15) or {}).get("data") or []}
        modele = [m for m in MODELE_LLM if m in dostepne or m == "openrouter/free"] or list(MODELE_LLM)
    except RuntimeError:
        modele = list(MODELE_LLM)
    c.update(czas=time.time(), modele=modele)
    return modele


def test_klucza():
    """(dziala, komunikat) - GET /key (darmowe, nic nie zuzywa). Panel: Konta -> OpenRouter -> Sprawdz."""
    if not sekrety.klucz("openrouter"):
        return False, "brak klucza OpenRouter (panel -> Konta)"
    try:
        d = (_http_json("GET", LLM_API + "/key", timeout=15) or {}).get("data") or {}
    except RuntimeError as e:
        return False, str(e)
    darmowy = " (konto bez doladowania - wystarczy, asystent bierze tylko darmowe modele)" if d.get("is_free_tier") else ""
    return True, "klucz dziala" + darmowy


def _stroje_dla_llm(sezon, n):
    """[(id, etykieta)] strojow, z ktorych model moze wybierac: biblioteka (ulubione z '*'), a gdy pusta - odwazne na pore roku."""
    bib = [s for s in baza.stroje_biblioteki() if s["id"] not in n["nsfw_stroje"] and s["waga"] > 0]
    if bib:
        return [(s["id"], ("*" if s["ulubiony"] else "") + s["nazwa"]) for s in sorted(bib, key=lambda s: not s["ulubiony"])]
    stroje = [s for s in sc.stroje_odwazne_na(sezon) if s not in n["nsfw_stroje"]] or sc.stroje_odwazne_na(sezon)
    return [(k, sc.STROJE_ODWAZNE[k][0]) for k in stroje]


def _katalog_dla_llm(sezon, n, ton="lagodne", nagrywa=None):
    przyklady = sc.komentarze_dla(nagrywa, "ostre")[:12] if ton == "ostre" else sc.KOMENTARZE
    linie = [
        "PLACES (id: Polish name):", "; ".join(f"{k}: {v['nazwa']}" for k, v in sc.MIEJSCA.items()
                                             if sezon in (v.get("sezony") or (sezon,))),
        "OUTFITS (id: Polish label; * = the user's favourite, prefer these):",
        "; ".join(f"{k}: {etykieta}" for k, etykieta in _stroje_dla_llm(sezon, n)),
        "CAMERAS (id: label; covert ones are the default):", "; ".join(f"{k}: {sc.KAMERY[k][0]}" for k in sc.KAMERY_UKRYTE),
        "REACTIONS (id: label):", "; ".join(f"{k}: {v[0]}" for k, v in sc.REAKCJE.items() if k != "losowa"),
        "COMMENT LINES (examples):", " | ".join(przyklady),
    ]
    return "\n".join(linie)


TON_LLM = {
    "ostre": ("COMMENT STYLE: crude, colloquial street Polish with swearing (e.g. 'kurwa', 'ja pierdolę'), exactly like real "
              "hidden-camera clips from Poland - short, spontaneous, a bit mocking."),
    "lagodne": "COMMENT STYLE: mild, no swearing - surprised or amused, like a polite person whispering to a friend.",
}


SYSTEM_LLM = (
    "You pick settings for a short vertical AI reel: a young woman in a bold goth street outfit is secretly filmed on a "
    "phone in a real place in Poland while people around react with subtle surprise. Pick the combination that best fits the "
    "user's idea and is most likely to look real and get reactions. Rules: if the idea names a place or city, follow it; outfits "
    "must come from the OUTFITS list (prefer the user's favourites marked with *); camera must be covert (from the CAMERAS "
    "list); prefer a surprise reaction that fits the place unless the idea says otherwise; the comment is ONE very short natural "
    "Polish line (max 6 words) said quietly by the person filming (see SPEAKER) - she herself never speaks; any first-person "
    "past or conditional verb must match the speaker's gender (a young man: 'widziałem', 'odważyłbym'; a young woman: "
    "'widziałam', 'odważyłabym'), neutral lines are best; follow the COMMENT STYLE; prefer what the learning notes say worked, "
    "avoid what failed, and take the user's notes on recent reels seriously (avoid what they disliked, repeat what they liked). "
    "Answer with ONLY a JSON object: "
    '{"miejsce": "<place id>", "stroj": "<outfit id>", "kamera": "<camera id>", "reakcja": "<reaction id>", '
    '"komentarz": "<Polish line>", "dlugosc": 10, "dlaczego": "<one short sentence in Polish, max 140 characters>"}'
)


def _json_z_tekstu(tekst):
    t = (tekst or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("brak JSON w odpowiedzi")
    return json.loads(m.group(0))


def zapytaj_llm(slug, tekst, sezon, n, model, nagrywa=None, ton="lagodne"):
    """Jedno zapytanie do darmowego modelu -> surowy slownik z JSON (bez walidacji). 3.6: ton komentarzy + ostatnie uwagi usera
    do ocenionych rolek (MAX_UWAG_LLM)."""
    kto = "a young woman" if nagrywa == "dziewczyna" else "a young man"
    try:
        uwagi = uwagi_dla_llm()
    except (OSError, ValueError):
        uwagi = []
    uzytkownik = (f"Idea (Polish): „{tekst or 'brak - wybierz sam cos z duza szansa na reakcje ludzi'}”\n"
                  f"Season now: {sc.SEZONY[sezon]['en']}.\n"
                  f"SPEAKER (the person filming, never visible): {kto}.\n"
                  f"{TON_LLM.get(ton, TON_LLM['lagodne'])}\n"
                  f"Learning notes: {opis_nauki(n, dla_llm=True) or 'none yet'}.\n"
                  f"User's notes on recent reels (newest first, in Polish): "
                  + ("\n" + "\n".join(uwagi) if uwagi else "none yet") + "\n\n"
                  + _katalog_dla_llm(sezon, n, ton, nagrywa))
    odp = _http_json("POST", LLM_API + "/chat/completions", {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_LLM}, {"role": "user", "content": uzytkownik}],
        "temperature": 0.7, "max_tokens": 400,
        "reasoning": {"effort": "low", "exclude": True},
    })
    if isinstance(odp, dict) and odp.get("error"):
        raise RuntimeError(f"OpenRouter: {str((odp['error'] or {}).get('message', odp['error']))[:200]}")
    try:
        tresc = odp["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("dziwna odpowiedz z OpenRouter")
    return _json_z_tekstu(tresc)


_POLSKIE = re.compile(r"^[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż ,.!?…'-]{2,60}$")


def _zastosuj_llm(opcje, wynik, n, sezon, zab, miejsce_z_tekstu):
    """Pola z odpowiedzi LLM, ktore przechodza walidacje, nadpisuja opcje regul. Zwraca liste przyjetych pol."""
    przyjete = []
    m = wynik.get("miejsce")
    if m in sc.MIEJSCA and not zab.get("miejsce") and not miejsce_z_tekstu and sezon in (sc.MIEJSCA[m].get("sezony") or (sezon,)):
        if m != opcje["miejsce"]:
            opcje["miejsce"] = m
            opcje["obiekt"] = ""
            if opcje["nazwy"] == "prawdziwe" and sc.obiekty_miejsca(m):
                opcje["obiekt"] = sc.wybierz_obiekt(m, opcje.get("tekst", ""), random.Random(), unikaj=n["ip_obiekty"]) or ""
            if not zab.get("kamera"):
                opcje["kamera"] = sc.kamera_ukryta(m)
        przyjete.append("miejsce")
    s = str(wynik.get("stroj") or "").replace("odwazny:", "").replace("biblioteka:", "").lstrip("*").strip()
    dozwolone = {k for k, _ in _stroje_dla_llm(sezon, n)}
    if s in dozwolone and not (zab.get("stroj") and zab["stroj"] != "biblioteka"):
        opcje["stroj"] = f"biblioteka:{s}" if baza.stroj_biblioteki(s) else f"odwazny:{s}"
        przyjete.append("stroj")
    k = wynik.get("kamera")
    if k in sc.KAMERY_UKRYTE and not zab.get("kamera"):
        opcje["kamera"] = k
        przyjete.append("kamera")
    r = wynik.get("reakcja")
    if r in sc.REAKCJE and r != "losowa" and not zab.get("reakcja"):
        opcje["reakcja"] = r
        przyjete.append("reakcja")
    kom = re.sub(r"[{}„”\"\[\]]", "", str(wynik.get("komentarz") or "")).strip()
    if (kom and _POLSKIE.match(kom) and len(kom.split()) <= 7 and not zab.get("komentarz")
            and sc.pasuje_do_mowiacego(kom, opcje.get("nagrywa"))
            and not (opcje.get("komentarze_ton") == "lagodne" and sc.WULGARNE.search(sc._bez_ogonkow(kom)))):
        opcje["komentarz"] = kom
        przyjete.append("komentarz")
    try:
        dl = int(wynik.get("dlugosc"))
    except (TypeError, ValueError):
        dl = None
    if (dl and opcje["model"] not in sc.WARIANTY_MODELI and dl in sc.MODELE.get(opcje["model"], sc.MODELE[sc.MODEL_DOMYSLNY])["dlugosci"]
            and not zab.get("dlugosc")):
        opcje["dlugosc"] = dl
    return przyjete


# ---------------- glowna funkcja ----------------

def podsumowanie(opcje, glos_efektywny=None):
    """Jedna linijka po polsku: co asystent dobral (panel pokazuje ja nad cena)."""
    m = sc.MIEJSCA.get(opcje.get("miejsce")) or {}
    obiekty = sc.obiekty_miejsca(opcje.get("miejsce"))
    gdzie = m.get("nazwa", "")
    if opcje.get("obiekt") in obiekty:
        gdzie = (f"Galeria {obiekty[opcje['obiekt']][0]}" if opcje.get("miejsce") in ("galeria_foodcourt", "galeria_pasaz")
                 else f"{gdzie}, {obiekty[opcje['obiekt']][0]}")
    st = str(opcje.get("stroj") or "")
    bib = baza.stroj_biblioteki(st.split(":", 1)[1]) if st.startswith("biblioteka:") else None
    if bib:
        stroj = ("★ " if bib["ulubiony"] else "") + bib["nazwa"]
    elif st.startswith("odwazny:") and st.split(":", 1)[1] in sc.STROJE_ODWAZNE:
        stroj = sc.STROJE_ODWAZNE[st.split(":", 1)[1]][0]
    else:
        stroj = sc.STROJE_TRYBY.get(st.split(":")[0], st)
    kamera = (sc.KAMERY.get(opcje.get("kamera")) or ("",))[0]
    reakcja = (sc.REAKCJE.get(opcje.get("reakcja")) or ("",))[0]
    glos = glos_efektywny or opcje.get("glos")
    kto = "dziewczyna" if opcje.get("nagrywa") == "dziewczyna" else "chłopak"
    glos_txt = (f"mówi {kto} zza kamery, ElevenLabs" if glos in ("tts", "auto", None)
                else f"ElevenLabs nie działa – rolka bez komentarza")
    model = (sc.MODELE.get(opcje.get("model")) or sc.WARIANTY_MODELI.get(opcje.get("model")) or {}).get("nazwa", "").split(" –")[0]
    czesci = [gdzie, f"strój: {stroj}", f"kamera: {kamera.lower()}", f"reakcja: {reakcja.lower()}"]
    if opcje.get("komentarz") and opcje.get("komentarz") != "bez":
        czesci.append(f"„{opcje['komentarz']}” ({glos_txt})")
    czesci.append(f"{opcje.get('dlugosc')} s · {model}")
    return " · ".join(c for c in czesci if c)


def dobierz(slug, tekst="", pomysl_id=None, zablokowane=None, uzyj_llm=True, los=None, glos_efektywny=None):
    """Asystent: opcje do scenariusz.zbuduj + jedno zdanie 'dlaczego'. LLM (darmowy OpenRouter), gdy jest klucz; inaczej reguly.
    Zwraca {"opcje", "podsumowanie", "dlaczego", "zrodlo": "openrouter:<model>" | "reguly", "uwaga", "nauka"}."""
    zab = {k: v for k, v in (zablokowane or {}).items() if v not in (None, "", "auto", "losowa", "losowy")}
    n = nauka(slug)
    sezon = zab.get("sezon") if zab.get("sezon") in sc.SEZONY else sc.sezon_z_daty()
    opcje, powody = dobierz_regulami(slug, tekst, pomysl_id, zab, sezon, los, n)
    zrodlo, uwaga, dlaczego = "reguly", "", ""
    miejsce_z_tekstu = bool(opcje.get("pomysl_id") or (tekst and sc.pomysl_z_tekstu(tekst)["miejsce"]))
    if uzyj_llm and sekrety.klucz("openrouter"):
        bledy = []
        for model in modele_llm()[:MAX_PROB_LLM]:
            try:
                wynik = zapytaj_llm(slug, tekst, sezon, n, model, nagrywa=opcje.get("nagrywa"), ton=opcje.get("komentarze_ton"))
            except (RuntimeError, ValueError) as e:
                bledy.append(f"{model.split('/')[-1]}: {e}")
                if "zly klucz" in str(e) or "doladowania" in str(e):
                    break
                continue
            przyjete = _zastosuj_llm(opcje, wynik if isinstance(wynik, dict) else {}, n, sezon, zab, miejsce_z_tekstu)
            if przyjete:
                zrodlo = f"openrouter:{model}"
                d = re.sub(r"\s+", " ", str(wynik.get("dlaczego") or "")).strip()
                dlaczego = d[:200] if d and re.search(r"[ąćęłńóśźżA-Za-z]", d) else ""
                break
            bledy.append(f"{model.split('/')[-1]}: odpowiedz bez pasujacych pol")
        if zrodlo == "reguly" and bledy:
            uwaga = "Darmowy model AI nie odpowiedział – dobrałem regułami (" + "; ".join(bledy)[:200] + ")."
    elif uzyj_llm:
        uwaga = "Bez klucza OpenRouter asystent dobiera regułami (Ustawienia → Konta → OpenRouter, za darmo)."
    if not dlaczego:
        dlaczego = (", ".join(dict.fromkeys(powody)) or "dobrane do pomysłu")
        dlaczego = dlaczego[:1].upper() + dlaczego[1:] + "."
    return {"opcje": opcje, "podsumowanie": podsumowanie(opcje, glos_efektywny), "dlaczego": dlaczego, "zrodlo": zrodlo,
            "uwaga": uwaga, "nauka": opis_nauki(n)}


MAX_UWAGI_ZNAKOW = 400


def ocen(slug, pid, ocena, komentarz=None):
    """Ocena usera rolki z promptu: 'dobra' / 'slaba' / None (cofnij). Asystent liczy ja przy nastepnym dobieraniu.
    3.6: komentarz = "Co wyszlo zle?" / "Co bylo dobre?" -> pomysl.ocena_komentarz + uwaga w asystent_uwagi.json (reguly ->
    stale poprawki promptu, ostatnie uwagi -> LLM). Cofniecie oceny albo ocena bez tekstu usuwa uwage tej rolki."""
    if ocena not in OCENY + (None,):
        raise ValueError("Ocena: dobra, slaba albo brak.")
    p = baza.pomysl(slug, int(pid))
    if p.get("typ") != "prompt":
        raise ValueError("Oceniac mozna rolki z promptu.")
    tekst = re.sub(r"\s+", " ", str(komentarz or "")).strip()[:MAX_UWAGI_ZNAKOW] if ocena else ""
    p = baza.aktualizuj_pomysl(slug, int(pid), ocena=ocena, ocena_komentarz=tekst or None,
                               ocena_poprawki=rozpoznaj_uwage(tekst, ocena) if tekst else None)
    if tekst:
        zapisz_uwage(slug, p, ocena, tekst)
    else:
        usun_uwagi_rolki(slug, int(pid))
    return p
