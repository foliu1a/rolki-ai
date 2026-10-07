# -*- coding: utf-8 -*-
"""scenariusz.py - "Rolka z promptu": pomysl po polsku -> dlugi angielski prompt + lista zdjec (bez filmiku zrodlowego).

Czyste funkcje (zero wysylania, zero kredytow) - fabryka.py (wycena_z_promptu / dodaj_z_promptu), panel (zakladka "Z promptu")
i testy wolaja zbuduj(). Wynik ma prompt ZAMROZONY w pomysle - generacja i wznawianie po restarcie uzywaja tego samego tekstu.

Zasady (sprawdzone na przewodniku Seedance 2.5 i na rolkach usera z 6.10, PROJEKT rolka_z_promptu):
- obrazy w kolejnosci --image: referencje/ persony (01_, 02_...), na koncu zdjecie stroju (gdy jest). Seedance dostaje w prompcie
  tokeny <<<image_N>>> (tak zapisuje je apka Higgsfield), Wan / Gemini - bez numerow ("the reference photos");
- prawdziwe, rozpoznawalne polskie miejsca (MIEJSCA) i wyglad nagrania z telefonu, nie z lustrzanki (opisy pozytywne);
- komentarz zza kamery po polsku RAZ, w klamrach, po "Dialogue language: Polish." (inaczej model dorabia napisy / chinski);
- bez nazw marek sklepow i postaci (filtr IP Higgsfielda), bez slow z fabryka.SLOWA_RYZYKOWNE (filtr NSFW); prawdziwe NAZWY
  galerii/dworcow/dzielnic (OBIEKTY, `nazwy: "prawdziwe"`) albo bez nazw (`"opisowe"` - bezpieczny zapas, gdy filtr IP odrzuci);
- wlosy do wyboru per rolka (domyslnie wlasne ze zdjec), zmiana wlosow nie zmienia twarzy; wzrost persony z profilu (wzrost_cm);
- (zp-2, feedback usera 2026-10-07) odwazne, przyciagajace wzrok stroje (STROJE_ODWAZNE, legalna moda uliczna), kamera z ukrycia
  (KAMERY_UKRYTE: z daleka, z biodra, zza filaru - nigdy nie podchodzi), subtelne reakcje zdziwienia (REAKCJE_ZDZIWIENIE + polskie
  linie), glos komentarza: `glos` "model" (mowi model wideo; `wymowa: "fonetyczna"` = ą/ę zapisane tak, jak sie je czyta) albo
  "tts" (wideo tylko z dzwiekiem otoczenia, komentarz ElevenLabs dogrywa komentarz_glos.py po generacji).
"""
import os
import random
import re
import unicodedata
from datetime import date

import baza

WERSJA_SZABLONU = "zp-2"

# ---------------- modele (wszystkie przez CLI Higgsfield, wyceny `generate cost` z 2026-10-07) ----------------

MODELE = {
    "seedance_2_5": {
        "nazwa": "Seedance 2.5 – najlepszy", "opis": "najlepsza twarz i polska mowa; 10 s 720p ≈ 70 kr, 8 s 1080p ≈ 96 kr",
        "mode": "omni_reference", "szablon": "pelny", "tokeny": True, "max_obrazow": 30,
        "dlugosci": (8, 10, 15), "rozdzielczosci": ("480p", "720p", "1080p"),
        "parametry": {"bitrate_mode": "high"}, "generate_audio": True, "limit_znakow": 8000, "zalecane_znaki": 5000,
    },
    "wan3_0_prime": {
        "nazwa": "Wan 3.0 Prime – taniej", "opis": "ok. 2,3× taniej (10 s 720p ≈ 30 kr); twarz i polska mowa do sprawdzenia",
        "mode": None, "szablon": "krotki", "tokeny": False, "max_obrazow": 10,
        "dlugosci": (8, 10, 15), "rozdzielczosci": ("480p", "720p", "1080p"),
        "parametry": {}, "generate_audio": True, "limit_znakow": 5000, "zalecane_znaki": 3000,
    },
    "gemini_omni_flash_1_1": {
        "nazwa": "Gemini Omni Flash – taniej, max 10 s", "opis": "10 s 720p ≈ 30 kr, najtańsze 1080p; max 7 zdjęć",
        "mode": "reference-to-video", "szablon": "krotki", "tokeny": False, "max_obrazow": 7,
        "dlugosci": (8, 10), "rozdzielczosci": ("720p", "1080p"),
        "parametry": {}, "generate_audio": None, "limit_znakow": 4000, "zalecane_znaki": 2600,
    },
}
MODEL_DOMYSLNY = "seedance_2_5"
DLUGOSC_DOMYSLNA = 10
PROG_1080P_S = 8          # zasada fabryki: <= 8 s -> 1080p, dluzsze -> 720p (fabryka.PROG_1080P_S)


def rozdzielczosc_auto(dlugosc, model=MODEL_DOMYSLNY):
    """<= 8 s -> 1080p, dluzsze -> 720p (gdy model nie ma 1080p/720p - najblizsza, ktora ma)."""
    r = "1080p" if float(dlugosc) <= PROG_1080P_S else "720p"
    dozwolone = MODELE.get(model, MODELE[MODEL_DOMYSLNY])["rozdzielczosci"]
    return r if r in dozwolone else dozwolone[-1]


# ---------------- pory roku, pory dnia ----------------

SEZONY = {
    "wiosna": {"nazwa": "Wiosna", "en": "spring", "pogoda": "Mild spring weather, fresh green leaves on the trees.",
               "ubrania": "light jackets, hoodies, trench coats, jeans and sneakers"},
    "lato": {"nazwa": "Lato", "en": "summer", "pogoda": "Warm summer weather.",
             "ubrania": "T-shirts, shorts, summer dresses, sandals and sneakers"},
    "jesien": {"nazwa": "Jesień", "en": "autumn", "pogoda": "A grey, overcast autumn day: damp pavements, yellow and brown leaves.",
               "ubrania": "puffer and parka jackets, hoodies, scarves, jeans and sneakers"},
    "zima": {"nazwa": "Zima", "en": "winter",
             "pogoda": "A cold grey winter day: dirty slush and a little snow along the kerbs, bare trees.",
             "ubrania": "thick winter coats, puffer jackets, wool hats, scarves and boots"},
}
PORY_DNIA = {"rano": ("Rano", "morning"), "popoludnie": ("Po południu", "afternoon"), "wieczor": ("Wieczorem", "evening")}
WIECZOR_NA_ZEWNATRZ = ("after dusk: orange and white street lamps and lit shop windows, deep shadows with clearly visible "
                       "phone noise")


def sezon_z_daty(d=None):
    m = (d or date.today()).month
    return "wiosna" if m in (3, 4, 5) else "lato" if m in (6, 7, 8) else "jesien" if m in (9, 10, 11) else "zima"


# ---------------- wlosy (domyslnie wlasne ze zdjec persony) ----------------
# kolor: (etykieta PL, opis EN albo None = wlasny, [fryzura], [grzywka] - gotowy zestaw, gdy uzytkownik nie wybral osobno)

WLOSY_KOLORY = {
    "wlasne": ("Jej własne – jak na zdjęciach", None),
    "platyna": ("Platynowy blond", "pale platinum blonde"),
    "rozowe_pastel": ("Pastelowy róż", "soft pastel pink"),
    "rozowe_mocne": ("Mocny róż", "vivid hot-pink"),
    "blekit_pastel": ("Pastelowy błękit", "pastel baby-blue"),
    "miku": ("Turkusowe długie kucyki z grzywką (jak Miku)", "bright turquoise-teal", "dwa_kucyki_dlugie", "prosta"),
    "turkus": ("Turkus", "bright turquoise-teal"),
    "czarne": ("Kruczoczarne", "glossy jet-black"),
    "srebrne": ("Srebrne / białe", "silvery icy white"),
    "czerwone": ("Wiśniowa czerwień", "deep cherry-red"),
    "rude": ("Rude (miedziane)", "natural copper-ginger"),
    "lawenda": ("Lawendowe", "pastel lavender"),
    "brazowe": ("Ciemny brąz", "dark chocolate-brown"),
    "czarno_rozowe": ("Dwukolorowe: pół czarne, pół różowe", "two-tone split dye: the left half jet-black, the right half bright pink"),
    "czarne_rozowy_spod": ("Czarne z różowym spodem", "jet-black with a hidden bright pink underlayer that shows when she moves"),
    "blond_rozowe_konce": ("Blond z różowymi końcówkami", "light blonde with the last 10 cm dyed pastel pink"),
    "czarne_jasne_pasma": ("Czarne z jasnymi pasmami z przodu", "jet-black with two bright blonde face-framing streaks at the front"),
}
WLOSY_FRYZURY = {
    "wlasna": ("Jak na zdjęciach", None),
    "rozpuszczone": ("Długie, rozpuszczone, proste", "long, loose and straight, falling well below the shoulders"),
    "fale": ("Luźne fale", "long with soft loose waves"),
    "kucyk": ("Wysoki kucyk", "pulled back into a high ponytail"),
    "dwa_kucyki": ("Dwa kucyki", "in two high pigtails tied above the ears"),
    "dwa_kucyki_dlugie": ("Dwa bardzo długie kucyki", "in two very long high twin tails tied above the ears, reaching down to her thighs"),
    "dwa_koki": ("Dwa koki na czubku głowy", "in two small round buns on top of her head, with a few loose strands"),
    "warkocze": ("Dwa warkocze", "in two long plaits over her shoulders"),
    "kok": ("Niedbały kok", "in a messy bun on top of her head with loose face-framing strands"),
    "bob": ("Krótki bob do brody", "cut into a sleek chin-length bob"),
    "wilk": ("Cieniowane, puszyste (wolf cut)", "in a shaggy layered wolf cut, shoulder length"),
}
WLOSY_GRZYWKI = {
    "wlasna": ("Jak na zdjęciach", None),
    "prosta": ("Prosta grzywka", "with blunt straight bangs covering her eyebrows"),
    "firanka": ("Grzywka firanka", "with soft curtain bangs parted in the middle"),
    "bez": ("Bez grzywki", "with no bangs, her forehead visible"),
}

# ---------------- stroje ----------------

STROJE_TRYBY = {
    "odwazny": "Odważny, przyciąga wzrok (losowy)",
    "zdjecia": "Jak na jej zdjęciach",
    "codzienny": "Codzienny, w jej stylu (losowy)",
    "cosplay": "Cosplay (losowy) – tylko gdy chcesz",
    "wlasny": "Własny opis",
}
# Odwazne, ekscentryczne stroje do rolek "ludzie reaguja" (feedback usera 2026-10-07): bardzo krotkie spodniczki, glebokie dekolty,
# dziwne zestawienia - ale LEGALNA moda uliczna (zero nagosci, zero bielizny na wierzchu). Opisy bez slow z fabryka.SLOWA_RYZYKOWNE
# ("mini skirt", "tight dress", "cleavage", "sheer", "mesh", "lace"...) - filtr NSFW. id -> (etykieta PL, opis EN, pory roku)
STROJE_ODWAZNE = {
    "krata_futerko": ("Krótka spódniczka w czerwoną kratę + różowa kurtka z futerkiem",
                      "a very short red tartan pleated skirt, a fitted black long-sleeve top with a low square neckline, a cropped "
                      "fluffy hot-pink faux-fur jacket, black opaque tights and knee-high black patent platform boots",
                      ("jesien", "zima", "wiosna")),
    "panterka": ("Płaszcz w panterkę + krótka skórzana spódniczka",
                 "a long leopard-print faux-fur coat worn open over a black top with a deep V-neck, a very short black leather "
                 "skirt and black over-the-knee boots", ("jesien", "zima")),
    "srebrna_kurtka": ("Krótka srebrna kurtka + plisowana spódniczko-spodenki",
                       "a cropped shiny metallic-silver puffer jacket, a white ribbed top with a low scoop neckline, a very short "
                       "black pleated skort, black opaque tights and chunky silver platform sneakers", ("jesien", "zima")),
    "rozowy_sweterek": ("Różowy puszysty sweterek w serek + biała jeansowa spódniczka",
                        "a fluffy baby-pink cardigan buttoned low with a deep V-neck, a very short white denim skirt and white "
                        "knee-high boots", ("wiosna", "jesien")),
    "krowie_laty": ("Kurtka w krowie łaty + różowa spódniczka i podkolanówki w paski",
                    "a cropped cow-print faux-fur jacket, a fitted pink top with a low neckline, a very short pink pleated skirt, "
                    "black-and-white striped knee-high socks and white platform boots", ("jesien", "wiosna", "zima")),
    "czerwony_trencz": ("Czerwony lakierowany trencz jako sukienka + czerwone kozaki",
                        "a short belted cherry-red patent-leather trench coat worn as a dress with a low neckline, glossy red "
                        "over-the-knee boots and small black sunglasses", ("wiosna", "jesien")),
    "blezer_sukienka": ("Limonkowa marynarka jako krótka sukienka",
                        "an oversized lime-green blazer worn as a very short dress, cinched with a wide black belt and buttoned "
                        "low, black opaque tights and pointed black heeled boots", ("wiosna", "jesien")),
    "cekiny_w_dzien": ("Złoty cekinowy top w biały dzień + krótka spódniczka",
                       "a sparkly gold sequinned party top with a low neckline worn in broad daylight, a very short black pleated "
                       "skirt, a long camel coat worn open, black opaque tights and chunky boots", ("jesien", "zima")),
    "pomaranczowa_dzianina": ("Pomarańczowa krótka sukienka z dzianiny + czapka do kompletu",
                              "a bright orange fitted knit dress ending high above the knee with a low square neckline, a "
                              "matching orange beanie, orange knee-high socks and black platform sneakers", ("jesien", "zima")),
    "pastelowy_komplet": ("Pastelowy różowy komplet: krótki sweterek i spódniczka",
                          "a pastel-pink knitted two-piece: a cropped fitted cardigan with a deep V-neck and a matching very "
                          "short knit skirt, white over-the-knee socks and fluffy white boots", ("jesien", "zima", "wiosna")),
    "bialy_komplet": ("Cała na biało: futerko, krótkie spodenki, kozaki",
                      "an all-white outfit: a cropped white faux-fur jacket, a white ribbed top with a low neckline, very short "
                      "white shorts over white opaque tights and white knee-high boots", ("jesien", "zima")),
    "moro": ("Moro: krótka spódniczka + glany",
             "a cropped camouflage jacket, a black tank top with a low neckline, a very short camouflage skirt, black opaque "
             "tights and chunky black combat boots", ("wiosna", "jesien")),
    "varsity": ("Kurtka baseballowa + spódniczka w kratę z łańcuchem",
                "a purple-and-yellow cropped varsity jacket, a white fitted top with a low neckline, a very short grey plaid "
                "skirt with a chunky silver chain belt, white knee-high socks and black platform loafers", ("wiosna", "jesien")),
    "baletowa_spodniczka": ("Bufiasta różowa spódniczka + skórzana ramoneska",
                            "a puffy layered pink ruffle skirt ending high above the knee, a black leather biker jacket, a "
                            "black top with a low neckline, black opaque tights and chunky black boots", ("wiosna", "jesien")),
    "neon": ("Neonowo-zielony komplet: krótka bluza i bojówki",
             "a neon-green cropped zip-up jacket worn open over a black top with a low neckline, neon-green low-rise cargo "
             "trousers, a chunky chain necklace and huge white platform sneakers", ("wiosna", "lato", "jesien")),
    "futro_kozaki": ("Długie białe futerko + krótka czarna sukienka + kozaki",
                     "a long white faux-fur coat worn open over a very short black knit dress with a low neckline, a huge black "
                     "faux-fur hat and black thigh-high boots", ("zima",)),
    "zolty_top": ("Żółty top z odkrytymi plecami + krótkie jeansowe szorty",
                  "a bright yellow halter top with an open back, very short frayed denim shorts, white platform sandals and a "
                  "tiny green handbag", ("lato",)),
    "groszki": ("Czerwona sukienka w groszki na ramiączkach",
                "a red polka-dot sundress with thin straps and a low neckline, ending high above the knee, white platform "
                "sneakers and a straw bucket hat", ("lato", "wiosna")),
    "kwiatowy_kombinezon": ("Kwiecisty krótki kombinezon z dekoltem w serek",
                            "a floral very short playsuit with a deep V-neck, white platform sandals and big gold hoop earrings",
                            ("lato",)),
}


def stroje_odwazne_na(sezon):
    """Id odwaznych strojow pasujacych do pory roku (gdy zaden - wszystkie)."""
    return [k for k, v in STROJE_ODWAZNE.items() if sezon in v[2]] or list(STROJE_ODWAZNE)
# codzienne ubrania w stylu person (alternatywny / e-girl na co dzien - czarne, platformy), z porami roku
STROJE_CODZIENNE = [
    ("a black oversized hoodie, loose black cargo trousers and chunky black platform sneakers", ("wiosna", "jesien")),
    ("a black leather biker jacket over a black long-sleeve top, wide-leg black jeans, chunky platform boots and a thin silver "
     "chain necklace", ("wiosna", "jesien")),
    ("a long black wool coat, a black turtleneck, black wide trousers and black platform boots", ("jesien", "zima")),
    ("a grey oversized sweatshirt, straight black jeans, black-and-white canvas high-top sneakers and a small black backpack",
     ("wiosna", "jesien")),
    ("a black puffer jacket, a black knitted beanie, black jeans and chunky black boots", ("jesien", "zima")),
    ("a long black knitted cardigan over a black knee-length dress, black opaque tights and black platform shoes",
     ("wiosna", "jesien")),
    ("a plain black T-shirt, a black pleated skirt to the knee, white knee-high socks and black platform loafers", ("lato", "wiosna")),
    ("a white T-shirt under a black corduroy jacket, baggy light-grey jeans and black platform sneakers", ("wiosna", "jesien")),
    ("a black zip-up hoodie, a black pleated skirt to the knee, black opaque tights and chunky boots", ("jesien",)),
    ("a loose black linen shirt over a black tank top, wide black trousers and black platform sandals", ("lato",)),
    ("a dark-grey hoodie, black joggers, black sneakers and a canvas tote bag on her shoulder",
     ("wiosna", "lato", "jesien", "zima")),
    ("an oversized denim jacket, a black long-sleeve top, black flared jeans and platform boots", ("wiosna", "jesien")),
    ("a black parka with a fur-trimmed hood, black jeans and black snow boots", ("zima",)),
    ("a black knitted sweater, a long black maxi skirt, chunky black boots and silver rings", ("jesien", "zima")),
    ("a black T-shirt with a faded unreadable print, black denim shorts over black opaque tights and platform boots",
     ("lato", "wiosna")),
]
# cosplay - tylko na zyczenie (domyslnie wylaczony), opisowo, bez nazw postaci (filtr IP)
STROJE_COSPLAY = [
    "a yellow electric-mouse costume with black-tipped pointy ears and a zigzag tail",
    "a black-and-white frilly maid costume with a white apron and a frilly white headband",
    "a teal-and-purple striped cat costume with fluffy ears and a long striped tail",
    "a headband with small red horns, a white shirt with a black tie and black trousers",
    "a black bunny costume with a long-eared headband, white cuffs and a black ruffled skirt to the knee",
    "a navy sailor-style school uniform with a red neckerchief and a pleated navy skirt to the knee",
    "a witch costume: a pointy black hat, a long black cape and a broom in her hand",
    "a fluffy white sheep onesie with a hood with little ears",
    "a pastel-pink magical-girl dress with a big bow and a toy wand",
]

