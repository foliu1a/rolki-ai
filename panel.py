# -*- coding: utf-8 -*-
"""Panel CLI - glowny punkt wejscia do rolki-ai."""
import os
import sys

import baza

if sys.platform == "win32":
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")


def wybierz_modelke_interaktywnie():
    modelki = baza.lista_modelek()
    if not modelki:
        print("Brak modelek. Wybierz opcje 1 zeby utworzyc pierwsza.")
        return None
    print("\nModelki:")
    for i, m in enumerate(modelki, 1):
        print(f"  {i}. {m}")
    wybor = input("Numer: ").strip()
    if wybor.isdigit() and 1 <= int(wybor) <= len(modelki):
        return modelki[int(wybor) - 1]
    print("Nieprawidlowy wybor.")
    return None


def naglowek(aktywna):
    print()
    print("=" * 56)
    if aktywna:
        prof = baza.profil_modelki(aktywna)
        ig = f"  IG: {prof['instagram']}" if prof.get("instagram") else ""
        print(f"rolki-ai  |  modelka: {aktywna}{ig}")
        st = baza.statystyki_pomyslow(aktywna)
        nieuzyte, wszystkie = baza.statystyki_tekstow(aktywna)
        czesci = [f"{n}: {st[n]}" for n in baza.STATUSY if st[n]]
        pomysly_txt = ", ".join(czesci) if czesci else "brak"
        print(f"pomysly: {pomysly_txt}  |  teksty: {nieuzyte} nieuzytych / {wszystkie}")
    else:
        print("rolki-ai  |  brak aktywnej modelki (opcja 2)")
    print("=" * 56)


def menu_glowne():
    while True:
        aktywna = baza.aktywna_modelka()
        naglowek(aktywna)
        print(" MODELKA                     POMYSLY")
        print("  1. Nowa modelka             3. Dodaj pomysl")
        print("  2. Wybierz aktywna          4. Lista pomyslow")
        print("  9. Profil modelki           5. Zmien status / usun")
        print()
        print(" PRODUKCJA                   TEKSTY")
        print("  6. Postprodukcja            7. Dodaj teksty (wklej)")
        print("  g. Higgsfield (pomysl)     10. Import tekstow z pliku")
        print("                              8. Losuj nieuzyty tekst")
        print()
        print(" SZABLONY PROMPTOW           INNE")
        print(" 11. Lista / dodaj / usun     0. Wyjscie")
        wybor = input("\nWybor: ").strip().lower()

        wymaga_modelki = wybor in ("3", "4", "5", "6", "7", "8", "9", "10", "11", "g")
        if wymaga_modelki and not aktywna:
            print("Najpierw wybierz aktywna modelke (opcja 2).")
            continue

        try:
            if wybor == "1":
                nazwa = input("Nazwa nowej modelki: ").strip()
                slug = baza.utworz_modelke(nazwa)
                baza.ustaw_aktywna_modelke(slug)
                print(f"Utworzono '{slug}' i ustawiono jako aktywna.")
                ig = input("Link/handle Instagram (Enter = pomin): ").strip()
                if ig:
                    baza.zapisz_profil(slug, instagram=ig)
            elif wybor == "2":
                slug = wybierz_modelke_interaktywnie()
                if slug:
                    baza.ustaw_aktywna_modelke(slug)
                    print(f"Aktywna modelka: {slug}")
            elif wybor == "3":
                dodaj_pomysl(aktywna)
            elif wybor == "4":
                lista_pomyslow(aktywna)
            elif wybor == "5":
                zmien_lub_usun_pomysl(aktywna)
            elif wybor == "6":
                postprodukcja(aktywna)
            elif wybor == "7":
                dodaj_teksty_wklej(aktywna)
            elif wybor == "8":
                losuj_tekst(aktywna)
            elif wybor == "9":
                profil_modelki(aktywna)
            elif wybor == "10":
                import_tekstow(aktywna)
            elif wybor == "11":
                szablony(aktywna)
            elif wybor == "g":
                generuj_przez_higgsfield(aktywna)
            elif wybor == "0":
                break
            else:
                print("Nieznana opcja.")
        except KeyboardInterrupt:
            print("\n(przerwano)")
        except Exception as e:
            print(f"[BLAD] {type(e).__name__}: {e}")


# ---------------- pomysly ----------------

def dodaj_pomysl(slug):
    opis = input("Opis pomyslu: ").strip()
    if not opis:
        print("Pusty opis - anulowano.")
        return

    prompt = ""
    szablony_lista = baza.lista_szablonow(slug)
    if szablony_lista:
        uzyj = input("Uzyc szablonu promptu? (t/n) [n]: ").strip().lower()
        if uzyj in ("t", "tak", "y"):
            prompt = prompt_z_szablonu(slug) or ""
    if not prompt:
        prompt = input("Prompt do Higgsfield (Enter = pomin na razie): ").strip()

    pid = baza.dodaj_pomysl(slug, opis, prompt)
    print(f"Dodano pomysl #{pid}.")


