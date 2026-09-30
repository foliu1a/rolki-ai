# -*- coding: utf-8 -*-
"""Panel webowy rolki-ai - odpalasz panel.bat i klikasz w przegladarce."""
import os
import sys
import threading
import traceback

from flask import Flask, jsonify, render_template, request

import baza

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

app = Flask(__name__)

PORT = 5077

# Stan postprodukcji (jedno zadanie na raz)
zadanie = {
    "trwa": False,
    "procent": 0,
    "komunikat": "",
    "blad": None,
    "wynik": None,
}


def _ok(**dane):
    return jsonify({"ok": True, **dane})


def _blad(msg, kod=400):
    return jsonify({"ok": False, "blad": str(msg)}), kod


# ---------------- strona ----------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------- stan ogolny ----------------

@app.route("/api/stan")
def api_stan():
    aktywna = baza.aktywna_modelka()
    modelki = baza.lista_modelek()
    if aktywna not in modelki:
        aktywna = None
    dane = {"modelki": modelki, "aktywna": aktywna}
    if aktywna:
        dane["profil"] = baza.profil_modelki(aktywna)
        dane["statystyki_pomyslow"] = baza.statystyki_pomyslow(aktywna)
        nieuzyte, wszystkie = baza.statystyki_tekstow(aktywna)
        dane["teksty_nieuzyte"] = nieuzyte
        dane["teksty_wszystkie"] = wszystkie
    return _ok(**dane)


# ---------------- modelki ----------------

@app.route("/api/modelki", methods=["POST"])
def api_nowa_modelka():
    nazwa = (request.json or {}).get("nazwa", "").strip()
    if not nazwa:
        return _blad("Podaj nazwe modelki.")
    try:
        slug = baza.utworz_modelke(nazwa)
    except ValueError as e:
        return _blad(e)
    baza.ustaw_aktywna_modelke(slug)
    ig = (request.json or {}).get("instagram", "").strip()
    if ig:
        baza.zapisz_profil(slug, instagram=ig)
    return _ok(slug=slug)


@app.route("/api/modelki/aktywna", methods=["POST"])
def api_aktywna_modelka():
    slug = (request.json or {}).get("slug", "")
    try:
        baza.ustaw_aktywna_modelke(slug)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/profil", methods=["POST"])
def api_profil():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    dane = request.json or {}
    zmiany = {}
    for pole in ("instagram", "opis_stylu", "nazwa"):
        if pole in dane:
            zmiany[pole] = str(dane[pole]).strip()
    if "cechy" in dane:
        if isinstance(dane["cechy"], list):
            zmiany["cechy"] = [str(c).strip() for c in dane["cechy"] if str(c).strip()]
        else:
            zmiany["cechy"] = [c.strip() for c in str(dane["cechy"]).split(",") if c.strip()]
    profil = baza.zapisz_profil(aktywna, **zmiany)
    return _ok(profil=profil)


# ---------------- pomysly ----------------

@app.route("/api/pomysly")
def api_pomysly():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    return _ok(pomysly=baza.lista_pomyslow(aktywna), statusy=baza.STATUSY)


@app.route("/api/pomysly", methods=["POST"])
def api_dodaj_pomysl():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    dane = request.json or {}
    opis = dane.get("opis", "").strip()
    if not opis:
        return _blad("Podaj opis pomyslu.")
    pid = baza.dodaj_pomysl(aktywna, opis, dane.get("prompt", "").strip())
    return _ok(id=pid)


@app.route("/api/pomysly/<int:pid>", methods=["PATCH"])
def api_aktualizuj_pomysl(pid):
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    dane = {k: v for k, v in (request.json or {}).items()
            if k in ("status", "opis", "prompt_higgsfield", "plik_wynikowy", "notatki")}
    try:
        pomysl = baza.aktualizuj_pomysl(aktywna, pid, **dane)
    except ValueError as e:
        return _blad(e)
    return _ok(pomysl=pomysl)


@app.route("/api/pomysly/<int:pid>", methods=["DELETE"])
def api_usun_pomysl(pid):
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    try:
        baza.usun_pomysl(aktywna, pid)
    except ValueError as e:
        return _blad(e)
    return _ok()


# ---------------- szablony ----------------

@app.route("/api/szablony")
def api_szablony():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    szablony = baza.lista_szablonow(aktywna)
    for s in szablony:
        s["placeholdery"] = baza.placeholdery_szablonu(s["tresc"])
    return _ok(szablony=szablony)