# ---------------- reakcje ludzi, komentarze zza kamery, kamera ----------------

REAKCJE = {
    "losowa": ("Dobierz do pomysłu", None),
    "smiech": ("Ktoś się śmieje", "a woman standing nearby covers her mouth to hide a laugh, and her friend turns away giggling"),
    "gapienie": ("Ludzie się gapią", "several people turn their heads and stare for a moment; one man slows down to keep looking"),
    "krzywo": ("Krzywe spojrzenia", "an older woman looks her up and down with a disapproving frown and shakes her head; a man nearby "
                                   "smirks"),
    "nagrywa": ("Ktoś też ją nagrywa", "a teenager nearby secretly films her on his own phone too, grinning"),
    "szept": ("Szepczą i chichoczą", "two friends whisper to each other, glance at her and giggle"),
    "brak": ("Nikt nie reaguje", "nobody pays her any special attention; people simply walk past"),
    # zdziwienie / szok "jak mozna tak chodzic" (prosba usera 2026-10-07) - subtelnie i wiarygodnie, bez pokazywania palcem
    "dwa_razy": ("Ktoś się odwraca drugi raz i staje",
                 "a man walking past glances at her, takes two more steps, then does a double take, stops for a second and "
                 "stares at her outfit with raised eyebrows before slowly moving on"),
    "para_kreci_glowa": ("Starsza para wymienia spojrzenia i kręci głową",
                         "an older couple walking arm in arm exchange a long look; the woman purses her lips and slowly shakes "
                         "her head, the man keeps glancing back over his shoulder"),
    "szturcha_kolege": ("Chłopak szturcha kolegę łokciem",
                        "a young man nudges his friend with his elbow and tilts his head towards her; the friend turns, stares "
                        "for a second with his mouth slightly open, then looks away grinning"),
    "kasjerka_zamiera": ("Kasjerka zamiera w pół ruchu",
                         "the cashier freezes mid-scan with a product still in her hand, stares at her outfit for a second, "
                         "then blinks and carries on scanning"),
    "mama_odciaga": ("Mama odciąga dziecko na bok",
                     "a mother walking with a small child stares at her, then gently pulls the child closer to her side and "
                     "walks on, glancing back once"),
    "szepcze_patrzac": ("Ktoś szepcze do koleżanki, patrząc na nią",
                        "a woman leans to her friend and whispers something without taking her eyes off her; the friend looks "
                        "over and her eyebrows go up"),
}
REAKCJE_ZDZIWIENIE = ("dwa_razy", "para_kreci_glowa", "szturcha_kolege", "kasjerka_zamiera", "mama_odciaga", "szepcze_patrzac")
SUBTELNE_REAKCJE = (" The reactions are subtle and believable: short stares, raised eyebrows, a small head shake; nobody points, "
                    "laughs out loud or speaks to her.")
# krotkie polskie komentarze zza kamery pasujace do reakcji zdziwienia (bez ą/ę na koncu wyrazow - model wideo czyta je lepiej)
LINIE_REAKCJI = {
    "dwa_razy": ["Widziałaś to?", "Jak ona może tak chodzić?", "No ja nie mogę…"],
    "para_kreci_glowa": ["Jak ona może tak chodzić?", "No ja nie mogę…", "Widziałaś to?"],
    "szturcha_kolege": ["Widziałeś to?", "Ej, patrz na nią.", "No ja nie mogę…"],
    "kasjerka_zamiera": ["No ja nie mogę…", "Widziałaś to?", "Jak ona może tak chodzić?"],
    "mama_odciaga": ["Jak ona może tak chodzić?", "Widziałaś to?"],
    "szepcze_patrzac": ["Widziałaś to?", "No ja nie mogę…", "Jak ona może tak chodzić?"],
}
KOMENTARZE = ["Jak ona wygląda.", "Patrz, patrz…", "Co ona ma na sobie?", "O matko…", "Zobacz, zobacz…", "Teraz tak się chodzi?",
              "Ej, patrz na nią.", "No to mamy cyrk.", "Ale odwaga.", "Serio tak wyszła z domu?", "Ja bym tak nie wyszła.",
              "Jak ona może tak chodzić?", "Widziałaś to?", "Widziałeś to?", "No ja nie mogę…",
              "Widziałaś to? Jak ona wygląda…"]
KOMENTARZE_COSPLAY = ["Halloween już był.", "Gdzie jest ten konwent?"]

# Glos komentarza zza kamery: kto go "mowi" (feedback usera: model wideo przekreca polskie ą - "wyględa" zamiast "wygląda")
GLOSY = {
    "auto": "Automatycznie (ElevenLabs, gdy jest dobry klucz; inaczej model)",
    "tts": "Dograny po generacji (ElevenLabs v3, poprawna polszczyzna)",
    "model": "Mówi model wideo (bywa zła wymowa ą/ę)",
}
WYMOWY = {"fonetyczna": "ą/ę zapisane tak, jak się je czyta (model mówi lepiej)", "zwykla": "zwykła pisownia"}
NAZWY_TRYBY = {"prawdziwe": "Prawdziwe nazwy (np. Posnania, Złote Tarasy)", "opisowe": "Bez nazw (bezpieczniej dla filtra IP)"}


def fonetycznie(tekst):
    """Polski tekst -> zapis "tak, jak sie czyta" dla modelu wideo (ą/ę): wygląda -> wyglonda, idą -> idom, mogę -> moge, się -> sie,
    zęby -> zemby. Uzywane tylko w {komentarzu} dla modelu wideo (ElevenLabs dostaje poprawna pisownie)."""
    def zamien(m):
        slowo = m.group(0)
        wynik = []
        for i, c in enumerate(slowo):
            nast = slowo[i + 1].lower() if i + 1 < len(slowo) else ""
            if c.lower() not in "ąę":
                wynik.append(c)
                continue
            samog = "o" if c.lower() == "ą" else "e"
            if not nast:
                wynik.append("om" if samog == "o" else "e")          # idą -> idom, mogę -> moge
            elif nast in "bp":
                wynik.append(samog + "m")                            # zęby -> zemby, kąpie -> kompie
            elif nast in "lł":
                wynik.append(samog)                                  # wzięli -> wzieli
            else:
                wynik.append(samog + "n")                            # wygląda -> wyglonda, ręka -> renka
            if c.isupper():
                wynik[-1] = wynik[-1].capitalize()
        return "".join(wynik)
    tekst = re.sub(r"\b[Ss]ię\b", lambda m: m.group(0)[0] + "ie", tekst or "")
    return re.sub(r"\w*[ąęĄĘ]\w*", zamien, tekst)


KAMERY = {
    "idzie_za": ("Ktoś idzie za nią", "walking a few metres behind her",
                 "First a wide view from 5-6 m while the person filming walks slowly closer; at about {t1} s they stop 2-3 m away "
                 "at her side, so the shot becomes a medium side view; near the end they step back a little."),
    "z_daleka_zoom": ("Z daleka, powolny zoom", "standing still far away, 10-15 m from her",
                      "The person filming never moves from one spot; the only movement is a slow, slightly jerky 2x phone zoom "
                      "towards her starting at about {t1} s; she never becomes a close-up."),
    "mija": ("Ktoś ją mija", "walking past her at normal speed",
             "The phone is held low at chest height and turned towards her as the person filming walks past, as if they were "
             "not filming; the angle changes from front-side to side to back."),
    "stoi_obok": ("Ktoś stoi kilka metrów obok", "standing 3-4 m away",
                  "The person filming stays in place and only turns the phone to keep her in frame, sometimes losing her for a "
                  "moment behind passers-by."),
    "siedzi_naprzeciw": ("Siedzi naprzeciwko (tramwaj, pociąg)", "sitting a few seats away from her",
                         "The phone rests low near their lap, tilted up at her; the view shakes with the vehicle and is partly "
                         "blocked by other passengers' shoulders."),
    "kolejka": ("Stoi za nią w kolejce (ukradkiem)", "standing two people behind her in the queue",
                "The phone is held at chest height between other people's shoulders; at about {t1} s the person filming leans "
                "sideways once to get a clearer view."),
    # z ukrycia (feedback usera 2026-10-07): tak wygladaja prawdziwe nagrania "ludzie reaguja" - nagrywajacy udaje, ze nie nagrywa,
    # telefon nisko, czesc kadru zaslonieta, z daleka, lekki zoom, nigdy nie podchodzi
    "ukradkiem": ("Ukradkiem z daleka (udaje, że pisze SMS-a)", "standing still 6-10 m away, pretending to read their own phone",
                  "The phone is held low at chest-to-waist height and tilted up a little, as if they were only texting; the frame "
                  "is slightly crooked and she drifts off-centre; at about {t1} s a slow, slightly jerky 1.5x digital zoom "
                  "towards her; she stays a small-to-medium figure in the frame and never becomes a close-up."),
    "zza_filaru": ("Zza filaru / regału, z daleka", "half hidden behind a pillar (or the end of a shelf) 6-8 m away",
                   "The blurred edge of the pillar or shelf, very close to the lens, covers one side of the frame; the phone "
                   "peeks out at chest height; at about {t1} s a short 2x digital zoom; the person filming stays hidden and does "
                   "not move."),
    "z_biodra": ("Z biodra, w przejściu", "walking slowly past her 4-6 m away with the phone held low at hip height",
                 "The lens points at her as if by accident: the horizon is tilted, the top of her head is sometimes cut off, and "
                 "a passer-by's shoulder briefly covers half of the frame; the person filming never stops next to her."),
}
KAMERY_UKRYTE = ("ukradkiem", "zza_filaru", "z_biodra", "kolejka", "siedzi_naprzeciw")


def kamera_ukryta(miejsce_id):
    """Domyslna kamera z ukrycia dla miejsca (nigdy nie podchodzi): kolejka/siedzi naprzeciw zostaja, wnetrza - zza filaru,
    ulice i przejscia - z biodra, reszta - ukradkiem z daleka."""
    m = MIEJSCA.get(miejsce_id) or {}
    k = m.get("kamera")
    if k in ("kolejka", "siedzi_naprzeciw"):
        return k
    if m.get("wnetrze"):
        return "zza_filaru"
    if k in ("mija", "idzie_za"):
        return "z_biodra"
    return "ukradkiem"

# ---------------- katalog prawdziwych polskich miejsc ----------------
# Pola: nazwa (PL, panel), kat, krotko (EN, "in ..."), opis, detale, swiatlo, dzwieki, akcje (3 beaty domyslnego pomyslu),
# reakcje, kamera, streszczenie, slowa (rdzenie PL bez ogonkow - wykrywanie miejsca w pomysle), wnetrze, pory, sezony, operator.
# Bez nazw marek: sklepy opisane wygladem (filtr IP). Napisy "too far to read" - model psuje litery.

KATEGORIE = ["Osiedle i blok", "Sklepy i jedzenie", "Komunikacja", "Znane miejsca w miastach", "Parki, woda, góry"]