def lista_pomyslow(slug):
    pomysly = baza.lista_pomyslow(slug)
    if not pomysly:
        print("Brak pomyslow. Dodaj pierwszy opcja 3.")
        return
    for p in pomysly:
        linia = f"  #{p['id']:3} [{p['status']:13}] {p['opis']}"
        if p.get("plik_wynikowy"):
            linia += f"  -> {p['plik_wynikowy']}"
        print(linia)
        if p.get("prompt_higgsfield"):
            print(f"        prompt: {p['prompt_higgsfield'][:70]}"
                  + ("..." if len(p["prompt_higgsfield"]) > 70 else ""))


def zmien_lub_usun_pomysl(slug):
    lista_pomyslow(slug)
    wybor = input("\nNumer pomyslu (Enter = anuluj): ").strip()
    if not wybor.isdigit():
        return
    pid = int(wybor)
    print(f"Statusy: {', '.join(baza.STATUSY)}")
    akcja = input("Nowy status albo 'usun' (Enter = anuluj): ").strip().lower()
    if not akcja:
        return
    if akcja == "usun":
        if input(f"Na pewno usunac pomysl #{pid}? (t/n): ").strip().lower() in ("t", "tak", "y"):
            baza.usun_pomysl(slug, pid)
            print(f"Usunieto #{pid}.")
    else:
        baza.aktualizuj_pomysl(slug, pid, status=akcja)
        print(f"Pomysl #{pid} -> {akcja}.")


# ---------------- teksty ----------------

def dodaj_teksty_wklej(slug):
    print("Wklej teksty (jeden na linie), pusta linia = koniec:")
    teksty = []
    while True:
        linia = input()
        if not linia.strip():
            break
        teksty.append(linia)
    zrodlo = input("Zrodlo (np. nazwa profilu IG, opcjonalnie): ").strip()
    n = baza.dodaj_teksty(slug, teksty, zrodlo)
    pominiete = len([t for t in teksty if t.strip()]) - n
    komunikat = f"Dodano {n} tekstow."
    if pominiete:
        komunikat += f" Pominieto {pominiete} (duplikaty)."
    print(komunikat)


def import_tekstow(slug):
    sciezka = input("Sciezka do pliku .txt: ").strip().strip('"')
    if not os.path.isfile(sciezka):
        print(f"Nie ma takiego pliku: {sciezka}")
        return
    zrodlo = input("Zrodlo (Enter = nazwa pliku): ").strip()
    n = baza.dodaj_teksty_z_pliku(slug, sciezka, zrodlo)
    print(f"Dodano {n} nowych tekstow (duplikaty pominiete).")


def losuj_tekst(slug):
    nieuzyte, wszystkie = baza.statystyki_tekstow(slug)
    tekst = baza.losuj_tekst(slug)
    if tekst:
        print(f"\n{tekst}\n")
        print(f"(zostalo {nieuzyte - 1} nieuzytych z {wszystkie})")
    else:
        print(f"Brak nieuzytych tekstow w banku (wszystkie {wszystkie} juz uzyte).")


# ---------------- profil ----------------

def profil_modelki(slug):
    prof = baza.profil_modelki(slug)
    print(f"\nProfil modelki '{slug}':")
    print(f"  nazwa:      {prof.get('nazwa', slug)}")
    print(f"  instagram:  {prof.get('instagram') or '(brak)'}")
    print(f"  opis stylu: {prof.get('opis_stylu') or '(brak)'}")
    print(f"  cechy:      {', '.join(prof.get('cechy', [])) or '(brak)'}")
    if input("\nEdytowac? (t/n) [n]: ").strip().lower() not in ("t", "tak", "y"):
        return
    ig = input(f"Instagram [{prof.get('instagram', '')}]: ").strip()
    opis = input(f"Opis stylu [{prof.get('opis_stylu', '')}]: ").strip()
    cechy = input(f"Cechy po przecinku [{', '.join(prof.get('cechy', []))}]: ").strip()
    zmiany = {}
    if ig:
        zmiany["instagram"] = ig
    if opis:
        zmiany["opis_stylu"] = opis
    if cechy:
        zmiany["cechy"] = [c.strip() for c in cechy.split(",") if c.strip()]
    if zmiany:
        baza.zapisz_profil(slug, **zmiany)
        print("Zapisano.")


# ---------------- szablony ----------------