@app.route("/api/szablony", methods=["POST"])
def api_dodaj_szablon():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    dane = request.json or {}
    nazwa = dane.get("nazwa", "").strip()
    tresc = dane.get("tresc", "").strip()
    if not nazwa or not tresc:
        return _blad("Podaj nazwe i tresc szablonu.")
    try:
        baza.dodaj_szablon(aktywna, nazwa, tresc)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/szablony/<nazwa>", methods=["DELETE"])
def api_usun_szablon(nazwa):
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    try:
        baza.usun_szablon(aktywna, nazwa)
    except ValueError as e:
        return _blad(e)
    return _ok()


@app.route("/api/szablony/wypelnij", methods=["POST"])
def api_wypelnij_szablon():
    dane = request.json or {}
    return _ok(prompt=baza.wypelnij_szablon(dane.get("tresc", ""), dane.get("wartosci", {})))


# ---------------- teksty ----------------

@app.route("/api/teksty")
def api_teksty():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    return _ok(teksty=baza.lista_tekstow(aktywna))


@app.route("/api/teksty", methods=["POST"])
def api_dodaj_teksty():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    dane = request.json or {}
    surowe = dane.get("teksty", "")
    if isinstance(surowe, str):
        if "---" in surowe:
            teksty = [b.strip() for b in surowe.split("---")]
        else:
            teksty = surowe.splitlines()
    else:
        teksty = list(surowe)
    n = baza.dodaj_teksty(aktywna, teksty, dane.get("zrodlo", "").strip())
    return _ok(dodano=n)


@app.route("/api/teksty/losuj", methods=["POST"])
def api_losuj_tekst():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    tekst = baza.losuj_tekst(aktywna)
    nieuzyte, wszystkie = baza.statystyki_tekstow(aktywna)
    return _ok(tekst=tekst, nieuzyte=nieuzyte, wszystkie=wszystkie)


# ---------------- postprodukcja ----------------

def _postprodukcja_w_tle(plik, liczba, pomysl_id, slug):
    import postprocess
    try:
        folder_wynikow = os.path.join(baza.folder_modelki(slug), "wyniki")

        def postep(aktualny, calkowity, komunikat):
            zadanie["procent"] = int(aktualny / max(calkowity, 1) * 100)
            zadanie["komunikat"] = komunikat

        pliki = postprocess.wygeneruj_warianty(
            plik, folder_wynikow, liczba, progress_callback=postep
        )
        zadanie["wynik"] = {"liczba": len(pliki), "folder": folder_wynikow}
        zadanie["procent"] = 100
        zadanie["komunikat"] = "Gotowe"
        if pomysl_id:
            baza.aktualizuj_pomysl(slug, pomysl_id,
                                   status="gotowe", plik_wynikowy=folder_wynikow)
    except Exception as e:
        traceback.print_exc()
        zadanie["blad"] = f"{type(e).__name__}: {e}"
    finally:
        zadanie["trwa"] = False


@app.route("/api/postprodukcja", methods=["POST"])
def api_postprodukcja():
    aktywna = baza.aktywna_modelka()
    if not aktywna:
        return _blad("Brak aktywnej modelki.")
    if zadanie["trwa"]:
        return _blad("Postprodukcja juz trwa - poczekaj az sie skonczy.")
    dane = request.json or {}
    plik = dane.get("plik", "").strip().strip('"')
    if not os.path.isfile(plik):
        return _blad(f"Nie ma takiego pliku: {plik}")
    try:
        liczba = max(1, min(500, int(dane.get("liczba", 10))))
    except (TypeError, ValueError):
        liczba = 10
    pomysl_id = dane.get("pomysl_id") or None
    if pomysl_id is not None:
        pomysl_id = int(pomysl_id)

    zadanie.update({"trwa": True, "procent": 0, "komunikat": "Startuje...",
                    "blad": None, "wynik": None})
    watek = threading.Thread(
        target=_postprodukcja_w_tle, args=(plik, liczba, pomysl_id, aktywna), daemon=True
    )
    watek.start()
    return _ok()


@app.route("/api/postprodukcja/status")
def api_postprodukcja_status():
    return _ok(**zadanie)


if __name__ == "__main__":
    print(f"Panel rolki-ai: http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