MIEJSCA = {
    # ---------- osiedle i blok ----------
    "osiedle": {
        "nazwa": "Osiedle z wielkiej płyty (pod blokami)", "kat": "Osiedle i blok",
        "krotko": "a housing estate of prefab blocks of flats",
        "opis": "A typical Polish housing estate (osiedle) of ten-storey 1970s prefab concrete blocks (wielka płyta), later "
                "insulated and painted in faded pastel colours, with long rows of balconies, some glazed, some with corrugated "
                "plastic panels.",
        "detale": "satellite dishes and drying laundry on balconies, a metal carpet-beating frame (trzepak), a fenced playground on "
                  "rubber tiles, a brick bin shelter, worn benches, a yellow parcel locker by the path, older cars with white "
                  "Polish number plates parked half on the kerb, patchy lawns",
        "swiatlo": "flat daylight between the blocks, sun reflecting off a few windows",
        "dzwieki": "kids on the playground, a dog barking, a car door, pigeons, a distant bus",
        "akcje": ["she walks along the pavement between the blocks, scrolling her phone",
                  "she stops at the yellow parcel locker, taps her phone and a locker door pops open",
                  "she takes out a small parcel, tucks it under her arm and walks on towards a stairwell door"],
        "streszczenie": "{IMIE} picks up a parcel from a parcel locker between the blocks while neighbours stare.",
        "reakcje": "two elderly ladies on a bench exchange looks and one of them shakes her head; a boy on a scooter rides past "
                   "and stares",
        "kamera": "z_daleka_zoom", "slowa": ("blok", "osiedl", "paczkomat", "trzepak", "wielka plyt"),
    },
    "klatka": {
        "nazwa": "Klatka schodowa w bloku", "kat": "Osiedle i blok", "wnetrze": True,
        "krotko": "the stairwell of an old block of flats",
        "opis": "The stairwell of an old Polish block of flats: worn terrazzo stairs with a metal handrail, walls painted with "
                "glossy oil paint, pale green on the lower half and white above, a row of dented metal mailboxes by the entrance.",
        "detale": "an intercom panel with numbered buttons, handwritten notices from the housing cooperative on a cork board, a "
                  "pram parked under the stairs, scuffed doormats in front of flat doors, a landing window with a dusty radiator",
        "swiatlo": "dim cold light from a motion-sensor lamp mixed with grey daylight from the landing window",
        "dzwieki": "echoing footsteps, the heavy entrance door slamming, the hum of the lift, a TV muffled behind a door",
        "akcje": ["she comes in through the heavy entrance door with a shopping bag and opens her mailbox",
                  "she pulls out a few letters and leaflets and flips through them",
                  "she starts climbing the stairs, her shoes echoing in the stairwell"],
        "streszczenie": "{IMIE} comes home to her block, checks her mailbox and climbs the stairs while a neighbour stares.",
        "reakcje": "a neighbour in a tracksuit coming down with a rubbish bag stops for a second and stares; an elderly lady opens "
                   "her door a crack to look",
        "kamera": "stoi_obok", "operator": "standing half a flight of stairs below her",
        "slowa": ("klatk", "klatc", "schod", "skrzynk", "sasiad"),
    },
    "sklep_osiedlowy": {
        "nazwa": "Sklepik pod blokiem (jak Żabka)", "kat": "Osiedle i blok", "wnetrze": True,
        "krotko": "a small convenience store under a block of flats",
        "opis": "A small Polish chain convenience store on the ground floor of a block of flats: a green-and-white shop front "
                "covered in promo posters, narrow aisles, fridges full of drinks, a hot-dog roller grill and a coffee machine "
                "next to the till, a self-checkout terminal.",
        "detale": "a shelf of parcel pick-ups behind the counter, racks of crisps and sweets, a cashier in a uniform T-shirt, a "
                  "bike rack and a bin outside the door",
        "swiatlo": "bright white shop light, grey daylight through the posters on the windows",
        "dzwieki": "the door chime, fridges humming, the till beeping, the coffee machine grinding",
        "akcje": ["she takes a can of drink from the fridge and a hot dog from the counter",
                  "she pays at the self-checkout by tapping her phone",
                  "she walks out through the sliding door, taking a first bite"],
        "streszczenie": "{IMIE} buys a hot dog and a can of drink in a small shop under a block while two lads stare.",
        "reakcje": "two lads in tracksuits by the drinks fridge nudge each other and grin; the cashier looks up a second too long",
        "kamera": "kolejka", "slowa": ("zabk", "zabc", "sklepik", "sklep pod", "sklep osiedl", "hot dog", "hot-dog", "hotdog"),
    },
    "silownia_plenerowa": {
        "nazwa": "Siłownia plenerowa na osiedlu", "kat": "Osiedle i blok",
        "krotko": "an outdoor gym on a housing estate",
        "opis": "A free outdoor gym (siłownia plenerowa) between blocks of flats: a row of sturdy metal exercise machines painted "
                "in bright colours on rubber flooring, next to a park alley and a basketball hoop.",
        "detale": "an information board with exercise pictograms, a bench, a bin, a few pensioners exercising slowly, apartment "
                  "blocks in the background",
        "swiatlo": "open daylight with soft shadows",
        "dzwieki": "the squeak and clank of the metal machines, birds, distant traffic, a dog barking",
        "akcje": ["she steps onto a walking machine and starts swinging her legs slowly",
                  "she checks her phone while still swinging, completely unbothered",
                  "she hops off and tries the twisting machine next to it"],
        "streszczenie": "{IMIE} tries the machines of an outdoor gym between the blocks next to a pensioner.",
        "reakcje": "a pensioner in a tracksuit on the next machine stops and watches her with raised eyebrows; two teenagers on a "
                   "bench laugh quietly",
        "kamera": "stoi_obok", "slowa": ("silowni", "cwicz", "orbitrek", "trening"),
    },
    "orlik": {
        "nazwa": "Boisko Orlik przy szkole", "kat": "Osiedle i blok",
        "krotko": "an Orlik football pitch next to a school",
        "opis": "A fenced artificial-turf football pitch of the Polish 'Orlik' type next to a school: tall green ball-stop nets, "
                "floodlight poles, a small changing-room building and a multi-sport court beside it.",
        "detale": "teenagers playing football in hoodies, backpacks thrown by the fence, a water bottle on the line, school "
                  "windows behind",
        "swiatlo": "open daylight over the pitch",
        "dzwieki": "a ball hitting the net, shouts in Polish, a whistle, sneakers squeaking on rubber",
        "akcje": ["she walks along the outside of the fence with her phone in her hand",
                  "the ball flies over the fence and rolls to her feet; she stops it with her shoe",
                  "she kicks it back clumsily over the fence and walks on"],
        "streszczenie": "{IMIE} walks past a school football pitch and has to kick the ball back to the boys.",
        "reakcje": "the boys stop playing and stare; one of them shouts a thank-you and the others laugh",
        "kamera": "z_daleka_zoom", "slowa": ("orlik", "boisk", "pilk"),
    },
    "dzialki": {
        "nazwa": "Ogródki działkowe", "kat": "Osiedle i blok",
        "krotko": "allotment gardens on the edge of a city",
        "opis": "Polish allotment gardens (działki): small plots behind wire fences, wooden summer sheds, vegetable beds, fruit "
                "trees, plastic garden chairs and a narrow gravel lane between the plots.",
        "detale": "a garden gnome, a barbecue grill, a watering can, a rain barrel, tomato plants tied to sticks, an elderly man "
                  "in a cap working with a hoe",
        "swiatlo": "soft daylight through fruit trees",
        "dzwieki": "birds, a lawnmower in the distance, a dog barking, a radio voice from a shed",
        "akcje": ["she walks down the gravel lane between the plots, looking around",
                  "she stops at a fence and looks at the ripe tomatoes and apples",
                  "an old man hands her an apple over the fence and she takes it, smiling"],
        "streszczenie": "{IMIE} walks through allotment gardens and an old gardener hands her an apple over the fence.",
        "reakcje": "the old gardener stares for a long moment before offering the apple; his wife peeks out of the shed",
        "kamera": "z_daleka_zoom", "slowa": ("dzialk", "dzialc", "ogrodk", "ogrod"),
    },
    # ---------- sklepy i jedzenie ----------
    "dyskont": {
        "nazwa": "Dyskont (jak Biedronka / Lidl)", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a discount supermarket",
        "opis": "A big Polish discount supermarket: wide aisles with goods on pallets, a bakery corner with self-service bread "
                "bins and paper bags, fruit and vegetables in crates, a long row of checkouts with conveyor belts.",
        "detale": "a bottle-and-can deposit return machine by the entrance, red-and-yellow price labels with prices in zł, promo "
                  "leaflets, trolleys with coin locks, stacks of plastic baskets, cashiers in uniform polo shirts",
        "swiatlo": "flat cool fluorescent ceiling light, slightly greenish, with daylight from the glass entrance",
        "dzwieki": "scanner beeps, rustling plastic bags, a rattling trolley, the hum of fridges, a short shop announcement",
        "akcje": ["she waits in the checkout queue holding a plastic basket with bread rolls and a bottle of water",
                  "she puts the things on the conveyor belt and takes out her phone",
                  "she pays by holding the phone to the terminal and packs the rolls into her bag"],
        "streszczenie": "{IMIE} waits in a checkout queue with a basket while the cashier and an old lady stare.",
        "reakcje": "the cashier looks at her a second too long; an elderly lady behind her raises her eyebrows; a man at the next "
                   "checkout smirks",
        "kamera": "kolejka", "slowa": ("biedron", "lidl", "dyskont", "dyskonc", "market", "kasie", "kasjer", "zakupy", "koszyk"),
    },
    "drogeria": {
        "nazwa": "Drogeria (jak Rossmann)", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a busy drugstore",
        "opis": "A busy Polish drugstore: long bright white aisles of shampoos, hair dyes and cosmetics, a make-up stand with "
                "testers and small round mirrors, red promo signs hanging from the ceiling.",
        "detale": "shopping baskets, security gates at the entrance, a queue at the tills, staff restocking shelves, price tags "
                  "in zł",
        "swiatlo": "very bright white shop lighting with glossy reflections on the floor",
        "dzwieki": "the till beeping, a security gate beep, a quiet shop announcement, people talking softly in Polish",
        "akcje": ["she picks up a lipstick tester at the make-up stand and tries the shade on the back of her hand",
                  "she leans to a small mirror and dabs a little colour on her lips",
                  "she puts the tester back, drops a new lipstick into her basket and moves on"],
        "streszczenie": "{IMIE} tries lipstick testers in a drugstore while two girls whisper about her.",
        "reakcje": "two teenage girls by the nail-polish rack whisper to each other and giggle; a shop assistant glances over",
        "kamera": "stoi_obok", "slowa": ("rossmann", "drogeri", "hebe", "szmink", "kosmetyk"),
    },
    "galeria_foodcourt": {
        "nazwa": "Galeria handlowa – kioski fast-food", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "the food court of a big shopping mall",
        "opis": "A long, bright shopping-mall corridor: on one side a fast-food counter with a wooden-slat wall and tall "
                "self-service ordering screens, on the other a glossy tiled floor and shop fronts; a glass facade at the far end.",
        "detale": "a cleaning trolley, a bin, receipt printers, an order-number screen above the counter, a digital advert "
                  "screen, people carrying shopping bags",
        "swiatlo": "warm light from the wooden counter mixed with cool daylight from the skylights; the far glass facade is blown "
                   "out to white",
        "dzwieki": "echoing mall hall, footsteps on tiles, beeps of the ordering screens, a muffled announcement in Polish",
        "akcje": ["she stands at an ordering screen with a small plain black bag on her forearm and taps through the menu",
                  "she waits for the receipt, takes it and glances at the order number",
                  "she steps back from the screen and looks around for the pickup counter"],
        "streszczenie": "{IMIE} orders food at a self-service screen of a fast-food counter while shoppers walk past and stare.",
        "reakcje": "a woman in a dark jacket waiting right next to her covers her mouth with her hand, trying not to laugh; a man "
                   "with shopping bags turns his head for a second while walking past",
        "kamera": "idzie_za", "pory": ("popoludnie",),
        "slowa": ("galeri", "food court", "fast food", "fast-food", "kiosk", "mcdonald", "maka", "kfc", "burger", "frytk"),
    },
    "galeria_pasaz": {
        "nazwa": "Galeria handlowa – pasaż i ruchome schody", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a big shopping mall",
        "opis": "The main passage of a big Polish shopping mall: two levels connected by escalators, glass balustrades, "
                "clothing-store windows, a central atrium under a glass roof, benches and potted plants.",
        "detale": "a coffee island with high stools, a coin-operated kids' ride, a security guard, a promo stand with a young "
                  "salesman, shopping bags",
        "swiatlo": "bright even mall lighting with daylight falling from the glass roof",
        "dzwieki": "echoing voices, escalator hum, footsteps, a muffled announcement in Polish",
        "akcje": ["she rides up the escalator holding the rubber handrail, a shopping bag in her other hand",
                  "at the top she steps off and stops to look at a shop window",
                  "she walks along the glass balustrade towards the next shop"],
        "streszczenie": "{IMIE} rides an escalator in a shopping mall while people on the other escalator turn their heads.",
        "reakcje": "a couple coming down the opposite escalator turn their heads as they pass; a teenage boy elbows his friend",
        "kamera": "stoi_obok", "slowa": ("pasaz", "ruchom", "arkadi", "manufaktur", "centrum handl", "sklep z ubraniami"),
    },
    "bazar": {
        "nazwa": "Bazar / targowisko", "kat": "Sklepy i jedzenie",
        "krotko": "an open-air market",
        "opis": "An open-air Polish market (targowisko): rows of stalls under blue and green tarpaulins, fruit and vegetables in "
                "plastic crates, handwritten price cards on cardboard, buckets of flowers, a stall with socks and slippers.",
        "detale": "elderly sellers in fleece jackets and caps, an old scale, thin plastic bags on hooks, jars of pickles and honey, "
                  "handwritten prices in zł",
        "swiatlo": "soft daylight filtered through the coloured tarpaulins",
        "dzwieki": "sellers calling out prices in Polish, rustling bags, a scale beeping, coins clinking",
        "akcje": ["she stops at a fruit stall and points at a punnet of strawberries",
                  "the seller weighs them and pours them into a thin plastic bag",
                  "she pays with coins, takes the bag and walks on along the stalls, eating one"],
        "streszczenie": "{IMIE} buys fruit at an open-air market while the sellers look her up and down.",
        "reakcje": "the elderly saleswoman looks her up and down; a man at the next stall stops counting change to stare",
        "kamera": "mija", "slowa": ("bazar", "targ", "warzyw", "owoc", "truskaw", "czeresn"),
    },
    "piekarnia": {
        "nazwa": "Piekarnia rano", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a small neighbourhood bakery",
        "opis": "A small Polish bakery in the morning: a glass counter full of bread rolls (kajzerki), loaves of rye bread, "
                "doughnuts (pączki) and sweet yeast buns, a saleswoman in an apron, paper bags, a short queue of locals.",
        "detale": "a price list on a board in zł, a card terminal, baskets of bread on wooden shelves, a coffee-to-go machine",
        "swiatlo": "warm light over the counter, cool morning daylight through the door",
        "dzwieki": "the door bell, paper bags rustling, the card terminal beeping, a short chat in Polish",
        "akcje": ["she waits in the short queue looking at the doughnuts behind the glass",
                  "she points at a doughnut and a few bread rolls; the saleswoman packs them into paper bags",
                  "she pays by card and steps out, already biting into the doughnut"],
        "streszczenie": "{IMIE} buys a doughnut and bread rolls in a small bakery in the morning.",
        "reakcje": "the saleswoman smiles politely but glances at her outfit; an old man in the queue shakes his head slightly",
        "kamera": "kolejka", "pory": ("rano",), "slowa": ("piekarn", "bulk", "chleb", "cukierni", "drozdzow"),
    },
    "stacja_paliw": {
        "nazwa": "Stacja benzynowa", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a petrol station by a main road",
        "opis": "A Polish petrol-station shop: a coffee machine, a hot-dog counter, shelves with snacks, car oil and windscreen "
                "fluid, a queue of drivers in work clothes, fuel pumps visible through the window.",
        "detale": "a newspaper rack, a wet-floor sign, price boards in zł, a lorry refuelling outside, cars with Polish plates at "
                  "the pumps",
        "swiatlo": "bright white shop lighting and grey daylight through the window",
        "dzwieki": "the coffee machine grinding, the till beeping, a car door outside, lorry engines idling",
        "akcje": ["she stands at the coffee machine waiting for her cup to fill",
                  "she pays at the counter by tapping her phone",
                  "she walks out through the door with the coffee towards the pumps"],
        "streszczenie": "{IMIE} gets a coffee at a petrol station while a lorry driver in the queue stares.",
        "reakcje": "a lorry driver in a high-visibility vest in the queue stares openly; the cashier smiles politely and glances "
                   "at her colleague",
        "kamera": "kolejka", "slowa": ("stacj", "orlen", "benzyn", "paliw", "tankuj"),
    },
    "kebab": {
        "nazwa": "Kebab na rogu (wieczorem)", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a small kebab bar on a city street",
        "opis": "A small kebab bar in an old tenement: a counter with a vertical rotating meat spit, a menu board with photos and "
                "prices in zł, a few plastic tables, a fridge with soft drinks and a TV in the corner.",
        "detale": "a cook slicing meat with a long knife, garlic and spicy sauce bottles, paper napkins, late customers in jackets",
        "swiatlo": "warm yellowish light inside, a bright sign reflecting in the dark window",
        "dzwieki": "the sizzle of the grill, the extractor fan, chatter in Polish, a TV in the background",
        "akcje": ["she stands at the counter and orders, pointing at a picture on the menu board",
                  "the cook rolls the wrap and asks her something; she nods",
                  "she takes the wrap in foil, pays and bites into it right away"],
        "streszczenie": "{IMIE} orders a kebab wrap late in the evening while the cook and the customers stare.",
        "reakcje": "the cook raises his eyebrows and grins; a guy waiting at a table stops eating and stares",
        "kamera": "kolejka", "pory": ("wieczor",), "slowa": ("kebab", "kebs", "falafel"),
    },
    "poczta": {
        "nazwa": "Poczta (kolejka z numerkiem)", "kat": "Sklepy i jedzenie", "wnetrze": True,
        "krotko": "a Polish post office",
        "opis": "A Polish post office: a ticket queue machine with a number display, a few counters behind glass, people waiting "
                "with parcels and envelopes, and shelves of books, puzzles and sweets for sale next to the counters.",
        "detale": "plastic chairs along the wall, forms on a small table, cardboard boxes, a clock on the wall, a tired clerk",
        "swiatlo": "flat fluorescent office light",
        "dzwieki": "the queue display chiming, tape pulled off a roll, a clerk calling the next number, quiet murmur",
        "akcje": ["she pulls a number ticket from the machine and looks up at the display",
                  "she sits on a plastic chair and scrolls her phone while waiting",
                  "the display chimes; she gets up and walks to the counter with a parcel"],
        "streszczenie": "{IMIE} waits for her number in a post office queue while the people waiting stare.",
        "reakcje": "an elderly man stares at her over his glasses; two women waiting with parcels whisper",
        "kamera": "stoi_obok", "slowa": ("poczt", "poczc", "numerek", "wyslac paczk", "list polecon"),
    },
    # ---------- komunikacja ----------
    "przystanek": {
        "nazwa": "Przystanek tramwajowy w centrum", "kat": "Komunikacja",
        "krotko": "a tram stop in a city centre",
        "opis": "A tram stop in the centre of a big Polish city: a glass shelter with an electronic departure board, a ticket "
                "machine, tram tracks in a cobbled street and old tenement houses with shops on the ground floor.",
        "detale": "a timetable in a frame, faded posters on the shelter, pigeons, a kebab place and a pharmacy across the street, "
                  "overhead tram wires",
        "swiatlo": "overcast daylight with soft shadows and reflections on the cobbles",
        "dzwieki": "a tram bell and screeching wheels, traffic, the ticking signal of a pedestrian crossing, wind",
        "akcje": ["she stands at the tram stop scrolling on her phone, shifting her weight from foot to foot",
                  "a tram rolls in behind her and stops with a hiss of doors; people get off around her",
                  "she checks the tram number, puts the phone away and steps towards the doors"],
        "streszczenie": "{IMIE} waits at a tram stop while a tram arrives and people around her stare.",
        "reakcje": "a young man on the bench stares at her and nudges his friend; an older woman with a shopping trolley shakes her "
                   "head slightly",
        "kamera": "mija", "slowa": ("przystan", "czeka na tramwaj", "czeka na autobus"),
    },
    "tramwaj": {
        "nazwa": "W tramwaju", "kat": "Komunikacja", "wnetrze": True,
        "krotko": "a city tram",
        "opis": "Inside a modern low-floor Polish city tram: rows of grey-blue seats, yellow handrails and hanging straps, a ticket "
                "validator and a ticket machine, a small screen showing the next stops in Polish, the city passing outside.",
        "detale": "a pensioner with a shopping trolley, students with backpacks, a man in a reflective work jacket, scratched "
                  "windows",
        "swiatlo": "daylight flickering through the windows as the tram moves, mixed with cool interior lights",
        "dzwieki": "the tram motor whine and rattle, door warning beeps, a recorded stop announcement in Polish, quiet chatter",
        "akcje": ["she stands holding a hanging strap, swaying as the tram brakes",
                  "she sits down on a free seat by the window and looks out",
                  "she gets up as the tram slows down and walks to the door"],
        "streszczenie": "{IMIE} rides a city tram while the passengers stare at her.",
        "reakcje": "an elderly lady with a shopping trolley stares at her openly; a teenager across the aisle films her too, "
                   "pretending to text",
        "kamera": "siedzi_naprzeciw", "slowa": ("tramwaj", "w tramwaju", "mpk", "autobus"),
    },
    "metro": {
        "nazwa": "Metro w Warszawie", "kat": "Komunikacja", "wnetrze": True,
        "krotko": "a metro station in Warsaw",
        "opis": "A Warsaw metro station: long escalators between steel-and-glass walls, a platform with a modern silver train "
                "arriving, adverts on the walls, a digital board with the next train time.",
        "detale": "commuters with backpacks, ticket gates, a dropped ticket on a step, a security guard, an info sign with the "
                  "line number",
        "swiatlo": "cool white overhead light with shiny steel reflections",
        "dzwieki": "escalator hum, a train arriving below, footsteps, beeps of the exit gates, a recorded announcement in Polish",
        "akcje": ["she rides up the long escalator standing on the right, one hand on the rubber handrail",
                  "people on the descending escalator next to her turn their heads as they pass",
                  "at the top she steps off and walks towards the exit gates"],
        "streszczenie": "{IMIE} rides a long metro escalator while commuters on the opposite escalator turn to look.",
        "reakcje": "a teenager on the opposite escalator turns around to keep looking; a man in a suit pretends not to look",
        "kamera": "stoi_obok", "operator": "standing three steps below her on the same escalator, tilting the phone up",
        "slowa": ("metro", "metrze"),
    },
    "dworzec": {
        "nazwa": "Dworzec kolejowy (hala)", "kat": "Komunikacja", "wnetrze": True,
        "krotko": "the main hall of a big railway station",
        "opis": "The main hall of a big Polish railway station: a large electronic departure board, ticket machines and ticket "
                "counters, a coffee kiosk and a small bakery stand, people with suitcases, escalators down to the platforms.",
        "detale": "suitcases on wheels, a security guard in a vest, a cleaning machine, information screens with train times",
        "swiatlo": "daylight from a glass roof mixed with cold white station lights",
        "dzwieki": "an echoing station announcement in Polish, suitcase wheels on tiles, footsteps, voices",
        "akcje": ["she stands under the departure board looking up at it, a small plain bag on her shoulder",
                  "she checks her ticket on her phone and looks at the board again",
                  "she turns and walks towards the escalator to the platforms"],
        "streszczenie": "{IMIE} checks the departure board in a busy station hall while travellers turn their heads.",
        "reakcje": "a man pulling a suitcase slows down and looks back at her; two students whisper to each other and laugh "
                   "quietly",
        "kamera": "stoi_obok", "slowa": ("dworz", "dworc", "centraln", "tablic", "odjazd"),
    },
    "peron": {
        "nazwa": "Peron, przyjeżdża pociąg", "kat": "Komunikacja",
        "krotko": "a railway platform",
        "opis": "An open platform of a Polish railway station: a concrete platform edge with a painted safety line, a metal "
                "shelter with benches, a station name board, overhead wires and a regional train pulling in.",
        "detale": "a platform display with train times, a pedestrian tunnel entrance, people with bikes and suitcases, gravel and "
                  "rails",
        "swiatlo": "open sky light, the wind moving her hair",
        "dzwieki": "an approaching train horn, wheels screeching to a stop, a platform announcement in Polish, doors hissing",
        "akcje": ["she waits on the platform with a small backpack, watching the train approach",
                  "the train stops and the doors open; passengers step out around her",
                  "she presses the door button and climbs aboard"],
        "streszczenie": "{IMIE} waits on a railway platform as a regional train pulls in.",
        "reakcje": "a conductor in a uniform cap gives her a long look; a group of students on the platform turn around",
        "kamera": "stoi_obok", "slowa": ("peron", "pociag", "pkp", "intercity", "kolejow"),   # nie "kolej" - "w kolejce"
    },
    "pociag": {
        "nazwa": "W pociągu (wagon)", "kat": "Komunikacja", "wnetrze": True,
        "krotko": "a long-distance train carriage",
        "opis": "Inside a modern Polish long-distance train carriage: rows of blue-grey seats with white headrest covers, folding "
                "tables, overhead luggage racks, a screen showing the next station, fields and villages passing outside.",
        "detale": "a paper coffee cup on a table, a sleeping passenger, a backpack in the aisle, a conductor checking tickets on a "
                  "handheld device",
        "swiatlo": "soft window light changing as the train passes trees",
        "dzwieki": "the rhythmic rattle of the wheels, an announcement in Polish and English, a refreshment trolley squeaking",
        "akcje": ["she sits by the window eating a sandwich from a paper wrapper",
                  "the conductor comes and she shows her ticket on her phone",
                  "she leans her head on the window and watches the fields go by"],
        "streszczenie": "{IMIE} travels by train and shows her ticket to the conductor.",
        "reakcje": "the conductor pauses a beat longer than needed; a man across the aisle lowers his newspaper to look",
        "kamera": "siedzi_naprzeciw", "slowa": ("w pociagu", "wagon", "konduktor"),
    },
    "przejscie_podziemne": {
        "nazwa": "Przejście podziemne w centrum", "kat": "Komunikacja", "wnetrze": True,
        "krotko": "an underground pedestrian passage in a city centre",
        "opis": "A busy underground pedestrian passage under a big city crossing: tiled walls, a low ceiling with fluorescent "
                "tubes, small kiosks selling phone cases, keys, flowers and snacks, stairs and escalators up to the street.",
        "detale": "a man handing out leaflets, flowers in buckets, posters on the walls, people hurrying with coffee",
        "swiatlo": "flat greenish fluorescent light with daylight at the top of the stairs",
        "dzwieki": "echoing footsteps, traffic rumbling above, kiosk sellers chatting in Polish",
        "akcje": ["she comes down the stairs into the passage, holding the handrail",
                  "she stops at a little kiosk and looks at the phone cases",
                  "she buys a small keychain, pays and heads to the other stairs"],
        "streszczenie": "{IMIE} walks through a busy underground passage and stops at a little kiosk.",
        "reakcje": "the kiosk seller stares; a group of teenagers on the stairs turn their heads",
        "kamera": "mija", "slowa": ("przejsci", "podziemn", "tunel"),
    },
    "przejscie_dla_pieszych": {
        "nazwa": "Przejście dla pieszych – czeka na zielone", "kat": "Komunikacja",
        "krotko": "a pedestrian crossing on a busy city street",
        "opis": "A zebra crossing on a busy Polish city street: a pedestrian traffic light with a ticking sound signal, a crowd "
                "waiting at the kerb, cars, a bus and a tram passing, tenement houses and shops around.",
        "detale": "a push-button box on the pole, a cyclist on the bike path, delivery riders with big cube backpacks, a bus with "
                  "a destination display",
        "swiatlo": "open daylight between the buildings",
        "dzwieki": "the fast ticking of the crossing signal, traffic, a bus braking, a car horn",
        "akcje": ["she waits at the kerb among other people for the green light, checking her phone",
                  "the light turns green and the crowd starts crossing with her",
                  "halfway across she adjusts her bag and keeps walking"],
        "streszczenie": "{IMIE} waits for the green light at a busy crossing while people at the kerb stare.",
        "reakcje": "a man waiting next to her looks her up and down; a driver in a stopped car leans forward to look",
        "kamera": "stoi_obok", "slowa": ("przejscie dla", "pasy", "zielone", "swiatl", "skrzyzow"),
    },
    # ---------- znane miejsca w miastach ----------
    "rynek_krakow": {
        "nazwa": "Rynek Główny w Krakowie", "kat": "Znane miejsca w miastach",
        "krotko": "the Main Market Square in Kraków",
        "opis": "The Main Market Square in Kraków: the long Renaissance Cloth Hall in the middle, St. Mary's Basilica with its "
                "two unequal brick towers, colourful old tenement houses, horse-drawn carriages, flower stalls and café gardens.",
        "detale": "a cart selling ring-shaped bagels (obwarzanki), pigeons on the cobbles, tour groups following a guide, street "
                  "performers, café menus on boards",
        "swiatlo": "open daylight over the square, the sky blown out in places",
        "dzwieki": "the trumpet call from the church tower that breaks off mid-melody, pigeons, horse hooves on cobbles, tourist "
                   "chatter",
        "akcje": ["she buys a ring-shaped bagel from a cart and pays with a coin",
                  "pigeons flutter up in front of her and she steps around them",
                  "she walks across the cobbles towards the Cloth Hall, nibbling the bagel"],
        "streszczenie": "{IMIE} buys a bagel on Kraków's Main Market Square while tourists and café guests watch her.",
        "reakcje": "a couple in a café garden stop talking and watch her; a few people in a tour group turn their heads",
        "kamera": "z_daleka_zoom", "slowa": ("rynek glown", "rynku glown", "krakow", "sukienn", "mariack", "obwarzan"),
    },
    "plac_nowy": {
        "nazwa": "Plac Nowy na Kazimierzu – zapiekanki", "kat": "Znane miejsca w miastach",
        "krotko": "Plac Nowy in Kraków's Kazimierz district",
        "opis": "Plac Nowy in Kraków's Kazimierz district: a small round brick market hall in the middle with little windows "
                "selling zapiekanki (long toasted open baguettes with mushrooms, cheese and ketchup), worn old tenements, bars "
                "and parked bikes.",
        "detale": "a queue at the zapiekanka windows, handwritten menus with prices in zł, ketchup bottles, students and tourists "
                  "eating standing up, graffiti on old walls",
        "swiatlo": "evening street lamps and warm light from the little windows",
        "dzwieki": "chatter in Polish and English, bike bells, a bar door opening, someone laughing",
        "akcje": ["she waits at one of the little windows of the round market hall",
                  "she gets a long zapiekanka on a paper tray and squeezes extra ketchup on it",
                  "she takes a big bite and tries not to drop the melted cheese"],
        "streszczenie": "{IMIE} buys a zapiekanka at Plac Nowy in Kraków while the people in the queue stare.",
        "reakcje": "the people in the queue behind her stare; a guy eating his zapiekanka stops chewing",
        "kamera": "stoi_obok", "pory": ("wieczor",), "slowa": ("zapiekank", "kazimierz", "plac nowy", "placu nowym", "okraglak"),
    },
    "plac_zamkowy": {
        "nazwa": "Plac Zamkowy w Warszawie", "kat": "Znane miejsca w miastach",
        "krotko": "Castle Square in Warsaw",
        "opis": "Castle Square in Warsaw: the brick-red Royal Castle with its clock tower, Sigismund's Column (a tall column with "
                "a bronze king on top), colourful Old Town tenement houses, cobblestones and tourists.",
        "detale": "a horse carriage, a bubble-blower entertaining kids, souvenir sellers, the entrance to the narrow Old Town "
                  "streets, pigeons",
        "swiatlo": "open daylight over the square",
        "dzwieki": "tourist chatter in many languages, Polish voices nearby, pigeons, horse hooves, a distant tram",
        "akcje": ["she walks across the cobbles with a takeaway coffee, looking at a map on her phone",
                  "she stops near the column and takes a quick photo of the castle",
                  "she turns and heads into a narrow Old Town street"],
        "streszczenie": "{IMIE} crosses Castle Square in Warsaw with a coffee while tourists watch her.",
        "reakcje": "a group of tourists turn their phones from the castle to her; a souvenir seller shakes his head and smiles",
        "kamera": "z_daleka_zoom", "slowa": ("zamkow", "zamek", "starowk", "stare miasto", "starym miescie", "kolumn"),
    },
    "nowy_swiat": {
        "nazwa": "Nowy Świat w Warszawie", "kat": "Znane miejsca w miastach",
        "krotko": "Nowy Świat street in Warsaw",
        "opis": "Nowy Świat street in central Warsaw: low classicist tenement houses in pastel colours, wide pavements with café "
                "tables, ice-cream and doughnut shops, old street lamps.",
        "detale": "delivery riders on bikes, a city bus, people with shopping bags, Polish flags on a building, café menus on "
                  "boards",
        "swiatlo": "open daylight along the street, shop windows reflecting",
        "dzwieki": "traffic and bus engines, café chatter in Polish, cutlery, footsteps",
        "akcje": ["she walks along the pavement past café tables, carrying a small paper bag",
                  "she stops at a doughnut shop window and looks at the trays",
                  "she goes in through the door"],
        "streszczenie": "{IMIE} walks down Nowy Świat in Warsaw and stops at a doughnut shop.",
        "reakcje": "people at the café tables stop talking and follow her with their eyes; a waiter smiles",
        "kamera": "idzie_za", "slowa": ("nowy swiat", "nowym swiecie", "krakowskie przedm", "krakowskim przedm"),
    },
    "palac_kultury": {
        "nazwa": "Pod Pałacem Kultury (Warszawa)", "kat": "Znane miejsca w miastach",
        "krotko": "the square below the Palace of Culture and Science in Warsaw",
        "opis": "The square at the foot of the Palace of Culture and Science in Warsaw: the huge socialist-realist tower with its "
                "spire above, wide paved squares, fountains and glass skyscrapers of the city centre around.",
        "detale": "skateboarders, people hurrying towards the station, electric scooters lying on the pavement, a hot-dog stand",
        "swiatlo": "open daylight, the sky behind the tower blown out to white",
        "dzwieki": "city traffic, skateboard wheels, wind between the buildings, voices",
        "akcje": ["she walks across the wide square with the tower rising behind her",
                  "she stops to fix her hair in the wind",
                  "she tilts her head back to look up at the spire and then walks on"],
        "streszczenie": "{IMIE} crosses the square below the Palace of Culture in Warsaw.",
        "reakcje": "two skateboarders stop rolling and watch her; a man with a briefcase turns his head",
        "kamera": "z_daleka_zoom", "slowa": ("palac", "pkin", "centrum warszaw"),
    },
    "bulwary": {
        "nazwa": "Bulwary nad Wisłą (Warszawa)", "kat": "Znane miejsca w miastach",
        "krotko": "the riverside boulevards in Warsaw",
        "opis": "The Vistula boulevards in Warsaw: wide concrete steps down to the river, a cable-stayed bridge in the distance, "
                "a cycle path, food trucks and groups of friends sitting on the steps.",
        "detale": "electric scooters lying on the ground, paper cups, a bin, a food-truck menu too far away to read",
        "swiatlo": "low golden sun behind her, rim light on her hair, the sky slightly blown out",
        "dzwieki": "wind from the river, distant chatter, bicycle bells, seagulls, a boat engine",
        "akcje": ["she walks along the boulevard with the river on one side",
                  "a cyclist rings and passes between her and the camera",
                  "she sits down on the concrete steps and takes a photo of the river with her phone"],
        "streszczenie": "{IMIE} walks along the Vistula boulevards while people sitting on the steps go quiet and look.",
        "reakcje": "a group of friends on the steps go quiet and look at her; one guy raises his eyebrows at his friend",
        "kamera": "idzie_za", "pory": ("popoludnie",), "slowa": ("bulwar", "wisl", "nad rzek"),
    },
    "lazienki": {
        "nazwa": "Łazienki Królewskie (Warszawa)", "kat": "Znane miejsca w miastach",
        "krotko": "Łazienki Park in Warsaw",
        "opis": "Łazienki Park in Warsaw: the white classicist Palace on the Isle reflected in the pond, gravel alleys under old "
                "trees, peacocks walking freely and red squirrels near the benches.",
        "detale": "people feeding squirrels with nuts, white benches, ducks on the water, a park guard",
        "swiatlo": "soft daylight through old trees",
        "dzwieki": "a peacock calling, birds, gravel crunching, children's voices",
        "akcje": ["she crouches near a bench and holds out a nut to a red squirrel",
                  "the squirrel snatches it and runs off; she laughs and stands up",
                  "a peacock walks across the path in front of her and she films it on her phone"],
        "streszczenie": "{IMIE} feeds a squirrel in Łazienki Park while walkers watch her.",
        "reakcje": "an elderly couple on a bench watch her with amused faces; a mother with a pram stares",
        "kamera": "z_daleka_zoom", "slowa": ("lazienk", "wiewior", "paw"),
    },
    "rynek_wroclaw": {
        "nazwa": "Rynek we Wrocławiu (krasnale)", "kat": "Znane miejsca w miastach",
        "krotko": "the Market Square in Wrocław",
        "opis": "The Market Square in Wrocław: the Gothic town hall with ornate pointed gables and an astronomical clock, rows of "
                "colourful tenement houses, café gardens, and small bronze dwarf figurines (krasnale) on the pavement.",
        "detale": "tourists crouching to photograph the dwarfs, flower stalls, a fountain, pigeons",
        "swiatlo": "open daylight over the square",
        "dzwieki": "tourist chatter, café cutlery, pigeons, footsteps on cobbles",
        "akcje": ["she crouches next to a tiny bronze dwarf figure on the pavement",
                  "she takes a selfie with it, making a silly face",
                  "she stands up and walks on across the square"],
        "streszczenie": "{IMIE} takes a selfie with a bronze dwarf on Wrocław's Market Square.",
        "reakcje": "a family waiting to photograph the same dwarf stares at her; a waiter in a café garden grins",
        "kamera": "stoi_obok", "slowa": ("wroclaw", "krasnal"),
    },
    "gdansk": {
        "nazwa": "Długi Targ w Gdańsku", "kat": "Znane miejsca w miastach",
        "krotko": "the Long Market in Gdańsk",
        "opis": "The Long Market (Długi Targ) in Gdańsk: tall narrow Hanseatic tenement houses with decorated gables, the Neptune "
                "Fountain and the Main Town Hall with its tall spire, café gardens and amber jewellery stalls.",
        "detale": "tourists with cameras, seagulls, a street artist drawing portraits, amber pendants on velvet",
        "swiatlo": "bright seaside daylight, the sky blown out above the gables",
        "dzwieki": "seagulls, tourist chatter, footsteps on stones, café cups clinking",
        "akcje": ["she walks along the long street past the amber stalls",
                  "she stops at a stall and holds an amber pendant up to the light",
                  "she puts it back and walks on towards the Neptune Fountain"],
        "streszczenie": "{IMIE} looks at amber jewellery on the Long Market in Gdańsk.",
        "reakcje": "the amber seller stares at her instead of the jewellery; tourists turn their cameras towards her",
        "kamera": "idzie_za", "slowa": ("gdansk", "dlugi targ", "neptun", "bursztyn"),
    },
    "poznan": {
        "nazwa": "Stary Rynek w Poznaniu (koziołki)", "kat": "Znane miejsca w miastach",
        "krotko": "the Old Market Square in Poznań",
        "opis": "The Old Market Square in Poznań: the Renaissance town hall with an arcaded loggia and a clock tower where two small "
                "mechanical goats knock their heads together at noon, and a row of narrow colourful merchants' houses in front of it.",
        "detale": "a crowd looking up at the clock, pigeons, café gardens, a fountain, tourists holding up phones",
        "swiatlo": "midday daylight over the square",
        "dzwieki": "a crowd murmuring, the clock chiming, pigeons, café chatter",
        "akcje": ["she stands in the crowd waiting for the clock, looking at her phone",
                  "everyone raises their phones towards the tower; she looks up too",
                  "she turns away before the end and walks off across the square"],
        "streszczenie": "{IMIE} waits for the goats on the Poznań town hall clock while the crowd films her instead.",
        "reakcje": "people next to her film her instead of the clock tower; a child points at her",
        "kamera": "stoi_obok", "slowa": ("poznan", "koziolk"),
    },
    "piotrkowska": {
        "nazwa": "Piotrkowska w Łodzi", "kat": "Znane miejsca w miastach",
        "krotko": "Piotrkowska Street in Łódź",
        "opis": "Piotrkowska Street in Łódź: a long pedestrian street of ornate 19th-century tenement houses, café gardens, bronze "
                "sculptures on benches, bike rickshaws and neon signs.",
        "detale": "a bronze figure of a poet on a bench, a rickshaw driver waiting, flower pots, people with ice cream",
        "swiatlo": "open daylight along the street",
        "dzwieki": "footsteps, café chatter in Polish, a rickshaw bell, distant traffic",
        "akcje": ["she walks down the middle of the long street",
                  "she sits for a moment on a bench next to a bronze sculpture",
                  "a bike rickshaw rolls past and she gets up and walks on"],
        "streszczenie": "{IMIE} walks down Piotrkowska Street in Łódź and sits next to a bronze statue.",
        "reakcje": "a rickshaw driver whistles quietly; two women at a café table stare",
        "kamera": "idzie_za", "slowa": ("lodz", "piotrkowsk"),
    },
    "spodek": {
        "nazwa": "Pod Spodkiem w Katowicach", "kat": "Znane miejsca w miastach",
        "krotko": "the area around Spodek in Katowice",
        "opis": "The area around Spodek in Katowice: the flying-saucer-shaped concrete arena, wide paved squares and grassy slopes, "
                "modern glass buildings of the city centre around.",
        "detale": "people walking to an event, a tram line on the street, electric scooters, pigeons",
        "swiatlo": "open daylight, the concrete arena slightly hazy",
        "dzwieki": "traffic, a tram passing, wind, voices",
        "akcje": ["she walks across the square towards the saucer-shaped arena",
                  "she stops and takes a photo of it on her phone",
                  "she sits on the grassy slope and checks the photo"],
        "streszczenie": "{IMIE} takes a photo of the Spodek arena in Katowice.",
        "reakcje": "a group of guys in football scarves stare; one of them whistles quietly",
        "kamera": "z_daleka_zoom", "slowa": ("spodek", "katowic", "slask"),
    },
    "miasteczko": {
        "nazwa": "Rynek małego miasteczka", "kat": "Znane miejsca w miastach",
        "krotko": "the market square of a small Polish town",
        "opis": "The market square of a small Polish town: a modest town hall with a clock, a church tower, low houses with small "
                "shops (a pharmacy, a butcher, a bank), a bus stop and a few parked cars.",
        "detale": "pensioners on benches, a man on an old bicycle, flower beds, a war memorial, shop signs in Polish",
        "swiatlo": "quiet open daylight",
        "dzwieki": "church bells, a car passing slowly, pigeons, two neighbours chatting in Polish",
        "akcje": ["she walks across the quiet market square with a bakery bag",
                  "she stops at the bus stop and reads the timetable",
                  "she sits on a bench next to a pensioner and waits"],
        "streszczenie": "{IMIE} waits for a bus on the quiet market square of a small Polish town.",
        "reakcje": "the pensioner on the bench stares at her in silence; a man on a bicycle almost rides into a flower bed",
        "kamera": "z_daleka_zoom", "slowa": ("miasteczk", " wsi ", " wies ", "malym miescie"),
    },
    # ---------- parki, woda, gory ----------
    "park": {
        "nazwa": "Park miejski", "kat": "Parki, woda, góry",
        "krotko": "a city park",
        "opis": "A Polish city park: gravel alleys under old chestnut and lime trees, green benches, a pond with ducks, a small "
                "ice-cream kiosk and a playground.",
        "detale": "people walking dogs, a jogger, pensioners on benches, children on scooters",
        "swiatlo": "soft daylight through the trees",
        "dzwieki": "birds, ducks, gravel crunching, children's voices, distant city hum",
        "akcje": ["she walks along the alley with a takeaway coffee",
                  "she stops at the pond and throws a few crumbs to the ducks",
                  "she sits on a bench and checks her phone"],
        "streszczenie": "{IMIE} feeds the ducks in a city park while walkers stare.",
        "reakcje": "a man walking his dog slows down and stares; two pensioners on a bench comment to each other",
        "kamera": "z_daleka_zoom", "slowa": ("park", "kacz", "staw", "lawk"),
    },
    "molo_sopot": {
        "nazwa": "Molo w Sopocie", "kat": "Parki, woda, góry",
        "krotko": "the wooden pier in Sopot",
        "opis": "The long wooden pier in Sopot stretching far into the Baltic Sea: wide wooden planks, white lamps and benches, "
                "seagulls on the railings, the beach and the grand hotel on the shore behind.",
        "detale": "couples walking, a man with a fishing rod, a child with a balloon, wet planks",
        "swiatlo": "bright sea light, the sky and water blown out near the horizon",
        "dzwieki": "wind, waves, seagulls screaming, wooden planks creaking under footsteps",
        "akcje": ["she walks along the pier with the wind blowing her hair across her face",
                  "she stops at the railing and holds out her phone to film the sea",
                  "a seagull lands next to her and she steps back, laughing"],
        "streszczenie": "{IMIE} walks along the Sopot pier in the wind.",
        "reakcje": "a couple walking hand in hand turn to look at her; a man with a fishing rod shakes his head",
        "kamera": "idzie_za", "slowa": ("molo", "sopot", "sopoc", "trojmiast"),
    },
    "plaza": {
        "nazwa": "Plaża nad Bałtykiem (parawany)", "kat": "Parki, woda, góry", "sezony": ("lato",),
        "krotko": "a crowded Polish Baltic beach",
        "opis": "A crowded Polish Baltic beach: pale sand, colourful windbreaker screens (parawany) fencing off family spots, "
                "grey-green waves, a lifeguard tower with a flag, dunes with beach grass.",
        "detale": "a waffle and ice-cream stand at the beach entrance, inflatable toys, sunburnt dads, children with buckets, "
                  "plastic chairs",
        "swiatlo": "harsh bright beach light, the sea and sky blown out",
        "dzwieki": "waves, wind flapping the windbreakers, children shouting, seagulls, a seller calling out",
        "akcje": ["she walks between the windbreakers barefoot, holding a waffle with whipped cream",
                  "she steps around a family's screen and almost trips over a bucket",
                  "she sits on the sand facing the sea and takes a bite"],
        "streszczenie": "{IMIE} walks across a crowded Baltic beach full of windbreakers with a waffle.",
        "reakcje": "a family behind their windbreaker stop eating and stare; a dad elbows his wife",
        "kamera": "z_daleka_zoom", "slowa": ("plaz", "morz", "baltyk", "parawan", "gofr"),
    },
    "jezioro": {
        "nazwa": "Pomost nad jeziorem (Mazury)", "kat": "Parki, woda, góry",
        "krotko": "a wooden jetty on a Masurian lake",
        "opis": "A wooden jetty on a Masurian lake: calm dark water, reeds along the shore, white sailing boats moored nearby and a "
                "pine forest on the far shore.",
        "detale": "a rowing boat tied to a post, a fisherman on a folding chair, life rings on a pole, ducks",
        "swiatlo": "soft light reflecting off the water",
        "dzwieki": "water lapping against the jetty, boat ropes creaking, wind in the reeds, ducks",
        "akcje": ["she walks to the end of the jetty",
                  "she sits on the edge and lets her legs dangle over the water",
                  "she takes a photo of the lake on her phone"],
        "streszczenie": "{IMIE} sits at the end of a jetty on a Masurian lake.",
        "reakcje": "a fisherman on a folding chair stares at her over his rod; sailors on a moored boat stop talking",
        "kamera": "z_daleka_zoom", "slowa": ("jezior", "mazur", "pomost", "zagl"),
    },
    "krupowki": {
        "nazwa": "Krupówki w Zakopanem", "kat": "Parki, woda, góry",
        "krotko": "Krupówki street in Zakopane",
        "opis": "Krupówki, the main street of Zakopane: wooden highlander-style houses with steep roofs, souvenir stalls, small "
                "grills selling smoked sheep cheese (oscypek) with cranberry jam, horse-drawn carriages, and the Tatra peaks "
                "with Giewont in the distance.",
        "detale": "sheepskin slippers on stalls, crowds of tourists in fleece jackets, a seller in a traditional felt hat",
        "swiatlo": "crisp mountain daylight, the peaks hazy in the background",
        "dzwieki": "crowd chatter, horse hooves, a seller calling out, mountain wind",
        "akcje": ["she buys a grilled smoked cheese with cranberry jam at a little grill stall",
                  "she blows on it and takes a careful bite",
                  "she walks on through the crowd, wiping jam from her finger with a napkin"],
        "streszczenie": "{IMIE} buys a grilled oscypek on Krupówki in Zakopane while tourists stare.",
        "reakcje": "the seller in the felt hat grins at her; a family of tourists stop and stare",
        "kamera": "idzie_za", "slowa": ("krupowk", "zakopan", "oscyp", "gory", "tatr"),
    },
}