def szablony(slug):
    szablony_lista = baza.lista_szablonow(slug)
    if szablony_lista:
        print("\nSzablony:")
        for s in szablony_lista:
            print(f"  - {s['nazwa']}: {s['tresc'][:60]}" + ("..." if len(s["tresc"]) > 60 else ""))
    else:
        print("\nBrak szablonow.")
    print("\n d = dodaj | u = usun | Enter = wroc")
    akcja = input("Wybor: ").strip().lower()
    if akcja == "d":
        nazwa = input("Nazwa szablonu: ").strip()
        print("Tresc promptu - placeholdery w klamrach, np. {scena}, {ubior}:")
        tresc = input("> ").strip()
        if nazwa and tresc:
            baza.dodaj_szablon(slug, nazwa, tresc)
            ph = baza.placeholdery_szablonu(tresc)
            print(f"Dodano '{nazwa}'" + (f" (placeholdery: {', '.join(ph)})" if ph else ""))
    elif akcja == "u":
        nazwa = input("Nazwa szablonu do usuniecia: ").strip()
        baza.usun_szablon(slug, nazwa)
        print(f"Usunieto '{nazwa}'.")


def prompt_z_szablonu(slug):
    """Wybor szablonu + wypelnienie placeholderow. Zwraca gotowy prompt albo None."""
    szablony_lista = baza.lista_szablonow(slug)
    if not szablony_lista:
        print("Brak szablonow.")
        return None
    for i, s in enumerate(szablony_lista, 1):
        print(f"  {i}. {s['nazwa']}: {s['tresc'][:60]}")
    wybor = input("Numer szablonu (Enter = anuluj): ").strip()
    if not wybor.isdigit() or not 1 <= int(wybor) <= len(szablony_lista):
        return None
    szablon = szablony_lista[int(wybor) - 1]
    wartosci = {}
    for ph in baza.placeholdery_szablonu(szablon["tresc"]):
        wartosci[ph] = input(f"  {ph}: ").strip()
    prompt = baza.wypelnij_szablon(szablon["tresc"], wartosci)
    print(f"Prompt: {prompt}")
    return prompt


# ---------------- produkcja ----------------

def generuj_przez_higgsfield(slug):
    nowe = baza.lista_pomyslow(slug, status="nowy")
    if not nowe:
        print("Brak pomyslow o statusie 'nowy'.")
        return
    for p in nowe:
        print(f"  #{p['id']}: {p['opis']}")
    wybor = input("Numer pomyslu (Enter = anuluj): ").strip()
    if not wybor.isdigit():
        return
    pomysl = next((p for p in nowe if p["id"] == int(wybor)), None)
    if not pomysl:
        print("Nie ma takiego pomyslu.")
        return
    if not pomysl["prompt_higgsfield"]:
        prompt = input("Prompt do Higgsfield: ").strip()
        if not prompt:
            print("Bez promptu nie generuje.")
            return
        baza.aktualizuj_pomysl(slug, pomysl["id"], prompt_higgsfield=prompt)

    # Cala logika (bezpiecznik kredytow, CLI, pobranie wyniku) siedzi w fabryka.py
    import fabryka
    fabryka.main(["--modelka", slug, "generuj", "--id", str(pomysl["id"])])


def postprodukcja(slug):
    plik = input("Sciezka do pliku wejsciowego (po faceswapie): ").strip().strip('"')
    if not os.path.isfile(plik):
        print(f"Nie ma takiego pliku: {plik}")
        return
    liczba = input("Ile wariantow? [10]: ").strip()
    liczba = int(liczba) if liczba.isdigit() else 10

    # Opcjonalnie: domknij konkretny pomysl (status -> gotowe)
    otwarte = [p for p in baza.lista_pomyslow(slug)
               if p["status"] in ("wygenerowany", "postprodukcja")]
    pomysl_id = None
    if otwarte:
        print("\nDomknac ktorys pomysl tym wynikiem? (Enter = zaden)")
        for p in otwarte:
            print(f"  #{p['id']}: {p['opis']}")
        wybor = input("Numer pomyslu: ").strip()
        if wybor.isdigit() and any(p["id"] == int(wybor) for p in otwarte):
            pomysl_id = int(wybor)

    folder_wynikow = os.path.join(baza.folder_modelki(slug), "wyniki")

    import postprocess
    try:
        pliki = postprocess.wygeneruj_warianty(plik, folder_wynikow, liczba)
    except Exception as e:
        print(f"[BLAD] {e}")
        return

    print(f"Gotowe: {len(pliki)} plikow w {folder_wynikow}")
    if pomysl_id is not None:
        baza.aktualizuj_pomysl(slug, pomysl_id, status="gotowe", plik_wynikowy=folder_wynikow)
        print(f"Pomysl #{pomysl_id} oznaczony jako gotowy.")


if __name__ == "__main__":
    menu_glowne()