# ---------------- prawdziwe nazwy: galerie, dworce, metro, dzielnice, miasta (feedback usera 2026-10-07) ----------------
# User nie chce wymyslonych miejsc: rolka ma byc w PRAWDZIWEJ galerii (Posnania, Stary Browar, Wroclavia, Zlote Tarasy...).
# Nazwy galerii/dworcow to nie marki produktow - filtr IP Higgsfielda raczej ich nie rusza; gdyby jednak odrzucil (powod "ip"),
# asystent.py przelacza miejsce na `nazwy: "opisowe"` (opis bez nazwy). Marki SKLEPOW (Zabka, Biedronka, Rossmann...) nadal tylko
# opisem wygladu. id -> (etykieta PL, fraza EN, miasto)
GALERIE = {
    "posnania": ("Posnania (Poznań)", "the Posnania shopping centre in Poznań", "poznan"),
    "stary_browar": ("Stary Browar (Poznań)", "the Stary Browar shopping centre in Poznań, a converted red-brick brewery", "poznan"),
    "wroclavia": ("Wroclavia (Wrocław)", "the Wroclavia shopping centre in Wrocław", "wroclaw"),
    "zlote_tarasy": ("Złote Tarasy (Warszawa)", "the Złote Tarasy shopping centre in Warsaw, under its wavy glass roof", "warszawa"),
    "arkadia": ("Arkadia (Warszawa)", "the Arkadia shopping centre in Warsaw", "warszawa"),
    "galeria_krakowska": ("Galeria Krakowska (Kraków)", "the Galeria Krakowska shopping centre in Kraków", "krakow"),
    "manufaktura": ("Manufaktura (Łódź)", "the Manufaktura shopping centre in Łódź, in red-brick former factory buildings", "lodz"),
    "galeria_baltycka": ("Galeria Bałtycka (Gdańsk)", "the Galeria Bałtycka shopping centre in Gdańsk", "gdansk"),
    "silesia": ("Silesia City Center (Katowice)", "the Silesia City Center shopping centre in Katowice", "katowice"),
}
DWORCE = {
    "warszawa_centralna": ("Warszawa Centralna", "Warszawa Centralna station in Warsaw", "warszawa"),
    "krakow_glowny": ("Kraków Główny", "Kraków Główny station in Kraków", "krakow"),
    "wroclaw_glowny": ("Wrocław Główny", "Wrocław Główny station in Wrocław", "wroclaw"),
    "poznan_glowny": ("Poznań Główny", "Poznań Główny station in Poznań", "poznan"),
    "gdansk_glowny": ("Gdańsk Główny", "Gdańsk Główny station in Gdańsk", "gdansk"),
    "katowice": ("Katowice (dworzec)", "the main railway station in Katowice", "katowice"),
}
STACJE_METRA = {
    "centrum": ("Centrum (M1)", "Centrum station of the Warsaw metro", "warszawa"),
    "swietokrzyska": ("Świętokrzyska", "Świętokrzyska station of the Warsaw metro", "warszawa"),
    "politechnika": ("Politechnika", "Politechnika station of the Warsaw metro", "warszawa"),
    "rondo_daszynskiego": ("Rondo Daszyńskiego", "Rondo Daszyńskiego station of the Warsaw metro", "warszawa"),
}
DZIELNICE = {
    "jezyce": ("Jeżyce (Poznań)", "Poznań's Jeżyce district", "poznan"),
    "praga": ("Praga (Warszawa)", "Warsaw's Praga district", "warszawa"),
    "nowa_huta": ("Nowa Huta (Kraków)", "Kraków's Nowa Huta district", "krakow"),
    "nadodrze": ("Nadodrze (Wrocław)", "Wrocław's Nadodrze district", "wroclaw"),
    "baluty": ("Bałuty (Łódź)", "Łódź's Bałuty district", "lodz"),
    "zaspa": ("Zaspa (Gdańsk)", "Gdańsk's Zaspa district", "gdansk"),
    "tysiaclecie": ("Osiedle Tysiąclecia (Katowice)", "the Tysiąclecia estate in Katowice", "katowice"),
}
MIASTA = {
    "warszawa": ("Warszawa", "Warsaw", "warszawa"), "krakow": ("Kraków", "Kraków", "krakow"),
    "poznan": ("Poznań", "Poznań", "poznan"), "wroclaw": ("Wrocław", "Wrocław", "wroclaw"),
    "lodz": ("Łódź", "Łódź", "lodz"), "gdansk": ("Gdańsk", "Gdańsk", "gdansk"), "katowice": ("Katowice", "Katowice", "katowice"),
}
_RDZENIE_MIAST = {"poznan": ("poznan",), "krakow": ("krakow",), "wroclaw": ("wroclaw",), "warszawa": ("warszaw", "stolic"),
                  "lodz": (" lodz", "lodzi "), "gdansk": ("gdansk", "trojmiast"), "katowice": ("katowic", "slask")}
# miejsce -> (lista obiektow, wzor frazy EN: {o} = fraza obiektu, {k} = 'krotko' miejsca)
OBIEKTY_MIEJSC = {
    "galeria_foodcourt": (GALERIE, "the food court of {o}"), "galeria_pasaz": (GALERIE, "the main passage of {o}"),
    "dworzec": (DWORCE, "the main hall of {o}"), "peron": (DWORCE, "a platform of {o}"), "metro": (STACJE_METRA, "{o}"),
    "przystanek": (MIASTA, "{k} in {o}"), "tramwaj": (MIASTA, "{k} in {o}"), "przejscie_podziemne": (MIASTA, "{k} in {o}"),
    "przejscie_dla_pieszych": (MIASTA, "{k} in {o}"),
    **{mid: (DZIELNICE, "{k} in {o}") for mid in ("osiedle", "klatka", "sklep_osiedlowy", "silownia_plenerowa", "orlik", "dyskont",
                                                 "drogeria", "bazar", "piekarnia", "stacja_paliw", "kebab", "poczta", "park")},
}
# prawdziwe polskie napisy w miejscu (model psuje litery - krotkie, DUZE slowa); ceny zawsze "19,99 zł"
SZYLDY = {
    "galeria_foodcourt": "'ZAMÓW TUTAJ', 'ODBIÓR ZAMÓWIEŃ', 'WYJŚCIE'", "galeria_pasaz": "'WYJŚCIE', 'TOALETY', 'PROMOCJA -30%'",
    "dyskont": "'KASA', 'PROMOCJA', 'PIECZYWO'", "drogeria": "'PROMOCJA', 'NOWOŚĆ', 'KASA'",
    "sklep_osiedlowy": "'OTWARTE', 'HOT DOG', 'KAWA'", "stacja_paliw": "'KAWA', 'KASA', 'MYJNIA'",
    "piekarnia": "'PĄCZKI', 'CHLEB', 'BUŁKI'", "kebab": "'KEBAB', 'ZAPIEKANKI', 'FRYTKI'", "poczta": "'POCZTA', 'NUMEREK'",
    "bazar": "handwritten cardboard price cards like 'TRUSKAWKI 15 zł/kg'", "dworzec": "'ODJAZDY', 'PRZYJAZDY', 'KASY BILETOWE'",
    "peron": "'PERON 2', 'TOR 3'", "metro": "'WYJŚCIE', 'KIERUNEK'", "przejscie_podziemne": "'WYJŚCIE', 'KLUCZE', 'KWIATY'",
    "klatka": "'WYJŚCIE', 'OGŁOSZENIE'", "osiedle": "'PACZKOMAT', 'ZAKAZ PARKOWANIA'",
}


def obiekty_miejsca(miejsce_id):
    """Prawdziwe obiekty dla miejsca: {id: (etykieta PL, fraza EN, miasto)} (puste = miejsce juz jest konkretne, np. Rynek)."""
    lista = OBIEKTY_MIEJSC.get(miejsce_id)
    return dict(lista[0]) if lista else {}


def miasto_z_tekstu(tekst):
    """'w Poznaniu', 'we Wrocławiu', 'w Warszawie' -> klucz MIASTA albo None."""
    t = " " + _bez_ogonkow(tekst) + " "
    return next((k for k, rdzenie in _RDZENIE_MIAST.items() if any(r in t for r in rdzenie)), None)


def wybierz_obiekt(miejsce_id, tekst="", los=None, chce=None, unikaj=()):
    """Konkretny prawdziwy obiekt (np. galeria Posnania) dla miejsca: `chce` (id, gdy pasuje), potem miasto z pomyslu, potem los
    (bez obiektow z `unikaj` - np. odrzuconych przez filtr IP). None = miejsce bez listy obiektow."""
    obiekty = obiekty_miejsca(miejsce_id)
    if not obiekty:
        return None
    if chce in obiekty:
        return chce
    kandydaci = [k for k in obiekty if k not in set(unikaj or ())] or list(obiekty)
    miasto = miasto_z_tekstu(tekst)
    z_miasta = [k for k in kandydaci if obiekty[k][2] == miasto]
    los = los or random.Random()
    return _wybierz(los, sorted(z_miasta or kandydaci))


def fraza_miejsca(miejsce_id, obiekt_id):
    """'krotko' miejsca z prawdziwa nazwa obiektu (np. 'the food court of the Posnania shopping centre in Poznań')."""
    m = MIEJSCA[miejsce_id]
    obiekty = obiekty_miejsca(miejsce_id)
    if not obiekt_id or obiekt_id not in obiekty:
        return m["krotko"]
    return OBIEKTY_MIEJSC[miejsce_id][1].format(o=obiekty[obiekt_id][1], k=m["krotko"])


# ---------------- gotowe pomysly ("Losuj pomysl") ----------------
# Pomysl = miejsce + (opcjonalnie) wlasne beaty/reakcje/kamera/komentarz; brakujace pola bierze z miejsca.

POMYSLY = [
    {"id": "galeria_fastfood", "miejsce": "galeria_foodcourt", "komentarz": "Jak ona wygląda.",
     "pl": "W galerii handlowej zamawia jedzenie w kiosku fast-food, pani obok zakrywa usta ze śmiechu"},
    {"id": "market_kasa", "miejsce": "dyskont", "komentarz": "Patrz, patrz…",
     "pl": "W dyskoncie stoi w kolejce do kasy z koszykiem, kasjerka i starsza pani się przyglądają"},
    {"id": "przystanek_tramwaj", "miejsce": "przystanek", "komentarz": "Co ona ma na sobie?",
     "pl": "Czeka na tramwaj w centrum, podjeżdża tramwaj, chłopak na ławce szturcha kolegę"},
    {"id": "sklep_osiedlowy", "miejsce": "sklep_osiedlowy", "komentarz": "O matko…",
     "pl": "W sklepiku pod blokiem kupuje hot-doga i puszkę, chłopaki w dresach się gapią"},
    {"id": "dworzec", "miejsce": "dworzec", "komentarz": "Zobacz, zobacz…",
     "pl": "Na dworcu patrzy na tablicę odjazdów, ludzie z walizkami się odwracają"},
    {"id": "rynek_obwarzanek", "miejsce": "rynek_krakow", "komentarz": "Jak ona wygląda.",
     "pl": "Na Rynku w Krakowie kupuje obwarzanka, para w ogródku kawiarni przestaje gadać"},
    {"id": "lawka_blok", "miejsce": "osiedle", "komentarz": "Teraz tak się chodzi?",
     "pl": "Siedzi na ławce pod blokiem z telefonem, dwie starsze panie wymieniają spojrzenia",
     "beaty": ["she sits on a worn bench under the block, scrolling her phone with her legs crossed",
               "she laughs quietly at something on the screen and types a reply",
               "she gets up, brushes off her clothes and walks towards the stairwell door"],
     "streszczenie": "{IMIE} sits on a bench between the blocks, busy with her phone, while two old ladies exchange looks.",
     "reakcje": "two elderly ladies on the next bench exchange looks and one of them shakes her head; a boy on a scooter rides "
                "past and stares"},
    {"id": "paczkomat", "miejsce": "osiedle", "komentarz": "Ej, patrz na nią.",
     "pl": "Odbiera paczkę z paczkomatu między blokami, sąsiedzi się gapią"},
    {"id": "klatka", "miejsce": "klatka", "komentarz": "O matko…",
     "pl": "Wraca do bloku, wyjmuje listy ze skrzynki, sąsiad z workiem śmieci staje jak wryty"},
    {"id": "bulwary", "miejsce": "bulwary", "komentarz": "Ej, patrz na nią.",
     "pl": "Idzie bulwarem nad Wisłą, rowerzysta przejeżdża przed kamerą, grupka na schodach milknie"},
    {"id": "metro_schody", "miejsce": "metro", "komentarz": "Patrz, patrz…",
     "pl": "Jedzie ruchomymi schodami w metrze, ludzie z naprzeciwka się odwracają"},
    {"id": "stacja_paliw", "miejsce": "stacja_paliw", "komentarz": "No to mamy cyrk.",
     "pl": "Na stacji benzynowej czeka na kawę i płaci telefonem, kierowca TIR-a się gapi"},
    {"id": "zapiekanka", "miejsce": "plac_nowy", "komentarz": "Jak ona wygląda.",
     "pl": "Na Placu Nowym w Krakowie je zapiekankę, ludzie w kolejce się gapią"},
    {"id": "oscypek", "miejsce": "krupowki", "komentarz": "Zobacz, zobacz…",
     "pl": "Na Krupówkach kupuje grillowanego oscypka z żurawiną"},
    {"id": "parawany", "miejsce": "plaza", "komentarz": "Co ona ma na sobie?",
     "pl": "Idzie przez plażę między parawanami z gofrem, rodzinka przestaje jeść"},
    {"id": "molo", "miejsce": "molo_sopot", "komentarz": "Ale odwaga.",
     "pl": "Spaceruje po molo w Sopocie, wiatr rozwiewa jej włosy, mewa ją straszy"},
    {"id": "bazar", "miejsce": "bazar", "komentarz": "Patrz, patrz…",
     "pl": "Na bazarze kupuje truskawki, sprzedawczyni mierzy ją wzrokiem"},
    {"id": "drogeria", "miejsce": "drogeria", "komentarz": "Ej, patrz na nią.",
     "pl": "W drogerii testuje szminkę przy lusterku, dziewczyny obok chichoczą"},
    {"id": "poczta", "miejsce": "poczta", "komentarz": "Teraz tak się chodzi?",
     "pl": "Na poczcie czeka z numerkiem w kolejce, starszy pan patrzy znad okularów"},
    {"id": "tramwaj", "miejsce": "tramwaj", "komentarz": "O matko…",
     "pl": "Jedzie tramwajem, babcia z wózkiem na zakupy gapi się bez przerwy"},
    {"id": "pociag", "miejsce": "pociag", "komentarz": "Zobacz, zobacz…",
     "pl": "W pociągu je kanapkę i pokazuje bilet konduktorowi"},
    {"id": "kebab", "miejsce": "kebab", "komentarz": "No to mamy cyrk.",
     "pl": "Wieczorem zamawia kebaba, kucharz się uśmiecha, klient przestaje jeść"},
    {"id": "krasnale", "miejsce": "rynek_wroclaw", "komentarz": "Jak ona wygląda.",
     "pl": "We Wrocławiu robi sobie selfie z krasnalem na Rynku"},
    {"id": "koziolki", "miejsce": "poznan", "komentarz": "Patrz, patrz…",
     "pl": "W Poznaniu czeka na koziołki, a ludzie nagrywają ją zamiast ratusza"},
    {"id": "silownia", "miejsce": "silownia_plenerowa", "komentarz": "Ale odwaga.",
     "pl": "Ćwiczy na siłowni plenerowej pod blokiem obok emeryta"},
    {"id": "orlik", "miejsce": "orlik", "komentarz": "Ej, patrz na nią.",
     "pl": "Idzie obok Orlika, piłka wylatuje za płot, kopie ją z powrotem"},
    {"id": "wiewiorka", "miejsce": "lazienki", "komentarz": "Zobacz, zobacz…",
     "pl": "W Łazienkach karmi wiewiórkę, przechodzi paw"},
    {"id": "paczek", "miejsce": "piekarnia", "komentarz": "Teraz tak się chodzi?",
     "pl": "Rano w piekarni kupuje pączka i bułki"},
    {"id": "przejscie", "miejsce": "przejscie_dla_pieszych", "komentarz": "Co ona ma na sobie?",
     "pl": "Czeka na zielone na przejściu w centrum, kierowca w aucie się pochyla, żeby zobaczyć"},
    {"id": "palac_kultury", "miejsce": "palac_kultury", "komentarz": "Jak ona wygląda.",
     "pl": "Idzie przez plac pod Pałacem Kultury, skejci przestają jeździć"},
    {"id": "plac_zamkowy", "miejsce": "plac_zamkowy", "komentarz": "Patrz, patrz…",
     "pl": "Na Placu Zamkowym z kawą robi zdjęcie zamku, turyści nagrywają ją"},
    {"id": "gdansk", "miejsce": "gdansk", "komentarz": "O matko…",
     "pl": "Na Długim Targu w Gdańsku ogląda bursztyny"},
    {"id": "miasteczko", "miejsce": "miasteczko", "komentarz": "Teraz tak się chodzi?",
     "pl": "Czeka na autobus na rynku małego miasteczka, emeryt na ławce patrzy bez słowa"},
    {"id": "dzialki", "miejsce": "dzialki", "komentarz": "Zobacz, zobacz…",
     "pl": "Idzie przez ogródki działkowe, dziadek podaje jej jabłko przez płot"},
]
POMYSLY_PO_ID = {p["id"]: p for p in POMYSLY}

# ---------------- wolny tekst po polsku: miejsce i czynnosc ze slow-kluczy ----------------

CZYNNOSCI = [   # (rdzenie bez ogonkow, opis EN) - podpowiedz po angielsku obok zdania usera
    (("zamawia", "zamowi", "kiosk"), "she orders food"),
    (("kawe", "kawa", "kawy", "kawka"), "she has a takeaway coffee"),
    (("placi", "zaplac", "kasie", "kasjer", "terminal"), "she pays at the till"),
    (("tanczy", "tancz", "taniec"), "she dances a little, shy and self-conscious"),
    (("selfie", "zdjeci", "fotk"), "she takes a photo with her phone"),
    (("telefon", "scroll", "esemes"), "she looks at her phone"),
    (("zapiekank",), "she eats a zapiekanka, a long toasted open baguette with mushrooms, cheese and ketchup"),
    (("kebab", "kebs"), "she eats a kebab wrap"),
    (("hot dog", "hot-dog", "hotdog", "parowk"), "she eats a hot dog"),
    (("lody", "loda", "lodem"), "she eats an ice-cream cone"),
    (("obwarzan", "precel"), "she eats a ring-shaped Kraków bagel"),
    (("oscyp",), "she eats a grilled smoked cheese with cranberry jam"),
    (("gofr",), "she eats a waffle with whipped cream"),
    (("paczkomat", "odbiera paczk"), "she picks up a parcel from a yellow parcel locker"),
    (("zakupy", "kupuje", "koszyk", "wozek"), "she does some shopping"),
    (("siedzi", "lawce", "lawk"), "she sits on a bench"),
    (("spacer", "idzie", "przechodzi", "chodzi"), "she walks along"),
    (("psem", "piesk", "pies"), "she walks a small dog on a lead"),
    (("hulajnog",), "she rides an electric scooter slowly"),
    (("rower",), "she pushes a city bike"),
    (("smieci",), "she takes the rubbish out to the bin shelter"),
    (("dzwoni", "rozmawia przez telefon"), "she talks on the phone"),
    (("biegnie", "biega", "spieszy", "spoznion"), "she hurries"),
    (("czeka",), "she waits"),
    (("pije",), "she drinks something"),
    (("je ", "zjada", "jedzenie", "obiad", "sniadan"), "she eats"),
]
REAKCJE_SLOWA = [   # (rdzenie, klucz REAKCJE) - pierwsza pasujaca
    (("nagrywa", "filmuje"), "nagrywa"),
    (("smieje", "smieja", "smiech", "chichocz", "parska"), "smiech"),
    (("krzywo", "ocenia", "kreci glowa", "oburz", "zgorsz"), "krzywo"),
    (("szepcz", "szept"), "szept"),
    (("gapi", "patrzy", "patrza", "oglada", "ogladaja", "przyglada"), "gapienie"),
]
_SAME_MIASTA = ("krakow", "wroclaw", "poznan", "lodz", "gdansk", "katowic", "slask", "trojmiast")
_OGONKI = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _bez_ogonkow(tekst):
    t = (tekst or "").translate(_OGONKI).lower()
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def _pasuje(tekst_norm, rdzenie):
    return any(r in tekst_norm for r in rdzenie)


def pomysl_z_tekstu(tekst):
    """Wolny pomysl po polsku -> {"miejsce": id|None, "czynnosci": [EN], "reakcja": klucz|None}. Bez LLM: rdzenie slow."""
    t = " " + _bez_ogonkow(tekst) + " "
    miejsce = None
    # kolejnosc: najpierw miejsca z dluzszymi/pewniejszymi slowami (wnetrze pociagu przed peronem, przystanek przed tramwajem);
    # sama nazwa miasta ("we Wroclawiu") wybiera miejsce dopiero, gdy nic innego nie pasuje - "w galerii we Wroclawiu" = galeria
    kolejnosc = ("pociag", "przystanek", "przejscie_dla_pieszych", "przejscie_podziemne", "plac_nowy", "plac_zamkowy",
                 "lazienki", "rynek_krakow", "rynek_wroclaw", "palac_kultury", "nowy_swiat", "galeria_foodcourt",
                 "galeria_pasaz") + tuple(MIEJSCA)
    for tylko_miejsca in (True, False):
        for mid in kolejnosc:
            slowa = [s for s in MIEJSCA[mid]["slowa"] if not (tylko_miejsca and s in _SAME_MIASTA)]
            if _pasuje(t, slowa):
                miejsce = mid
                break
        if miejsce:
            break
    czynnosci = []
    for rdzenie, en in CZYNNOSCI:
        if _pasuje(t, rdzenie) and en not in czynnosci:
            czynnosci.append(en)
    reakcja = next((k for rdzenie, k in REAKCJE_SLOWA if _pasuje(t, rdzenie)), None)
    return {"miejsce": miejsce, "czynnosci": czynnosci[:3], "reakcja": reakcja}


# ---------------- persona: tozsamosc, wlosy, wzrost ----------------

_WZORZEC_TOKENU_HF = re.compile(r"@\[Image\s*(\d+)\]\(image_\d+\)", re.I)
_WLOSY_W_CESZE = re.compile(r"\bhair\b|\bbangs\b|fringe|cent(?:er|re) part|parting|face-framing|streaks|highlights", re.I)


def _cechy_z_sekcji(tekst):
    """Sekcja '# 2. ... IDENTITY' promptu A persony -> (lista cech '* ...', zdania o tatuazach)."""
    linie = (tekst or "").splitlines()
    start = next((i for i, l in enumerate(linie) if re.match(r"^#\s*2\.\s.*IDENTITY", l, re.I)), None)
    if start is None:
        return [], []
    cechy, zdania = [], []
    for l in linie[start + 1:]:
        if re.match(r"^#\s*\d+\.", l):
            break
        s = l.strip()
        if s.startswith(("* ", "- ")):
            cechy.append(s[2:].strip().rstrip("."))
        elif re.search(r"tattoo", s, re.I) and not s.lower().startswith("do not"):
            z = _WZORZEC_TOKENU_HF.sub(lambda m: f"<<<image_{m.group(1)}>>>", s)
            zdania.append(re.sub(r"\s*\(see section \d+\)", "", z).rstrip("."))
    return cechy, zdania


def _plik_tozsamosci(slug):
    return os.path.join(baza.folder_modelki(slug), "prompty", "tozsamosc.txt")


def tozsamosc(slug, bez_wlosow=False, limit=700):
    """Opis twarzy/ciala persony po angielsku (bez ubrania). Zrodlo: prompty/tozsamosc.txt (gdy user go napisze) albo sekcja
    '# 2. ... EXACT IDENTITY' promptu A. bez_wlosow=True: bez cech o wlosach (wlosy opisuje osobno blok Hair)."""
    plik = _plik_tozsamosci(slug)
    if os.path.isfile(plik):
        with open(plik, encoding="utf-8-sig") as f:
            tekst = f.read().strip()
        if not bez_wlosow:
            return tekst
        czesci = [c.strip() for c in re.split(r";|\n", tekst) if c.strip()]
        return "; ".join(c for c in czesci if not _WLOSY_W_CESZE.search(c)).rstrip(".")
    cechy, zdania = _cechy_z_sekcji(baza.prompt_bazowy(slug))
    if bez_wlosow:
        cechy = [c for c in cechy if not _WLOSY_W_CESZE.search(c)]
    ogon = "".join(". " + z for z in zdania)
    wynik = ""
    for c in cechy:
        c = c if not wynik else c[:1].lower() + c[1:]
        nowy = (wynik + "; " if wynik else "") + c
        if len(nowy) + len(ogon) > limit:
            break
        wynik = nowy
    if not wynik and not ogon:
        prof = baza.profil_modelki(slug)
        wynik = ", ".join(c for c in (prof.get("cechy") or []) if not (bez_wlosow and _WLOSY_W_CESZE.search(c)))
    return (wynik[:1].upper() + wynik[1:] + ogon).strip()


def wlosy_wlasne(slug):
    """Wlosy persony ze zdjec (EN): profil.wlosy (np. Noemi: platyna - prompt A mowi o zlotych/brzoskwiniowych) albo cechy o
    wlosach z sekcji tozsamosci; zawsze z dopiskiem 'exact shade as in the reference photos'."""
    prof = baza.profil_modelki(slug)
    if (prof.get("wlosy") or "").strip():
        opis = prof["wlosy"].strip().rstrip(".")
    else:
        cechy, _ = _cechy_z_sekcji(baza.prompt_bazowy(slug))
        wl = [c for c in cechy if _WLOSY_W_CESZE.search(c)]
        if not wl:
            wl = [c for c in (prof.get("cechy") or []) if _WLOSY_W_CESZE.search(c)]
        opis = "; ".join(w[:1].lower() + w[1:] for w in wl) or "her own hair"
    if "reference photo" not in opis.lower():
        opis += ", exact colour and shade as in the reference photos"
    return opis


def wlosy_opis(slug, wybor=None):
    """(opis EN, zmienione: bool). wybor = {"kolor", "fryzura", "grzywka"} (klucze WLOSY_*); brak/wszystko 'wlasne' = jej wlosy."""
    w = dict(wybor or {})
    kolor_k = w.get("kolor") or "wlasne"
    kolor = WLOSY_KOLORY.get(kolor_k)
    if kolor is None:
        raise ValueError(f"Nieznany kolor wlosow '{kolor_k}'.")
    fryz_k = w.get("fryzura") or "wlasna"
    grzyw_k = w.get("grzywka") or "wlasna"
    if fryz_k == "wlasna" and len(kolor) > 2:
        fryz_k = kolor[2]                    # gotowy zestaw (np. Miku: dwa dlugie kucyki + prosta grzywka)
    if grzyw_k == "wlasna" and len(kolor) > 3:
        grzyw_k = kolor[3]
    if fryz_k not in WLOSY_FRYZURY or grzyw_k not in WLOSY_GRZYWKI:
        raise ValueError(f"Nieznana fryzura/grzywka ('{fryz_k}', '{grzyw_k}').")
    if kolor[1] is None and fryz_k == "wlasna" and grzyw_k == "wlasna":
        return wlosy_wlasne(slug), False
    if kolor[1] is None:
        baza_opis = "her own natural hair colour exactly as in the reference photos"
    else:
        baza_opis = f"{kolor[1]} hair"
    czesci = [baza_opis]
    if WLOSY_FRYZURY[fryz_k][1]:
        czesci.append(WLOSY_FRYZURY[fryz_k][1])
    elif kolor[1] is not None:
        czesci.append("same length and cut as in the reference photos")
    if WLOSY_GRZYWKI[grzyw_k][1]:
        czesci.append(WLOSY_GRZYWKI[grzyw_k][1])
    return ", ".join(czesci) + (" (only her hair is changed: face, eyebrows, make-up, piercings and body stay exactly as in "
                                "the photos)"), True


ZAKRES_WZROSTU = re.compile(r"^\s*(\d{3})(?:\s*[-–]\s*(\d{3}))?\s*(?:cm)?\s*$")


def _wzrost(wartosc):
    """'158-160' / '170' / 165 / [158, 160] -> (od, do) w cm albo None."""
    if isinstance(wartosc, (list, tuple)) and wartosc:
        a, b = int(wartosc[0]), int(wartosc[-1])
    elif isinstance(wartosc, (int, float)):
        a = b = int(wartosc)
    else:
        m = ZAKRES_WZROSTU.match(str(wartosc or ""))
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not (120 <= a <= 220 and 120 <= b <= 220):
        return None
    return (min(a, b), max(a, b))


def zdanie_wzrostu(wartosc):
    """Wzrost persony -> zdanie EN ze skala wzgledem ludzi (sr. Polka ~165 cm, Polak ~179 cm) albo ''."""
    w = _wzrost(wartosc)
    if not w:
        return ""
    a, b = w
    s = (a + b) / 2
    zakres = f"{a}-{b} cm" if a != b else f"{a} cm"
    if s < 162:
        jaka, kobiety = "petite", "noticeably shorter than most women around her"
    elif s < 165:
        jaka, kobiety = "on the short side", "a little shorter than most women around her"
    elif s < 167:
        jaka, kobiety = "of average height", "about as tall as most women around her"
    elif s < 170:
        jaka, kobiety = "fairly tall", "a little taller than most women around her"
    else:
        jaka, kobiety = "tall for a woman", "taller than most women around her"
    if s <= 159.5:
        mezczyzna = "only about the chin"
    elif s <= 163:
        mezczyzna = "about the mouth"
    elif s <= 166:
        mezczyzna = "about the nose"
    elif s <= 169.5:
        mezczyzna = "about the eyes"
    elif s <= 174:
        mezczyzna = "about the forehead"
    else:
        mezczyzna = "almost the top of the head"
    return (f"She is {jaka}, about {zakres} tall: {kobiety}, and the top of her head reaches {mezczyzna} of an average man. "
            f"Keep this real scale next to people, doors, counters and shelves.")


# ---------------- obrazy (ta sama kolejnosc dla promptu i dla --image) ----------------

def obrazy_rolki(slug, stroj_plik=None):
    """Zdjecia rolki w kolejnosci numeracji: referencje persony (01_, 02_...), na koncu zdjecie stroju (gdy jest)."""
    obrazy = list(baza.sciezki_referencji(slug))
    if stroj_plik:
        obrazy.append(stroj_plik)
    return obrazy


def plik_stroju(slug, nazwa):
    """Nazwa pliku z folderu stroje/ persony -> pelna sciezka (tylko z tego folderu)."""
    nazwa = os.path.basename(str(nazwa or ""))
    sciezka = os.path.join(baza.folder_strojow(slug), nazwa)
    if not nazwa or not nazwa.lower().endswith(baza.ROZSZERZENIA_OBRAZU) or not os.path.isfile(sciezka):
        raise ValueError(f"Nie ma zdjecia stroju '{nazwa}' w folderze Stroje tej persony.")
    return sciezka


# ---------------- os czasu, szablony ----------------

def os_czasu(sek, beaty):
    """3 beaty -> ciagle przedzialy bez dziur (8 s: 0-3/3-6/6-8, 10 s: 0-3/3-7/7-10, 15 s: 0-5/5-10/10-15)."""
    sek = int(sek)
    if sek <= 8:
        granice = [(0, 3), (3, 6), (6, sek)]
    elif sek <= 10:
        granice = [(0, 3), (3, 7), (7, sek)]
    else:
        t = sek // 3
        granice = [(0, t), (t, 2 * t), (2 * t, sek)]
    return " ".join(f"{a}-{b} s: {b_}." for (a, b), b_ in zip(granice, beaty)), granice


SZABLON_PELNY = (
    "Real vertical phone video, not a film: a candid {SEK}-second 9:16 clip that a passer-by secretly filmed on an iPhone in "
    "{KROTKO}, Poland, on an ordinary {PORA} in {SEZON}. {STRESZCZENIE}\n"
    "[References] {REF} show one and the same young woman, {IMIE}: the only source of her face, eyes, skin, {WLOSY_REF}piercings "
    "and body proportions. Keep her exactly recognizable in every frame, never blend her with anyone, only one of her."
    "{LINIA_STROJU}\n"
    "[{IMIE}] {TOZ}. Hair: {WLOSY}. {WZROST}Outfit: {STROJ}.\n"
    "[Place] {OPIS} Real Polish details: {DETALE}. {SZYLDY} "
    "{POGODA}Ordinary Polish people of all ages in {SEZON} clothes ({UBRANIA}) go about their business; nobody looks like a "
    "model.\n"
    "[Action] {AKCJA}\n"
    "She acts like a normal person busy with her own task: relaxed posture, small weight shifts, natural hand movements; she "
    "never looks into the lens and never poses. Bystanders react only briefly and naturally: {REAKCJE}.{SUBTELNIE}\n"
    "[Camera] {KAMERA}\n"
    "[Phone look] {SWIATLO}. Auto exposure and white balance readjust visibly as the phone turns; bright windows and sky clip "
    "to white, shadows slightly muddy with fine digital noise; natural, slightly flat colours, mild over-sharpening and "
    "compression like an Instagram upload. Realistic skin texture, no beauty filter, no colour grading.\n"
    "[Sound] {DZWIEK}\n"
    "[Result] A real clip someone filmed in Poland and posted on Instagram: natural scale and perspective (feet on the ground, "
    "her height correct next to people and objects), real-world physics. No subtitles, captions, added text, stickers or "
    "watermarks."
)
# [Camera]: klasyczna (nagrywajacy idzie/stoi obok) albo z ukrycia (KAMERY_UKRYTE - nigdy nie podchodzi, ona nie widzi telefonu)
KAMERA_KLASYCZNA = ("Ordinary iPhone, main 1x lens (about 24 mm), hand-held at chest-to-eye height by someone {OPERATOR}, "
                    "filming discreetly: constant small shake, off-centre framing corrected late, people sometimes pass between "
                    "the lens and her. {RUCH} Deep phone focus, the background as sharp as she is. No tripod, gimbal, drone, slow "
                    "motion or cinematic moves.")
KAMERA_Z_UKRYCIA = ("Ordinary iPhone (1x lens, a little digital zoom), secretly filmed by someone {OPERATOR} who pretends not to "
                    "be filming. {RUCH} They keep their distance the whole time and never walk up to her; she never notices the "
                    "phone. Constant small hand shake, deep phone focus, the background as sharp as she is. No tripod, gimbal, "
                    "drone, slow motion or cinematic moves.")
# [Sound]: komentarz mowi model wideo (z_modelem) albo wideo ma tylko dzwiek otoczenia, a komentarz dogrywa ElevenLabs (bez_mowy)
DZWIEK_Z_MODELEM = ("Phone-microphone sound: {DZWIEKI}; people nearby talk in Polish (words unclear). Dialogue language: "
                    "Polish. {KOMENTARZ}No background music.")
DZWIEK_BEZ_MOWY = ("Phone-microphone sound only: {DZWIEKI}; people nearby murmur in Polish (words unclear). The person filming "
                   "stays silent: no clear speech close to the phone. No background music.")

SZABLON_KROTKI = (
    "Candid vertical 9:16 smartphone video, real footage, not a film: someone secretly films {IMIE}, the young woman from the "
    "reference photos, in {KROTKO}, Poland, on an ordinary {PORA} in {SEZON}. Keep her face, skin, piercings and body exactly as "
    "in the reference photos; never blend her with anyone; only one of her. {TOZ}. Hair: {WLOSY}. {WZROST}Outfit: {STROJ}.\n"
    "Place: {OPIS} {SZYLDY} Ordinary Polish people in {SEZON} clothes go about their business.\n"
    "Action: {AKCJA} She never looks into the lens and never poses. Bystanders: {REAKCJE}.{SUBTELNIE}\n"
    "Camera: {KAMERA}\n"
    "Look: {SWIATLO}; phone auto exposure, windows and sky blown out, slight noise in the shadows, natural flat colours, "
    "realistic skin, no beauty filter.\n"
    "Sound: {DZWIEK}\n"
    "No subtitles, captions, text overlays or watermarks."
)
KAMERA_KROTKA = "ordinary iPhone, 1x lens, hand-held by someone {OPERATOR}: small shake, off-centre framing, deep focus, no cinematic moves. {RUCH}"
KAMERA_KROTKA_UKRYTA = ("ordinary iPhone, secretly filmed by someone {OPERATOR} who pretends not to film and never walks up to "
                        "her: {RUCH} Small shake, deep focus, no cinematic moves.")
DZWIEK_KROTKI_Z_MODELEM = "ambience ({DZWIEKI}); dialogue language Polish. {KOMENTARZ}No music."
DZWIEK_KROTKI_BEZ_MOWY = "ambience only ({DZWIEKI}), Polish murmur in the background; the person filming stays silent. No music."


def szyldy(miejsce_id, nazwy="prawdziwe", obiekt_id=None):
    """Zdanie o napisach: prawdziwe polskie slowa i ceny w zl (user: wymyslone nazwy sklepow i 'Z6£' zamiast zl)."""
    przyklad = SZYLDY.get(miejsce_id)
    zdanie = "Signs are in correct Polish with Polish letters" + (f" (e.g. {przyklad})" if przyklad else "")
    zdanie += "; prices are written the Polish way, like '19,99 zł'"
    obiekty = obiekty_miejsca(miejsce_id)
    if nazwy == "prawdziwe" and obiekt_id in obiekty and miejsce_id in ("galeria_foodcourt", "galeria_pasaz"):
        zdanie += f"; the real name {obiekty[obiekt_id][0].split(' (')[0]} appears on the mall's own signs"
    if nazwy != "prawdziwe":
        zdanie += "; no brand logos"
    return zdanie + "."


def _pierwsze_zdanie(tekst):
    m = re.match(r"(.+?[.!?])(\s|$)", tekst or "")
    return m.group(1) if m else (tekst or "")


def _lista_tokenow(n, start=1):
    tok = [f"<<<image_{i}>>>" for i in range(start, start + n)]
    return tok[0] if n == 1 else ", ".join(tok[:-1]) + " and " + tok[-1]


# ---------------- budowanie ----------------

def _wybierz(los, lista):
    return lista[los.randrange(len(lista))]


def uzyte_pomysly(slug, dni=14):
    """Id gotowych pomyslow uzytych w rolkach z promptu w ostatnich `dni` dniach (do losowania bez powtorek)."""
    from datetime import datetime, timedelta
    granica = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d")
    wynik = []
    for p in baza.lista_pomyslow(slug):
        zp = p.get("z_promptu") if isinstance(p.get("z_promptu"), dict) else None
        if zp and zp.get("pomysl_id") and baza.dzien_lokalny(p.get("utworzono")) >= granica:
            wynik.append(zp["pomysl_id"])
    return wynik


def losuj_pomysl(slug=None, sezon=None, uzyte=None, los=None):
    """Losowy gotowy pomysl (bez powtorek z ostatnich 14 dni, gdy sie da; plaza tylko latem). Zwraca slownik z POMYSLY."""
    los = los or random.Random()
    sezon = sezon if sezon in SEZONY else sezon_z_daty()
    uzyte = set(uzyte if uzyte is not None else (uzyte_pomysly(slug) if slug else []))
    pasujace = [p for p in POMYSLY if sezon in (MIEJSCA[p["miejsce"]].get("sezony") or (sezon,))]
    swieze = [p for p in pasujace if p["id"] not in uzyte] or pasujace
    return _wybierz(los, swieze)


def model_info(model):
    if model not in MODELE:
        raise ValueError(f"Nieznany model '{model}'. Znam: {', '.join(MODELE)}")
    return MODELE[model]


def zbuduj(slug, opcje=None, los=None):
    """Pomysl -> gotowy prompt + lista zdjec. opcje (z panelu/CLI, wszystko opcjonalne):
        pomysl_id (z POMYSLY), tekst (wolny pomysl PL), miejsce ("" = dobierz, "losowe", id z MIEJSCA), model, dlugosc (8/10/15),
        rozdzielczosc ("auto" = <= 8 s -> 1080p, dluzsze -> 720p), wlosy {kolor, fryzura, grzywka}, stroj ("zdjecia" |
        "codzienny" | "cosplay" | "wlasny" | "plik:<nazwa ze stroje/>"), stroj_tekst, reakcja (klucz REAKCJE), komentarz
        ("losowy" | "bez" | "wlasny" | tekst z KOMENTARZE), komentarz_tekst, sezon ("auto" | klucz SEZONY), pora ("auto" |
        klucz PORY_DNIA), kamera ("auto" = z ukrycia wg miejsca | klucz KAMERY), ustalone (losowe wybory z poprzedniego
        budowania - ten sam prompt). zp-2: stroj "odwazny" | "odwazny:<id STROJE_ODWAZNE>", nazwy ("prawdziwe" | "opisowe"),
        obiekt (id z obiekty_miejsca, "" = wg miasta z pomyslu / losowo), glos ("model" | "tts"; "auto" rozstrzyga fabryka),
        wymowa ("zwykla" | "fonetyczna" - tylko komentarz mowiony przez model).
    Zwraca {"prompt", "obrazy" (sciezki), "znaki", "limit", "ostrzezenia", "ustalone", "model", "mode", "parametry",
            "generate_audio", "rozdzielczosc", "dlugosc", "tytul", "miejsce", "pomysl_id", "szablon", "glos", "komentarz",
            "komentarz_t" (sekunda komentarza - tam dogrywa go komentarz_glos.py), "obiekt", "nazwy", "stroj_id", "reakcja"}.
    Rzuca ValueError przy zlych opcjach (model, dlugosc, brak zdjec persony, za dlugi prompt...)."""
    o = dict(opcje or {})
    u = dict(o.get("ustalone") or {})
    ziarno = u.get("ziarno") or random.randrange(1, 10 ** 9)
    los = los or random.Random(ziarno)
    model = o.get("model") or MODEL_DOMYSLNY
    mi = model_info(model)
    try:
        dlugosc = int(o.get("dlugosc") or DLUGOSC_DOMYSLNA)
    except (TypeError, ValueError):
        raise ValueError("Dlugosc musi byc liczba sekund (8, 10 albo 15).")
    if dlugosc not in mi["dlugosci"]:
        raise ValueError(f"{mi['nazwa']}: dlugosc {dlugosc} s niedostepna (mozna: {', '.join(map(str, mi['dlugosci']))} s).")
    rozdz = (o.get("rozdzielczosc") or "auto").strip()
    rozdz = rozdzielczosc_auto(dlugosc, model) if rozdz == "auto" else rozdz
    if rozdz not in mi["rozdzielczosci"]:
        raise ValueError(f"{mi['nazwa']}: rozdzielczosc {rozdz} niedostepna (mozna: {', '.join(mi['rozdzielczosci'])}).")

    prof = baza.profil_modelki(slug)
    imie = (prof.get("nazwa") or slug).strip() or slug
    ostrzezenia = []

    # --- pomysl i miejsce ---
    tekst = (o.get("tekst") or "").strip()
    pomysl = POMYSLY_PO_ID.get(o.get("pomysl_id") or "")
    if pomysl and tekst and _bez_ogonkow(tekst).strip(" .") != _bez_ogonkow(pomysl["pl"]).strip(" ."):
        pomysl = None                       # user zmienil tekst gotowego pomyslu -> to juz jego wlasny pomysl
    if not pomysl and tekst:
        # tekst slowo w slowo jak gotowy pomysl (np. przegladarka przywrocila pole po odswiezeniu) -> ten pomysl z jego beatami
        pomysl = next((p for p in POMYSLY if _bez_ogonkow(p["pl"]).strip(" .") == _bez_ogonkow(tekst).strip(" .")), None)
    wybor_miejsca = (o.get("miejsce") or "").strip()
    if wybor_miejsca and wybor_miejsca != "losowe" and wybor_miejsca not in MIEJSCA:
        raise ValueError(f"Nieznane miejsce '{wybor_miejsca}'.")
    if not pomysl and not tekst:
        if wybor_miejsca in MIEJSCA:
            # samo miejsce bez pomyslu: gotowy pomysl z tego miejsca albo domyslne beaty miejsca
            kand = [p for p in POMYSLY if p["miejsce"] == wybor_miejsca]
            pomysl = (POMYSLY_PO_ID[u["pomysl_id"]] if u.get("pomysl_id") in {p["id"] for p in kand} else
                      (_wybierz(los, kand) if kand else {"id": None, "miejsce": wybor_miejsca, "pl": MIEJSCA[wybor_miejsca]["nazwa"]}))
        else:
            pomysl = POMYSLY_PO_ID.get(u.get("pomysl_id") or "") or losuj_pomysl(slug, los=los)
    analiza = pomysl_z_tekstu(tekst) if not pomysl else {"miejsce": None, "czynnosci": [], "reakcja": None}
    if wybor_miejsca in MIEJSCA:
        miejsce_id = wybor_miejsca
    elif wybor_miejsca == "losowe":
        miejsce_id = u.get("miejsce") if u.get("miejsce") in MIEJSCA else _wybierz(los, sorted(MIEJSCA))
    else:
        miejsce_id = (pomysl or {}).get("miejsce") or analiza["miejsce"]
        if not miejsce_id:
            miejsce_id = u.get("miejsce") if u.get("miejsce") in MIEJSCA else _wybierz(los, sorted(MIEJSCA))
            ostrzezenia.append(f"Nie rozpoznalem miejsca w pomysle - wylosowalem: {MIEJSCA[miejsce_id]['nazwa']}. Wybierz miejsce "
                               f"z listy, jesli ma byc inne.")
    m = MIEJSCA[miejsce_id]
    if pomysl and pomysl["miejsce"] != miejsce_id:
        tekst = tekst or pomysl["pl"]       # gotowy pomysl jest pod inne miejsce - zostaje jego tekst jako wolny pomysl
        pomysl = None
        analiza = pomysl_z_tekstu(tekst)

    # --- pora roku i dnia ---
    sezon = o.get("sezon") if o.get("sezon") in SEZONY else (u.get("sezon") if u.get("sezon") in SEZONY else sezon_z_daty())
    if m.get("sezony") and sezon not in m["sezony"] and o.get("sezon") not in SEZONY:
        sezon = m["sezony"][0]
    pora = o.get("pora") if o.get("pora") in PORY_DNIA else (
        u.get("pora") if u.get("pora") in PORY_DNIA else _wybierz(los, list(m.get("pory") or ("rano", "popoludnie"))))
    sz = SEZONY[sezon]

    # --- kamera (domyslnie z ukrycia: z daleka / z biodra / zza filaru - feedback usera 2026-10-07) ---
    kamera = o.get("kamera") if o.get("kamera") in KAMERY else (
        u.get("kamera") if u.get("kamera") in KAMERY else kamera_ukryta(miejsce_id))

    # --- prawdziwa nazwa miejsca (galeria Posnania, dworzec Kraków Główny, Jeżyce...) albo opis bez nazwy ---
    nazwy = (o.get("nazwy") or "prawdziwe").strip()
    if nazwy not in NAZWY_TRYBY:
        raise ValueError(f"Nieznany tryb nazw '{nazwy}' (prawdziwe albo opisowe).")
    obiekt = None
    if nazwy == "prawdziwe" and obiekty_miejsca(miejsce_id):
        chce = o.get("obiekt") if o.get("obiekt") in obiekty_miejsca(miejsce_id) else u.get("obiekt")
        obiekt = wybierz_obiekt(miejsce_id, tekst or (pomysl or {}).get("pl", ""), los, chce=chce)
    krotko = fraza_miejsca(miejsce_id, obiekt)

    # --- akcja ---
    if pomysl:
        beaty = pomysl.get("beaty") or m["akcje"]
        os_tekst, granice = os_czasu(dlugosc, beaty)
        akcja = os_tekst
        streszczenie = (pomysl.get("streszczenie") or m["streszczenie"]).format(IMIE=imie)
        t_kom = min(granice[1][0] + 2, dlugosc - 2)
        t1 = granice[1][0]
    else:
        hint = "; ".join(analiza["czynnosci"])
        akcja = (f"The scene, written in Polish (follow it literally): „{tekst}”."
                 + (f" In short: {hint}." if hint else "")
                 + f" It all happens naturally in one continuous take over the whole {dlugosc} seconds, at an everyday pace.")
        streszczenie = f"{imie} goes about an ordinary errand while people around notice her."
        t1 = max(2, dlugosc // 3)
        t_kom = max(3, int(dlugosc * 0.45))

    # --- reakcje ---
    rk = (o.get("reakcja") or "losowa").strip()
    if rk not in REAKCJE:
        raise ValueError(f"Nieznana reakcja '{rk}'.")
    if rk == "losowa":
        rk_auto = analiza.get("reakcja")
        reakcje = REAKCJE[rk_auto][1] if rk_auto else ((pomysl or {}).get("reakcje") or m["reakcje"])
    else:
        reakcje = REAKCJE[rk][1]
    zdziwienie = rk in REAKCJE_ZDZIWIENIE

    # --- stroj ---
    stroj_wybor = (o.get("stroj") or "zdjecia").strip()
    stroj_plik = None
    stroj_id = None
    linia_stroju = ""
    obrazy_n = len(baza.sciezki_referencji(slug))
    if not obrazy_n:
        raise ValueError(f"{imie} nie ma zdjec w referencje/ - bez nich model nie wie, kogo pokazac.")
    if stroj_wybor == "zdjecia":
        stroj = "the same outfit she wears in the reference photos"
    elif stroj_wybor == "odwazny" or stroj_wybor.startswith("odwazny:"):
        stroj_id = stroj_wybor.split(":", 1)[1] if ":" in stroj_wybor else (
            u.get("stroj_id") if u.get("stroj_tryb") == "odwazny" and u.get("stroj_id") in STROJE_ODWAZNE
            else _wybierz(los, sorted(stroje_odwazne_na(sezon))))
        if stroj_id not in STROJE_ODWAZNE:
            raise ValueError(f"Nieznany stroj '{stroj_id}'.")
        u["stroj_id"], u["stroj_tryb"] = stroj_id, "odwazny"
        stroj = (f"{STROJE_ODWAZNE[stroj_id][1]} - a bold, eye-catching street look that makes people turn their heads (not the "
                 f"clothes from the reference photos)")
    elif stroj_wybor == "codzienny":
        pasujace = [s for s, pory in STROJE_CODZIENNE if sezon in pory] or [s for s, _ in STROJE_CODZIENNE]
        opis = u.get("stroj_opis") if u.get("stroj_tryb") == "codzienny" and u.get("stroj_opis") else _wybierz(los, pasujace)
        u["stroj_opis"], u["stroj_tryb"] = opis, "codzienny"
        stroj = f"{opis}, her everyday style (not the clothes from the reference photos)"
    elif stroj_wybor == "cosplay":
        opis = u.get("stroj_opis") if u.get("stroj_tryb") == "cosplay" and u.get("stroj_opis") else _wybierz(los, STROJE_COSPLAY)
        u["stroj_opis"], u["stroj_tryb"] = opis, "cosplay"
        stroj = f"{opis}, a home-made looking costume worn in public on an ordinary day (not the clothes from the reference photos)"
    elif stroj_wybor == "wlasny":
        st = (o.get("stroj_tekst") or "").strip()
        if not st:
            raise ValueError("Opisz stroj (pole 'Wlasny opis') albo wybierz inny.")
        stroj = f"„{st}” (not the clothes from the reference photos)"
    elif stroj_wybor.startswith("plik:"):
        stroj_plik = plik_stroju(slug, stroj_wybor[5:])
        k = obrazy_n + 1
        if mi["tokeny"]:
            linia_stroju = (f" <<<image_{k}>>> is only the outfit reference: she wears exactly this clothing; never take face, "
                            f"hair or body from it.")
            stroj = f"exactly the clothing from <<<image_{k}>>>"
        else:
            stroj = "exactly the clothing from the last reference photo (that photo is only for the outfit, not her face)"
    else:
        raise ValueError(f"Nieznany wybor stroju '{stroj_wybor}'.")

    # --- wlosy, wzrost, tozsamosc ---
    wlosy, wlosy_zmienione = wlosy_opis(slug, o.get("wlosy"))
    wzrost = zdanie_wzrostu(prof.get("wzrost_cm"))
    if not wzrost:
        ostrzezenia.append(f"{imie} nie ma wzrostu w profilu (Ustawienia -> Persona -> Wzrost) - skala wzgledem ludzi bez liczb.")
    toz = tozsamosc(slug, bez_wlosow=True, limit=600 if mi["szablon"] == "pelny" else 300)
    if not toz:
        ostrzezenia.append("Nie znalazlem opisu twarzy persony (sekcja '# 2. ... IDENTITY' promptu A albo prompty/tozsamosc.txt) "
                           "- model oprze sie tylko na zdjeciach.")
        toz = f"{imie} looks exactly like in the reference photos"

    # --- komentarz ---
    kom = (o.get("komentarz") or "losowy").strip()
    if kom == "bez":
        kom_tekst = ""
    elif kom == "wlasny":
        kom_tekst = (o.get("komentarz_tekst") or "").strip()
        if not kom_tekst:
            raise ValueError("Wpisz wlasny komentarz albo wybierz inny.")
    elif kom == "losowy":
        pula = KOMENTARZE + (KOMENTARZE_COSPLAY if stroj_wybor == "cosplay" else [])
        kom_tekst = u.get("komentarz") if u.get("komentarz_tryb") == "losowy" and u.get("komentarz") else (
            (pomysl or {}).get("komentarz") if stroj_wybor != "cosplay" and pomysl else _wybierz(los, pula))
        u["komentarz_tryb"] = "losowy"
    else:
        kom_tekst = kom
    kom_tekst = re.sub(r"[{}„”\"]", "", kom_tekst).strip()[:80]
    if kom_tekst and kom_tekst[-1] not in ".!?…":
        kom_tekst += "."

    # --- swiatlo ---
    swiatlo = m["swiatlo"]
    if pora == "wieczor" and not m.get("wnetrze") and "evening" not in swiatlo and "dusk" not in swiatlo:
        swiatlo = WIECZOR_NA_ZEWNATRZ
    elif pora == "wieczor" and m.get("wnetrze") and "daylight" in swiatlo:
        swiatlo = ("only the artificial light of the place; it is dark outside and the windows reflect the interior, with "
                   "visible phone noise in darker corners")
    swiatlo = swiatlo[:1].upper() + swiatlo[1:]
    pogoda = "" if m.get("wnetrze") else sz["pogoda"] + " "
    if m.get("wnetrze") and sezon in ("jesien", "zima"):
        pogoda = f"People still wear their {sz['en']} jackets inside. "

    operator = (pomysl or {}).get("operator") or (m.get("operator") if kamera == m.get("kamera") else None) or KAMERY[kamera][1]
    ruch = KAMERY[kamera][2].format(t1=t1)
    ukryta = kamera in KAMERY_UKRYTE

    # --- glos komentarza: model wideo (opcjonalnie zapis fonetyczny ą/ę) albo cisza zza kamery + ElevenLabs po generacji ---
    glos = (o.get("glos") or "model").strip()
    if glos not in GLOSY:
        raise ValueError(f"Nieznany glos komentarza '{glos}'.")
    glos = "model" if glos == "auto" else glos           # "auto" rozstrzyga fabryka (klucz ElevenLabs) przed zbuduj()
    wymowa = (o.get("wymowa") or "zwykla").strip()
    if wymowa not in WYMOWY:
        raise ValueError(f"Nieznana wymowa '{wymowa}'.")
    mowi_model = bool(kom_tekst) and glos == "model"
    w_klamrach = fonetycznie(kom_tekst) if wymowa == "fonetyczna" else kom_tekst
    ton = "half-whispering in disbelief" if zdziwienie else "amused"
    po = "Then a quiet, stunned exhale" if zdziwienie else "Then a short stifled laugh"
    subtelnie = SUBTELNE_REAKCJE if zdziwienie else ""
    napisy = szyldy(miejsce_id, nazwy, obiekt)

    if mi["szablon"] == "pelny":
        komentarz = (f"At about {t_kom} s the person filming says quietly off-screen ({ton}, native Polish accent): "
                     f"{{{w_klamrach}}} {po}; {imie} does not react. ") if mowi_model else ""
        dzwiek = (DZWIEK_Z_MODELEM if glos == "model" or not kom_tekst else DZWIEK_BEZ_MOWY).format(
            DZWIEKI=m["dzwieki"], KOMENTARZ=komentarz)
        kamera_blok = (KAMERA_Z_UKRYCIA if ukryta else KAMERA_KLASYCZNA).format(OPERATOR=operator, RUCH=ruch)
        prompt = SZABLON_PELNY.format(
            SEK=dlugosc, KROTKO=krotko, PORA=PORY_DNIA[pora][1], SEZON=sz["en"], STRESZCZENIE=streszczenie,
            REF=_lista_tokenow(obrazy_n), IMIE=imie, WLOSY_REF="" if wlosy_zmienione else "hair, ",
            LINIA_STROJU=linia_stroju, TOZ=toz.rstrip("."), WLOSY=wlosy, WZROST=(wzrost + " ") if wzrost else "",
            STROJ=stroj, OPIS=m["opis"], DETALE=m["detale"], SZYLDY=napisy, POGODA=pogoda, UBRANIA=sz["ubrania"], AKCJA=akcja,
            REAKCJE=reakcje, SUBTELNIE=subtelnie, KAMERA=kamera_blok, SWIATLO=swiatlo, DZWIEK=dzwiek)
    else:
        komentarz = (f"At about {t_kom} s the person filming says quietly off-screen ({ton}): {{{w_klamrach}}} "
                     if mowi_model else "")
        dzwiek = (DZWIEK_KROTKI_Z_MODELEM if glos == "model" or not kom_tekst else DZWIEK_KROTKI_BEZ_MOWY).format(
            DZWIEKI=m["dzwieki"], KOMENTARZ=komentarz)
        kamera_blok = (KAMERA_KROTKA_UKRYTA if ukryta else KAMERA_KROTKA).format(OPERATOR=operator, RUCH=ruch)
        toz_k = _WZORZEC_TOKENU.sub("the reference photos", toz)
        prompt = SZABLON_KROTKI.format(
            IMIE=imie, KROTKO=krotko, PORA=PORY_DNIA[pora][1], SEZON=sz["en"], TOZ=toz_k.rstrip("."),
            WLOSY=wlosy, WZROST=(wzrost.split(":")[0] + ". ") if wzrost else "", STROJ=stroj, OPIS=_pierwsze_zdanie(m["opis"]),
            SZYLDY=napisy, AKCJA=akcja, REAKCJE=reakcje, SUBTELNIE=subtelnie, KAMERA=kamera_blok, SWIATLO=swiatlo,
            DZWIEK=dzwiek)
    prompt = re.sub(r"[ \t]+\n", "\n", re.sub(r"  +", " ", prompt)).strip()

    obrazy = obrazy_rolki(slug, stroj_plik)
    if not obrazy:
        raise ValueError(f"{imie} nie ma zdjec w referencje/ - bez nich model nie wie, kogo pokazac.")
    if len(obrazy) > mi["max_obrazow"]:
        raise ValueError(f"{mi['nazwa']} przyjmuje max {mi['max_obrazow']} zdjec, a ta rolka ma {len(obrazy)}.")
    bledy, uwagi = sprawdz(prompt, model, len(obrazy))
    if bledy:
        raise ValueError(" ".join(bledy))
    ostrzezenia += uwagi
    tytul = (pomysl["pl"] if pomysl else tekst)[:120]
    u.update({"ziarno": ziarno, "pomysl_id": (pomysl or {}).get("id"), "miejsce": miejsce_id, "sezon": sezon, "pora": pora,
              "kamera": kamera})
    if obiekt:
        u["obiekt"] = obiekt
    if kom_tekst and kom == "losowy":
        u["komentarz"] = kom_tekst
    obiekt_nazwa = obiekty_miejsca(miejsce_id)[obiekt][0] if obiekt else None
    return {
        "prompt": prompt, "obrazy": obrazy, "znaki": len(prompt), "limit": mi["limit_znakow"], "ostrzezenia": ostrzezenia,
        "ustalone": u, "model": model, "mode": mi["mode"], "parametry": dict(mi["parametry"]),
        "generate_audio": mi["generate_audio"], "rozdzielczosc": rozdz, "dlugosc": dlugosc, "tytul": tytul,
        "miejsce": miejsce_id, "miejsce_nazwa": m["nazwa"] + (f" – {obiekt_nazwa}" if obiekt_nazwa else ""),
        "pomysl_id": (pomysl or {}).get("id"), "szablon": WERSJA_SZABLONU,
        "wlosy_zmienione": wlosy_zmienione, "stroj_plik": stroj_plik, "komentarz": kom_tekst,
        "sezon": sezon, "pora": pora, "kamera": kamera, "glos": glos if kom_tekst else "bez", "wymowa": wymowa,
        "komentarz_t": t_kom if kom_tekst else None, "obiekt": obiekt, "obiekt_nazwa": obiekt_nazwa, "nazwy": nazwy,
        "stroj_id": stroj_id, "stroj_tryb": stroj_wybor.split(":")[0], "reakcja": rk,
    }


# ---------------- sprawdzanie promptu ----------------

_WZORZEC_TOKENU = re.compile(r"<<<image_(\d+)>>>")
MARKI = ("mcdonald", "kfc", "burger king", "zabka", "biedronk", "lidl", "rossmann", "orlen", "inpost", "starbucks",
         "coca-cola", "coca cola", "pepsi", "nike", "adidas", "pikachu", "pokemon", "hatsune", "miku", "disney", "hello kitty",
         "louis vuitton", "gucci", "chanel", "marvel", "barbie", "naruto", "sailor moon")


def sprawdz(prompt, model, n_obrazow):
    """(bledy, ostrzezenia) promptu rolki z promptu. Bledy blokuja wycene i wyslanie; ostrzezenia tylko pokazujemy."""
    import fabryka
    mi = model_info(model)
    bledy, uwagi = [], []
    tekst = prompt or ""
    if not tekst.strip():
        bledy.append("Prompt jest pusty.")
    if len(tekst) > mi["limit_znakow"]:
        bledy.append(f"Prompt ma {len(tekst)} znakow, a {mi['nazwa']} przyjmie max ok. {mi['limit_znakow']} - skroc pomysl.")
    elif len(tekst) > mi["zalecane_znaki"]:
        uwagi.append(f"Prompt ma {len(tekst)} znakow (zalecane do {mi['zalecane_znaki']}) - krotszy model lepiej slucha.")
    tokeny = sorted({int(x) for x in _WZORZEC_TOKENU.findall(tekst)})
    if mi["tokeny"]:
        if any(t > n_obrazow or t < 1 for t in tokeny):
            bledy.append(f"Prompt odwoluje sie do zdjecia nr {max(tokeny)}, a rolka ma tylko {n_obrazow} zdjec.")
        if not tokeny:
            uwagi.append("Prompt nie wskazuje zdjec persony (<<<image_N>>>) - twarz moze wyjsc inna.")
    elif tokeny or _WZORZEC_TOKENU_HF.search(tekst):
        bledy.append(f"{mi['nazwa']} nie zna numerow zdjec (<<<image_N>>> / @[Image N]) - pisz 'the reference photos'.")
    if re.search(r"\n[ \t]*\n", tekst):
        uwagi.append("Pusta linia w prompcie - CLI Higgsfield skleja akapity (blad CLI #94), tresc zostaje.")
    if tekst.count("Dialogue language: Polish") > 1 or len(re.findall(r"\{[^}]+\}", tekst)) > 1:
        uwagi.append("Komentarz zza kamery wiecej niz raz - model moze dorobic napisy.")
    t = " " + re.sub(r"[^a-z0-9 -]+", " ", _bez_ogonkow(tekst)) + " "
    ryzykowne = [s for s in fabryka.SLOWA_RYZYKOWNE if f" {s} " in t or f" {s}s " in t]
    if ryzykowne:
        uwagi.append(f"Slowa, ktore filtr NSFW lubi blokowac: {', '.join(ryzykowne)}.")
    marki = [mk for mk in MARKI if re.search(r"(?<![a-z])" + re.escape(mk), t)]
    if marki:
        uwagi.append(f"Nazwy marek/postaci ({', '.join(marki)}) - filtr IP moze odrzucic rolke (kredyty wracaja). "
                     f"Lepiej opisac wyglad bez nazwy.")
    return bledy, uwagi


# ---------------- katalog dla panelu ----------------

def katalog(slug=None):
    """Wszystko do formularza 'Z promptu' (bez zapytan do dostawcow)."""
    kat = {
        "modele": [{"id": k, "nazwa": v["nazwa"], "opis": v["opis"], "dlugosci": list(v["dlugosci"]),
                    "rozdzielczosci": list(v["rozdzielczosci"]), "max_obrazow": v["max_obrazow"]} for k, v in MODELE.items()],
        "model_domyslny": MODEL_DOMYSLNY, "dlugosc_domyslna": DLUGOSC_DOMYSLNA, "prog_1080p_s": PROG_1080P_S,
        "pomysly": [{"id": p["id"], "pl": p["pl"], "miejsce": p["miejsce"]} for p in POMYSLY],
        "miejsca": [{"id": k, "nazwa": v["nazwa"], "kat": v["kat"]} for k, v in MIEJSCA.items()],
        "kategorie": KATEGORIE,
        "wlosy": {"kolory": [[k, v[0]] for k, v in WLOSY_KOLORY.items()],
                  "fryzury": [[k, v[0]] for k, v in WLOSY_FRYZURY.items()],
                  "grzywki": [[k, v[0]] for k, v in WLOSY_GRZYWKI.items()]},
        "stroje": [[k, v] for k, v in STROJE_TRYBY.items()],
        "stroje_odwazne": [[k, v[0], list(v[2])] for k, v in STROJE_ODWAZNE.items()],
        "reakcje": [[k, v[0]] for k, v in REAKCJE.items()],
        "reakcje_zdziwienie": list(REAKCJE_ZDZIWIENIE),
        "linie_reakcji": LINIE_REAKCJI,
        "komentarze": KOMENTARZE,
        "kamery": [[k, v[0]] for k, v in KAMERY.items()],
        "kamery_ukryte": list(KAMERY_UKRYTE),
        "glosy": [[k, v] for k, v in GLOSY.items()],
        "wymowy": [[k, v] for k, v in WYMOWY.items()],
        "nazwy": [[k, v] for k, v in NAZWY_TRYBY.items()],
        "obiekty": {mid: [[k, v[0]] for k, v in obiekty_miejsca(mid).items()] for mid in OBIEKTY_MIEJSC},
        "sezony": [[k, v["nazwa"]] for k, v in SEZONY.items()], "sezon_teraz": sezon_z_daty(),
        "pory": [[k, v[0]] for k, v in PORY_DNIA.items()],
    }
    if slug:
        prof = baza.profil_modelki(slug)
        kat["persona"] = {"slug": slug, "imie": prof.get("nazwa") or slug, "wzrost_cm": prof.get("wzrost_cm") or "",
                          "wlosy": wlosy_wlasne(slug), "zdjec": len(baza.sciezki_referencji(slug)),
                          "stroje": [n for n in sorted(os.listdir(baza.folder_strojow(slug)))
                                     if n.lower().endswith(baza.ROZSZERZENIA_OBRAZU)]}
    return kat
