'use strict';
/* rolki-ai – panel (static/app.js). Czysty JS (ES2020), bez bibliotek i zasobów z sieci.
   Układ pliku:
     1. narzędzia (esc, formatowanie, ikony)
     2. słownik prostych słów (statusy, błędy, wyniki zadań, postęp)
     3. API (fetch + obsługa {"ok": false}) i toasty
     4. stan aplikacji, tryb prosty / pełny
     5. nawigacja (#hash, #ustawienia/<sekcja>)
     6. pasek górny, odznaki, konsola „Co się dzieje” (+ czekanie na koniec zadania)
     7. strony: start, rolki, zdjęcia, lipsync, ustawienia (konta, persona, prompty, …), historia
     8. dialogi, upload (drag & drop), akcje w tle, łańcuch „Zrób rolki”
     9. zdarzenia (delegacja) i start
   Zasada: każdy tekst z serwera lub od użytkownika przechodzi przez esc() zanim trafi do innerHTML.
   Tryb prosty ukrywa [data-zaawansowane] (CSS), tryb pełny (body.tryb-pelny) ukrywa [data-tylko-prosty]. */

// ============================================================ 1. NARZĘDZIA
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const STRONY = ['start', 'rolki', 'z-promptu', 'zdjecia', 'lipsync', 'ustawienia', 'historia', 'pomoc'];
const STARE_STRONY = { pulpit: 'start', kolejka: 'rolki', persona: 'ustawienia/persona', konta: 'ustawienia/konta', teksty: 'ustawienia/teksty', dziennik: 'historia' };
const STATUSY = ['nowy', 'w_toku', 'wygenerowany', 'postprodukcja', 'gotowe', 'blad'];
const FILTRY_ROLEK = [
  { id: 'wszystkie', nazwa: 'wszystkie', statusy: null },
  { id: 'nowy', nazwa: 'czekają', statusy: ['nowy'] },
  { id: 'w_trakcie', nazwa: 'w trakcie', statusy: ['w_toku', 'wygenerowany', 'postprodukcja'] },
  { id: 'gotowe', nazwa: 'gotowe', statusy: ['gotowe'] },
  { id: 'blad', nazwa: 'nie wyszły', statusy: ['blad'] },
];
const STATUS_NA_FILTR = { nowy: 'nowy', w_toku: 'w_trakcie', wygenerowany: 'w_trakcie', postprodukcja: 'w_trakcie', gotowe: 'gotowe', blad: 'blad' };
const AKCEPT = { zrodlo: 'video/*,.mp4,.mov,.m4v,.webm', referencja: 'image/*', stroj: 'image/*', audio: 'audio/*,.mp3,.wav,.m4a,.aac,.ogg' };
const STRONY_PO_ZADANIU = ['start', 'rolki', 'z-promptu', 'zdjecia', 'lipsync', 'historia', 'ustawienia'];
const MODELE_SYNC_ZAPAS = ['lipsync-2', 'lipsync-2-pro', 'sync-3'];
const KLUCZ_TRYBU = 'rolki.tryb';
const KLUCZ_STATY = 'rolki.staty.';   // + 'start' | 'historia' -> '1' (rozwinięte) / '0' (zwinięte)
const DNI_TYGODNIA = ['nd', 'pn', 'wt', 'śr', 'cz', 'pt', 'sb'];
const KOSZT_PODGLADU = 21;             // Seedance draft, ~21 kr (CLAUDE.md)

const ESC_MAPA = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ESC_MAPA[c]);
}
function liczba(n) {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('pl-PL');
}
function odmiana(n, poj, kilka, wiele) {
  n = Math.abs(Number(n) || 0);
  if (n === 1) return poj;
  const r10 = n % 10, r100 = n % 100;
  if (r10 >= 2 && r10 <= 4 && !(r100 >= 12 && r100 <= 14)) return kilka;
  return wiele;
}
function kredytow(n) {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '? kredytów';
  const v = Number(n);
  return `${liczba(v)} ${odmiana(v, 'kredyt', 'kredyty', 'kredytów')}`;
}
// Kwoty dostawców: kredyty (Higgsfield, yapper) albo centy USD (WaveSpeed, sync.so) – centy pokazujemy jako dolary „$2,60”.
const JEDNOSTKI_DOSTAWCOW = { wavespeed: 'c', sync: 'c' };
function jednostkaDostawcy(d) { return JEDNOSTKI_DOSTAWCOW[d] || 'kr'; }
function usd(centy) {
  if (centy === null || centy === undefined || centy === '' || Number.isNaN(Number(centy))) return '$?';
  return '$' + (Number(centy) / 100).toFixed(2).replace('.', ',');
}
function kwota(n, jednostka) { return jednostka === 'c' ? usd(n) : kredytow(n); }
function kwotaKrotko(n, jednostka) { return jednostka === 'c' ? usd(n) : `${liczba(n)} kr`; }
const MODELE_WAVESPEED = {
  'bytedance/seedance-2.5/video-edit-turbo': 'Seedance 2.5 Turbo', 'bytedance/seedance-2.5/video-edit': 'Seedance 2.5 Edit',
  'alibaba/wan-3.0/reference-to-video': 'Wan 3.0', 'alibaba/wan-3.0-prime/reference-to-video': 'Wan 3.0 Prime',
};
// „rolki robi …” – dostawca i model persony po ludzku
function opisDostawcy(u) {
  const d = (u && u.dostawca) || 'higgsfield';
  if (d === 'yapper') return 'yapper.so (Wan 3.0)';
  if (d === 'wavespeed') return `WaveSpeed (${MODELE_WAVESPEED[((u.wavespeed || {}).model) || 'bytedance/seedance-2.5/video-edit-turbo'] || (u.wavespeed || {}).model})`;
  return 'Higgsfield (Seedance 2.5)';
}
function nazwaPliku(s) { return s ? String(s).split(/[\\/]/).pop() : ''; }
// „…\ROLKI AI\tu wrzucasz rolki\Noemi” – ostatnie n członów ścieżki (pełna ścieżka idzie do title)
function krotkaSciezka(s, n = 3) {
  s = String(s || '');
  const sep = s.includes('\\') ? '\\' : '/';
  const cz = s.split(/[\\/]/).filter(Boolean);
  return cz.length > n ? '…' + sep + cz.slice(-n).join(sep) : s;
}
function bezRozszerzenia(s) { return String(s || '').replace(/\.[^.]+$/, ''); }
function skroc(t, n = 160) { t = String(t || ''); return t.length > n ? t.slice(0, n - 1) + '…' : t; }
function dwaZnaki(n) { return String(n).padStart(2, '0'); }
function data(iso) {
  if (iso === null || iso === undefined || iso === '') return null;
  const d = typeof iso === 'number' ? new Date(iso > 1e12 ? iso : iso * 1000) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}
function formatCzas(iso) {
  const d = data(iso);
  if (!d) return iso ? String(iso) : '';
  const hhmm = `${dwaZnaki(d.getHours())}:${dwaZnaki(d.getMinutes())}`;
  if (d.toDateString() === new Date().toDateString()) return hhmm;
  return `${dwaZnaki(d.getDate())}.${dwaZnaki(d.getMonth() + 1)} ${hhmm}`;
}
function formatData(iso) {
  const d = data(iso);
  if (!d) return iso ? String(iso) : '';
  return `${dwaZnaki(d.getDate())}.${dwaZnaki(d.getMonth() + 1)}.${d.getFullYear()} ${dwaZnaki(d.getHours())}:${dwaZnaki(d.getMinutes())}:${dwaZnaki(d.getSeconds())}`;
}
function odstepSlownie(sek) {
  sek = Math.max(0, Math.floor(sek));
  const h = Math.floor(sek / 3600), m = Math.floor((sek % 3600) / 60), s = sek % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${s} s`;
  return `${s} s`;
}
function sekundOd(ts) { const d = data(ts); return d ? (Date.now() - d.getTime()) / 1000 : 0; }
function minutDo(ts) { const d = data(ts); return d ? Math.ceil((d.getTime() - Date.now()) / 60000) : null; }
function tekstWyniku(w) {
  if (w === null || w === undefined || w === '') return '';
  if (typeof w !== 'object') return String(w);
  if (Array.isArray(w)) return w.map(tekstWyniku).join(', ');
  return Object.entries(w).map(([k, v]) => `${k}: ${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`).join(', ');
}
function wartoscZ(obj, sciezka) {
  return sciezka.split('.').reduce((o, k) => (o === null || o === undefined ? undefined : o[k]), obj);
}
function ustawW(obj, sciezka, v) {
  const czesci = sciezka.split('.');
  let o = obj;
  for (let i = 0; i < czesci.length - 1; i++) {
    if (typeof o[czesci[i]] !== 'object' || o[czesci[i]] === null) o[czesci[i]] = {};
    o = o[czesci[i]];
  }
  o[czesci[czesci.length - 1]] = v;
}
function linkuj(tekst) {
  return esc(tekst).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
}

// Ikony liniowe (24x24, stroke = currentColor).
const IKONY = {
  start: '<path d="M3 11 12 3l9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  zdjecia: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 16-5-5-8 8"/>',
  lipsync: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>',
  ustawienia: '<path d="M4 6h8M16 6h4M4 12h2M10 12h10M4 18h10M18 18h2"/><circle cx="14" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
  historia: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  odswiez: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4h-4"/>',
  kopiuj: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  kosz: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  chevron: '<path d="m6 15 6-6 6 6"/>',
  'chevron-dol': '<path d="m6 9 6 6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  uwaga: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  zamknij: '<path d="M6 6l12 12M18 6 6 18"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
  ok: '<path d="m5 12 5 5L20 7"/>',
  folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6z"/>',
  persona: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  klucz: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l2 2M14 9l2 2"/>',
  tarcza: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z"/><path d="m9 12 2 2 4-4"/>',
  teksty: '<path d="M4 6h16M4 12h10M4 18h14"/>',
  podpis: '<path d="M4 20h16"/><path d="m5 16 10-10 3 3-10 10H5v-3z"/>',
  telefon: '<rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/>',
  pomoc: '<circle cx="12" cy="12" r="9"/><path d="M9.3 9.6a2.7 2.7 0 1 1 3.9 2.4c-.8.4-1.2 1-1.2 1.8"/><path d="M12 17h.01"/>',
  zasilanie: '<path d="M12 3v9"/><path d="M6.6 6.6a8 8 0 1 0 10.8 0"/>',
  ksiezyc: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  filtr: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  stroj: '<path d="M9 4 6 6 3 11l3 1.5V20h12v-7.5L21 11l-3-5-3-2a3 3 0 0 1-6 0z"/>',
  metka: '<path d="M3 12 12 3h8v8l-9 9z"/><circle cx="16" cy="8" r="1.5"/>',
  pioro: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m13.5 6.5 4 4"/>',
};
function ikona(nazwa) {
  const p = IKONY[nazwa];
  return p ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>` : '';
}
function wstawIkony(root = document) {
  $$('.ikona[data-ikona]', root).forEach(el => { if (!el.firstChild) el.innerHTML = ikona(el.dataset.ikona); });
}

// ============================================================ 2. SŁOWNIK PROSTYCH SŁÓW
// Statusy rolek / zdjęć / lipsyncu – jedno proste słowo zamiast nazwy technicznej.
const SLOWA_STATUSU = {
  rolka: { nowy: 'czeka', w_toku: 'generuje się', wygenerowany: 'zrobiona (jeszcze nie wyprana)', postprodukcja: 'w obróbce', gotowe: 'gotowa', blad: 'nie wyszło', pobieranie: 'pobieram' },
  zdjecie: { nowy: 'czeka', wygenerowany: 'zrobione', postprodukcja: 'w obróbce', gotowe: 'gotowe', blad: 'nie wyszło' },
  lipsync: { nowy: 'w trakcie', wygenerowany: 'zrobiony', postprodukcja: 'w obróbce', gotowe: 'gotowy', blad: 'nie wyszło' },
};
function slowoStatusu(status, rodzaj = 'rolka') {
  const m = SLOWA_STATUSU[rodzaj] || SLOWA_STATUSU.rolka;
  return m[status] || SLOWA_STATUSU.rolka[status] || status || '';
}
function kolorStatusu(status) {
  return { nowy: 'akcent', w_toku: 'uwaga', wygenerowany: 'uwaga', postprodukcja: 'uwaga', gotowe: 'ok', blad: 'zle', pobieranie: 'uwaga' }[status] || '';
}

// Błędy: fragment tekstu technicznego -> jedno zdanie po ludzku (kolejność ma znaczenie).
const SLOWNIK_BLEDOW = [
  [/nie znaleziono cli/i, 'Program Higgsfield nie jest zainstalowany. Kliknij dwa razy instaluj.bat.'],
  [/nie jest zalogowane|auth login|not authenticated|session expired/i, 'Zaloguj się do Higgsfield: kliknij dwa razy zaloguj-higgsfield.bat.'],
  [/no workspace|wybranego workspace|workspace set/i, 'Higgsfield: wybierz workspace (zaloguj-higgsfield.bat).'],
  [/hamulec|pauz[aąęy]/i, 'Autopilot jest zatrzymany — kliknij Wznów na stronie Start.'],
  [/telegram nie jest sparowany|brak sparowanego czatu|nie jest sparowany/i, 'Najpierw napisz /start do bota na telefonie.'],
  [/ponad 20 ?MB|plik za du[zż]y dla telegrama/i, 'Plik za duży dla Telegrama (max 20 MB).'],
  [/brak tokena bota/i, 'Podłącz telefon: wklej token bota w Ustawienia → Konta.'],
  [/dzienny limit WaveSpeed nie jest ustawiony|brak limitu dziennego wavespeed/i, 'Ustaw dzienny limit WaveSpeed (Ustawienia → Limity, tryb pełny) – bez niego fabryka nic tam nie wyda.'],
  [/WaveSpeed: za malo pieniedzy|insufficient.credits/i, 'Za mało pieniędzy na koncie WaveSpeed – doładuj je (wavespeed.ai → Billing).'],
  [/WaveSpeed odrzucil tresc|moderacja WaveSpeed/i, 'Odrzucone przez moderację WaveSpeed (NSFW) – filtr nie patrzy na kontekst.'],
  [/min_kredyty/i, 'Za mało kredytów na koncie, żeby bezpiecznik pozwolił.'],
  [/limit dzienny/i, 'Dzisiejszy limit kredytów wyczerpany.'],
  [/max\/rolka/i, 'Ta rolka kosztowałaby więcej niż dozwolone na jedną rolkę.'],
  [/nsfw/i, 'Odrzucone przez filtr treści (NSFW) – kredyty wróciły.'],
  [/ip_detected/i, 'Model wykrył znaną postać albo markę (znak towarowy / prawa autorskie).'],
  [/tylko na windows/i, 'Otwieranie folderu działa tylko na Windows – skopiuj ścieżkę i wklej ją w Eksploratorze.'],
  [/brak klucza/i, 'Brak klucza — wpisz go w Ustawienia → Konta.'],
  [/brak referencji|brak zdjec persony|brak zdjęć persony/i, 'Dodaj zdjęcia persony w Ustawieniach.'],
  [/mode_bez_zrodla/i, 'Ten pomysł nie ma filmiku. Włącz tryb „bez filmiku” w Ustawieniach (zaawansowane) albo wrzuć filmik.'],
  [/cos juz trwa|coś już trwa|\b409\b/i, 'Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.'],
  [/media tool/i, 'Media Tool nie zadziałał — rolka została bez prania.'],
  [/koszt nieznany/i, 'Nie udało się policzyć kosztu.'],
  [/\b402\b/, 'Ten serwis wymaga opłaconego planu.'],
  [/\b401\b/, 'Zły klucz — sprawdź w Ustawienia → Konta.'],
  [/zatrzymane|przerwano|\[stop\]/i, 'Zatrzymano.'],
  [/brak po[lł][aą]czenia/i, 'Panel nie odpowiada — sprawdź, czy okno panel.bat jest otwarte.'],
];
function prostyBlad(tekst) {
  if (tekst === null || tekst === undefined) return '';
  let t = typeof tekst === 'string' ? tekst : (tekst && tekst.message ? tekst.message : String(tekst));
  for (const [re, zdanie] of SLOWNIK_BLEDOW) if (re.test(t)) return zdanie;
  // "ValueError: ..." / "SystemExit: ..." – sama nazwa wyjątku nic użytkownikowi nie mówi
  t = t.replace(/^[A-Z][A-Za-z]*(Error|Exception|Exit|Blad|Interrupt|Warning|Klucza|Zalogowany|CLI|Przerwano|Zajete): /, '').trim();
  return skroc(t, 160);
}

// Zadania w tle: nazwy i proste podsumowania wyników.
const CO_ROBIE = { wznow: 'kończę rolki przerwane zamknięciem', skanuj: 'sprawdzam nowe filmiki', koszt: 'liczę koszt', generuj: 'rolki', pierz: 'pranie w Media Tool', lipsync: 'dopasowuję usta', zdjecia: 'zdjęcia', podpis: 'podpis', tts: 'głos z tekstu', autopilot_raz: 'przebieg autopilota', autopilot: 'autopilot', telegram_wyslij: 'wysyłam na telefon', podglad: 'tani podgląd' };
const NAZWY_AKCJI = { wznow: 'Dokończenie przerwanych rolek', skanuj: 'Sprawdzenie filmików', koszt: 'Liczenie kosztu', generuj: 'Robienie rolek', pierz: 'Pranie w Media Tool', lipsync: 'Dopasowanie ust', zdjecia: 'Zdjęcia', podpis: 'Podpis', tts: 'Głos z tekstu', autopilot_raz: 'Przebieg autopilota', autopilot: 'Autopilot', telegram_wyslij: 'Wysłanie na telefon', podglad: 'Tani podgląd' };
const ETAPY_AUTOPILOTA = { skanuj: 'sprawdza filmiki', generuj: 'robi rolki', podpisy: 'dobiera podpisy', zdjecia: 'robi zdjęcia' };

function prostyWynik(typ, w) {
  const n = x => (Array.isArray(x) ? x.length : (Number(x) || 0));
  if (w === null || w === undefined || w === '') return '';
  if (typeof w === 'string') {
    if (typ === 'pierz') return `wyprane: ${nazwaPliku(w)}`;
    if (typ === 'lipsync') return `usta dopasowane: ${nazwaPliku(w)}`;
    if (typ === 'tts') return `nagranie gotowe: ${nazwaPliku(w)}`;
    if (typ === 'podglad') return `podgląd gotowy: ${nazwaPliku(w)}`;
    return skroc(w, 120);
  }
  if (typeof w !== 'object') return String(w);
  switch (typ) {
    case 'skanuj': {
      const k = n(w.nowe);
      if (!k) return 'nic nowego w folderze';
      return `${k} ${odmiana(k, 'nowy filmik', 'nowe filmiki', 'nowych filmików')} ${odmiana(k, 'czeka', 'czekają', 'czeka')} na zrobienie` + (n(w.bez_promptu) ? `, ${n(w.bez_promptu)} bez promptu` : '');
    }
    case 'koszt': {
      const poz = Array.isArray(w.pozycje) ? w.pozycje : [];
      if (!poz.length) return 'nie ma czego liczyć';
      const nieznane = poz.filter(p => !p || p[1] === null || p[1] === undefined).length;
      return `około ${kwota(w.razem, jednostkaDostawcy(w.dostawca))} za ${poz.length} ${odmiana(poz.length, 'rolkę', 'rolki', 'rolek')}` + (nieznane ? ` (${nieznane} bez policzonego kosztu)` : '');
    }
    case 'generuj': {
      const z = Number(w.wygenerowane) || 0;
      const cz = [`${z} ${odmiana(z, 'rolka zrobiona', 'rolki zrobione', 'rolek zrobionych')}`];
      if (n(w.bledy)) cz.push(`nie wyszło: ${n(w.bledy)}`);
      if (n(w.pominiete)) cz.push(`pominięte: ${n(w.pominiete)}`);
      if (w.stop) cz.push(prostyBlad(w.stop));
      return cz.join(', ');
    }
    case 'zdjecia': {
      const z = Number(w.zrobione) || 0;
      return `${z} ${odmiana(z, 'zdjęcie', 'zdjęcia', 'zdjęć')}` + (w.stop ? `, ${prostyBlad(w.stop)}` : '');
    }
    case 'podpis': return w.tekst ? `podpis: „${skroc(w.tekst, 80)}”` : 'bank podpisów jest pusty albo wszystko użyte';
    case 'podglad': return w.plik ? `podgląd gotowy: ${nazwaPliku(w.plik)} – zobacz go w Rolkach` : 'podgląd gotowy – zobacz go w Rolkach';
    case 'dograj_glos': return w.plik ? `komentarz dograny: ${nazwaPliku(w.plik)}` : 'komentarz dograny';
    case 'lipsync': return w.url || w.plik ? 'usta dopasowane' : (w.status ? `status: ${w.status}` : 'gotowe');
    case 'telegram_wyslij': return w.wyslano !== undefined && w.wyslano !== null ? `rolka #${Number(w.wyslano)} poleciała na telefon` : 'wysłane na telefon';
    case 'autopilot_raz':
    case 'autopilot': {
      const lista = Array.isArray(w) ? w : [w];
      return lista.map(p => `${p.modelka ? p.modelka + ': ' : ''}nowe ${p.nowe || 0}, zrobione ${p.wygenerowane || 0}` + (n(p.bledy) ? `, problemy: ${n(p.bledy)}` : '')).join('; ') || 'nic do zrobienia';
    }
    default: return '';
  }
}

// Co teraz robi fabryka – zdanie z logu zadania (np. „Robię rolkę 2 z 3…”).
function postepZadania(z, linie) {
  const typ = (z && z.typ) || '';
  const a = state.autopilot || {};
  if (typ === 'generuj' || (typ === 'autopilot' && a.etap === 'generuj') || typ === 'autopilot_raz') {
    const starty = linie.filter(l => /#\d+: start \(/.test(l));
    if (typ === 'generuj' && !starty.length) return 'Sprawdzam saldo i liczę koszty…';
    if (starty.length) {
      const ids = []; starty.forEach(l => { const m = l.match(/#(\d+)/); if (m && !ids.includes(m[1])) ids.push(m[1]); });
      const razem = state.lancuch.ids ? state.lancuch.ids.length : null;
      const ostatnia = linie[linie.length - 1] || '';
      let dodatek = '';
      if (/media tool|pior|pranie/i.test(ostatnia)) dodatek = ' – piorę w Media Tool';
      else if (/lipsync/i.test(ostatnia)) dodatek = ' – dopasowuję usta';
      return `Robię rolkę ${ids.length}${razem ? ` z ${razem}` : ''} (#${ids[ids.length - 1]})${dodatek}… zwykle 2–4 min każda`;
    }
  }
  if (typ === 'autopilot' || typ === 'autopilot_raz') return `Autopilot ${ETAPY_AUTOPILOTA[a.etap] || 'pracuje'}${a.modelka ? ` (${a.modelka})` : ''}…`;
  return {
    skanuj: 'Sprawdzam nowe filmiki…', koszt: 'Liczę koszt…', pierz: 'Piorę rolkę w Media Tool…',
    lipsync: 'Dopasowuję usta do głosu… to może potrwać kilka minut', zdjecia: 'Robię zdjęcia…',
    podpis: 'Dobieram podpis…', tts: 'Robię głos z tekstu…', telegram_wyslij: 'Wysyłam rolkę na telefon…',
    podglad: 'Robię tani podgląd… zwykle 1–2 min',
  }[typ] || 'Pracuję…';
}

// Wpis dziennika -> proste zdanie (tryb prosty).
function prostyTekstWpisu(w) {
  const t = String((w && w.tekst) || '');
  let m;
  if ((m = t.match(/^#(\d+): GOTOWE -> (.+)$/))) return `Rolka #${m[1]} gotowa: ${nazwaPliku(m[2])}`;
  if ((m = t.match(/^#(\d+): WYGENEROWANE \((\d+) kr/))) return `Rolka #${m[1]} zrobiona (${kredytow(m[2])})`;
  if ((m = t.match(/^#(\d+): (?:NSFW -> zapas \S+: )?WYGENEROWANE \(\$(\d+)\.(\d\d)/))) return `Rolka #${m[1]} zrobiona ($${m[2]},${m[3]} WaveSpeed)`;
  if ((m = t.match(/^#(\d+): \$(\d+)\.(\d\d) \(/)) && w.typ === 'kredyty') return `Rolka #${m[1]}: wydano $${m[2]},${m[3]} (WaveSpeed)`;
  if ((m = t.match(/^#(\d+): start \(/))) return `Zaczynam rolkę #${m[1]}`;
  if ((m = t.match(/^#(\d+): BLAD po/i))) return `Rolka #${m[1]} nie wyszła`;
  if ((m = t.match(/^#(\d+): tani podglad \(draft, ~(\d+) kr\)/i))) return `Rolka #${m[1]}: robię tani podgląd (~${kredytow(m[2])})`;
  if ((m = t.match(/^#(\d+): podglad gotowy \((\d+) kr\) -> (.+)$/i))) return `Rolka #${m[1]}: tani podgląd gotowy (${kredytow(m[2])}) – ${nazwaPliku(m[3])}`;
  if ((m = t.match(/^#(\d+): (\d+) kr \(/)) && w.typ === 'kredyty') return `Rolka #${m[1]}: wydano ${kredytow(m[2])}`;
  if ((m = t.match(/^#(\d+): (.*)$/))) return `Rolka #${m[1]}: ${prostyBlad(m[2])}`;
  if ((m = t.match(/^#(\d+)\s+(\S.*?\.(?:mp4|mov|m4v|webm|avi|mkv))\b/i))) return `Nowy filmik #${m[1]}: ${m[2]}`;
  // hamulec i telefon (Telegram)
  if ((m = t.match(/^HAMULEC: autopilot (\S+) zatrzymany - (.*?)\.? Sprawdz w panelu/i))) return `Autopilot (${m[1]}) zatrzymał się: ${m[2]}. Kliknij Wznów na Starcie.`;
  if ((m = t.match(/^autopilot (\S+): wznowiony z panelu/))) return `Autopilot (${m[1]}) wznowiony.`;
  if (/^autopilot zatrzymany z telefonu/.test(t)) return 'Autopilot zatrzymany z telefonu (/stop).';
  if (/^autopilot wznowiony z telefonu/.test(t)) return 'Autopilot wznowiony z telefonu (/wznow).';
  if ((m = t.match(/^z telefonu: glos (.*)$/))) return `Z telefonu przyszło nagranie głosu: ${m[1]}`;
  if ((m = t.match(/^z telefonu: (.*?) -> wrzutnia (\S+)/))) return `Z telefonu przyszedł filmik ${m[1]} (do ${m[2]})`;
  if ((m = t.match(/^telegram: nie wyslalem rolki #(\d+) \((.*)\)$/))) return `Nie udało się wysłać rolki #${m[1]} na telefon: ${prostyBlad(m[2])}`;
  if ((m = t.match(/^telegram: nie wyslalem wiadomosci \((.*)\)$/))) return `Nie udało się wysłać wiadomości na telefon: ${prostyBlad(m[1])}`;
  if ((m = t.match(/^telegram: (.*)$/))) return `Telefon (Telegram): ${prostyBlad(m[1])}`;
  if (/^autopilot wlaczony/.test(t)) return 'Autopilot włączony';
  if (/^autopilot wylaczony/.test(t)) return 'Autopilot wyłączony';
  if ((m = t.match(/^autopilot dla (\S+): (wlaczony|wylaczony)/))) return `Autopilot dla ${m[1]}: ${m[2] === 'wlaczony' ? 'włączony' : 'wyłączony'}`;
  if ((m = t.match(/^autopilot generuj: (.*)$/))) return `Autopilot nie zrobił rolek: ${prostyBlad(m[1])}`;
  if ((m = t.match(/^autopilot (\S+): (.*)$/))) return `Autopilot (${m[1]}): ${m[2].replace('wygenerowane', 'zrobione').replace('bledy', 'problemy').replace('zdjecia', 'zdjęcia')}`;
  if ((m = t.match(/^autopilot: (.*)$/))) return `Autopilot: ${prostyBlad(m[1])}`;
  if ((m = t.match(/^nowe referencje: (.*)$/))) return `Dodano zdjęcia persony: ${m[1]}`;
  if ((m = t.match(/^nowa modelka: (.*)$/))) return `Nowa persona: ${m[1]}`;
  if ((m = t.match(/^limit dzienny (\S+): (.*)$/))) return `Zmieniono dzienny limit (${m[1]}): ${m[2]}`;
  if (/^\[BLAD\] saldo/.test(t)) return `Nie udało się sprawdzić kredytów: ${prostyBlad(t)}`;
  return w && w.typ === 'blad' ? prostyBlad(t) : skroc(t, 160);
}

// ============================================================ 3. API I TOASTY
class BladApi extends Error {
  constructor(msg, status) { super(msg); this.name = 'BladApi'; this.status = status; }
}

async function api(url, metoda = 'GET', dane = null) {
  const opcje = { method: metoda, headers: {} };
  if (dane instanceof FormData) opcje.body = dane;
  else if (dane !== null && dane !== undefined) {
    opcje.headers['Content-Type'] = 'application/json';
    opcje.body = JSON.stringify(dane);
  }
  let odp;
  try { odp = await fetch(url, opcje); }
  catch (e) { throw new BladApi('Brak połączenia z panelem – sprawdź, czy okno panel.bat jest otwarte.', 0); }
  let json = null;
  try { json = await odp.json(); } catch (e) { json = null; }
  if (odp.status === 409) throw new BladApi((json && json.blad) || 'Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 409);
  if (!json || typeof json !== 'object') throw new BladApi(`Błąd serwera (HTTP ${odp.status})`, odp.status);
  if (json.ok === false) throw new BladApi(json.blad || `Nieznany błąd (HTTP ${odp.status})`, odp.status);
  return json;
}

function toast(tekst, typ = 'ok', opcje = {}) {
  const el = document.createElement('div');
  el.className = `toast ${typ}`;
  el.innerHTML = `<span class="kropka ${esc(typ)}"></span><span class="toast-tekst">${esc(tekst)}</span>`;
  let timer = null;
  const usun = () => { clearTimeout(timer); el.classList.add('znika'); setTimeout(() => el.remove(), 300); };
  if (opcje.akcja) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-maly btn-glowny'; b.textContent = opcje.akcja;
    b.addEventListener('click', () => { usun(); if (opcje.cb) opcje.cb(); });
    el.appendChild(b);
  }
  const z = document.createElement('button');
  z.type = 'button'; z.className = 'toast-zamknij'; z.innerHTML = ikona('zamknij'); z.setAttribute('aria-label', 'Zamknij');
  z.addEventListener('click', usun);
  el.appendChild(z);
  $('#toasty').appendChild(el);
  timer = setTimeout(usun, typ === 'blad' ? 10000 : (opcje.akcja ? 12000 : 4500));
}
// Błąd -> proste zdanie; w trybie pełnym dopisujemy też surowy tekst.
function bladToast(e) {
  const surowy = e && e.message ? e.message : String(e);
  const prosty = prostyBlad(surowy);
  toast(state.pelny && prosty !== surowy ? `${prosty} (${skroc(surowy, 200)})` : prosty, 'blad');
}

// ============================================================ 4. STAN I TRYB
const state = {
  stan: null,            // /api/stan -> "stan" (null = brak aktywnej persony)
  modelki: [], aktywna: null, saldo: {}, autopilot: {}, zadanie: {}, konta: {}, dziennikOstatni: null, wersja: '',
  autopilotStan: {},     // hamulec aktywnej persony: {bledy_z_rzedu, pauza, pauza_od}
  telegram: {},          // bot Telegram: {skonfigurowany, sparowany, czat, czaty: [{nazwa, glowny}]}
  dzis: null,            // podsumowanie dnia: {rolki, zdjecia, bledy, kredyty{...}, rolek_zostalo}
  jakosc: null,          // /api/stan.jakosc: {preset, resolution, max_sekund_rolki, koszt_rolki, koszt_sekundy, za_drogo, max_kredyty_na_rolke, presety}
  foldery: null, pulpit: '',   // foldery aktywnej persony na pulpicie {wrzutnia, gotowe, zdjecia} + folder ROLKI AI
  stroje: [],            // zdjęcia strojów persony (z /api/ustawienia) – wybór stroju na stronie Zdjęcia
  nsfw: null,            // /api/nsfw aktywnej persony (Pomoc → Filtr NSFW)
  zamkniety: false,      // panel zamknięty z panelu („Zamknij program”)
  strona: 'start', sekcja: null,
  diagnoza: [], diagnozaCzas: 0, diagnozaStan: 'czekam', pkOtwarte: null, pkKlucz: '',   // „Pierwsze kroki” (/api/diagnoza); pkOtwarte: null = automatycznie
  statystyki: null, statystykiCzas: 0,                            // /api/statystyki?dni=14 (Start + Historia)
  profile: {},           // slug -> profil zapisany w tej sesji (API nie ma GET profilu)
  personyHtml: '',
  // rolki
  pomysly: [], statusy: STATUSY.slice(), pomyslyJson: '', filtr: 'wszystkie',
  odbierzTelefon: false, rolkiTelefon: false,   // czy listy były rysowane z podłączonym telefonem (przycisk „Wyślij na telefon”)
  kosztJakosc: {},       // id rolki -> podpis jakości (rozdzielczość|długość) z chwili policzenia kosztu w tej sesji; inny podpis = koszt nieaktualny
  rolkiJakosc: '',       // podpis jakości, z którym rysowano listę rolek (zmiana zestawu przerysowuje szacunki „ok. N kr”)
  bledyOdswiezania: 0,   // kolejne nieudane odpytania /api/stan w tle – toast dopiero po kilku z rzędu (jednorazowy błąd nie alarmuje)
  otwartePrompty: new Set(), odtwarzane: new Set(), podglady: new Set(),   // podglady = rolki z otwartym filmem taniego podglądu
  // reszta stron
  zdjecia: [], lipsync: [], ustawieniaPelne: null, budzet: null, kontaPelne: null, testyKont: {},
  teksty: [], szablony: [], dziennik: [], historiaFiltr: 'wszystko',
  listy: {},             // cache list modeli/głosów: zapytanie -> {czas, pozycje, blad}
  konsola: { otwarta: false, logOd: 0, start: null, trwalo: false, timer: null, sprawdzanie: false, linie: [], oczekujacy: [] },
  lancuch: { trwa: false, etap: '', ids: null, stop: false, wynik: null },   // „Zrób rolki”: skanuj -> koszt -> pytanie -> generuj
  timery: { dziennik: null },
  uploadTyp: null,
  odswiezanie: false,
  pelny: false,
};

function wyczyscCachePersony() {
  state.pomysly = []; state.pomyslyJson = ''; state.otwartePrompty.clear(); state.odtwarzane.clear(); state.podglady.clear();
  state.zdjecia = []; state.lipsync = []; state.ustawieniaPelne = null; state.teksty = []; state.szablony = [];
  state.stroje = []; state.nsfw = null;
  state.kosztJakosc = {}; state.rolkiJakosc = '';
  state.lancuch.wynik = null;
}

function wczytajTryb() {
  let t = 'prosty';
  try { t = localStorage.getItem(KLUCZ_TRYBU) || 'prosty'; } catch (e) { /* prywatne okno */ }
  ustawTryb(t === 'pelny', false);
}

function ustawTryb(pelny, zapisz = true) {
  state.pelny = !!pelny;
  document.body.classList.toggle('tryb-pelny', state.pelny);
  const chk = $('#tryb-przelacznik');
  if (chk) chk.checked = state.pelny;
  $('#tryb-nazwa').textContent = state.pelny ? 'Tryb pełny' : 'Tryb prosty';
  $('#tryb-opis').textContent = state.pelny ? 'wszystkie ustawienia i logi' : 'tylko to, co potrzebne';
  if (zapisz) { try { localStorage.setItem(KLUCZ_TRYBU, state.pelny ? 'pelny' : 'prosty'); } catch (e) { /* nic */ } }
  renderKonsolaStan();
  zastosujDomyslneStaty();
  if (state.stan) {
    if (state.strona === 'rolki') renderRolki();
    else if (state.strona === 'historia') { renderHistoria(); if (zapisz) ladujHistoria().catch(() => {}); }
    else if (state.strona === 'start') renderStart();
    else if (state.strona === 'lipsync') renderLipsyncHistoria();
    else if (state.strona === 'zdjecia') ladujZdjecia().catch(() => {});
  }
}

// ============================================================ 5. NAWIGACJA
function zastosujHash() {
  const h = (location.hash || '').replace(/^#/, '');
  const [sciezka, q] = h.split('?');
  let [strona, sekcja] = (sciezka || '').split('/');
  if (STARE_STRONY[strona]) {
    const [s, sek] = STARE_STRONY[strona].split('/');
    strona = s; sekcja = sekcja || sek;
  }
  let st = null;
  if (q) {
    const p = new URLSearchParams(q);
    st = p.get('status');
    if (st) state.filtr = STATUS_NA_FILTR[st] || st;
  }
  // samo #rolki (link w nawigacji, „wszystkie rolki →”) pokazuje całą listę – filtr z #rolki?status=… nie jest „lepki”
  if (strona === 'rolki' && !st) state.filtr = 'wszystkie';
  state.sekcja = sekcja || null;
  pokazStrone(STRONY.includes(strona) ? strona : 'start');
}

function pokazStrone(nazwa) {
  state.strona = nazwa;
  // strona tylko z trybu pełnego (Lipsync, Historia) otwarta linkiem w trybie prostym -> włączamy tryb pełny, jak otworzSekcje() dla sekcji ustawień
  const nav = $(`.nav a[data-strona="${nazwa}"]`);
  if (nav && nav.hasAttribute('data-zaawansowane') && !state.pelny) ustawTryb(true);
  $$('.strona').forEach(s => { s.hidden = s.id !== 'strona-' + nazwa; });
  $$('.nav a').forEach(a => a.classList.toggle('aktywny', a.dataset.strona === nazwa));
  if (state.timery.dziennik) { clearInterval(state.timery.dziennik); state.timery.dziennik = null; }
  window.scrollTo({ top: 0 });
  // Pomoc leży poza #strony – działa też bez persony (ekran „dodaj personę” wtedy chowamy)
  $('#brak-persony').hidden = !!state.stan || nazwa === 'pomoc';
  if (state.stan || nazwa === 'pomoc') ladujStrone(nazwa);
  if (nazwa === 'ustawienia' && state.sekcja) otworzSekcje(state.sekcja);
  if (nazwa === 'pomoc' && state.sekcja) otworzPomoc(state.sekcja);
}

// #pomoc/<id> otwiera jedno pytanie Pomocy (np. #pomoc/nsfw z karty odrzuconej rolki)
function otworzPomoc(id) {
  const d = $('#pomoc-' + id);
  if (!d) return;
  d.open = true;
  requestAnimationFrame(() => d.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}

function otworzSekcje(id) {
  const d = $('#sekcja-' + id);
  if (!d) return;
  if (d.hasAttribute('data-zaawansowane') && !state.pelny) ustawTryb(true);
  d.open = true;
  requestAnimationFrame(() => d.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}

function ladujStrone(nazwa) {
  const mapa = {
    start: () => ladujStart(false), rolki: () => ladujRolki(false), 'z-promptu': ladujZPromptu, zdjecia: ladujZdjecia, lipsync: ladujLipsync,
    ustawienia: ladujUstawienia, historia: ladujHistoria, pomoc: renderPomoc,
  };
  const f = mapa[nazwa];
  if (f) Promise.resolve().then(f).catch(bladToast);
}

// ============================================================ 6. PASEK GÓRNY, ODZNAKI, KONSOLA
async function odswiez(wymusSaldo = false) {
  if (state.odswiezanie) return;
  state.odswiezanie = true;
  try {
    const d = await api('/api/stan' + (wymusSaldo ? '?saldo=1' : ''));
    polaczenie(true);
    state.stan = d.stan || null;
    state.modelki = (d.modelki || []).map(m => (typeof m === 'string' ? { slug: m, nazwa: m } : m));
    state.aktywna = d.aktywna || null;
    state.saldo = d.saldo || {};
    state.autopilot = d.autopilot || {};
    if (!(state.konsola.timer && state.zadanie && state.zadanie.trwa)) state.zadanie = d.zadanie || state.zadanie || {};
    state.konta = d.konta || {};
    state.autopilotStan = d.autopilot_stan || {};
    state.telegram = d.telegram || {};
    state.dzis = d.dzis || null;
    state.jakosc = d.jakosc || null;
    state.foldery = d.foldery || null;
    state.pulpit = d.pulpit || '';
    state.dziennikOstatni = d.dziennik_ostatni || null;
    state.wersja = d.wersja || '';
    renderPersonaSelect(); renderKredyty(); renderOdznaki(); renderKonsolaStan(); renderHamulecRolek();
    const wer = $('#wersja');
    const werHtml = state.wersja ? `<span class="ikona">${ikona('ksiezyc')}</span><span>Rolki AI v${esc(state.wersja)}</span>` : '';
    if (wer.innerHTML !== werHtml) wer.innerHTML = werHtml;
    const jest = !!state.stan;
    $('#brak-persony').hidden = jest || state.strona === 'pomoc';
    $('#strony').hidden = !jest;
    if (jest) {
      $('#ustawienia-tytul').textContent = 'Ustawienia: ' + (nazwaPersony(state.aktywna) || state.stan.modelka || '');
      if (state.strona === 'start') ladujStart(true).catch(() => {});
      else if (state.strona === 'rolki' || state.strona === 'z-promptu') ladujRolki(true).catch(() => {});
      else if (state.strona === 'ustawienia') renderJakosc();
    }
    if (state.zadanie && state.zadanie.trwa) startKonsoli();
    state.bledyOdswiezania = 0;
  } catch (e) {
    if (e.status === 0) polaczenie(false);
    else {
      // odpytywanie w tle (co 5 s): jednorazowy błąd (np. plik JSON w trakcie zapisu) nie alarmuje – toast dopiero po 3 z rzędu;
      // ręczne odświeżenie (wymusSaldo) mówi od razu
      state.bledyOdswiezania += 1;
      if (wymusSaldo || state.bledyOdswiezania >= 3) bladToast(e);
      else console.warn('odświeżanie stanu nie wyszło (spróbuję za chwilę):', e.message);
    }
  } finally {
    state.odswiezanie = false;
  }
}
function polaczenie(ok) {
  // po „Zamknij program” pasek u góry mówi, jak włączyć panel ponownie – nie nadpisujemy go zwykłym „nie odpowiada”
  if (state.zamkniety) { $('#offline').hidden = false; return; }
  $('#offline').hidden = ok;
}

// Lewy dolny róg: „Zamknij program” – panel może działać w tle (skrót Rolki AI bez okna konsoli), więc trzeba go móc wyłączyć stąd.
async function zamknijPanel() {
  const w = await potwierdz({
    tytul: 'Zamknąć program?',
    tresc: '<p>Panel i autopilot przestaną działać, dopóki nie uruchomisz programu ponownie – skrótem <b>Rolki AI</b> na pulpicie.</p>' + (state.zadanie && state.zadanie.trwa ? '<p class="dialog-uwaga">Coś się jeszcze robi – zamknę panel po bieżącym kroku (wysyłanie rolki nie jest przerywane). Rolka, która już się generuje, dokończy się po ponownym uruchomieniu – bez drugiej opłaty.</p>' : ''),
    ok: 'Zamknij program', klasa: 'btn-zly',
  });
  if (!w) return;
  let d = {};
  try { d = await api('/api/zamknij', 'POST', {}); }
  catch (e) { if (e.status !== 0) { bladToast(e); return; } }
  state.zamkniety = true;
  stopKonsoli();
  const off = $('#offline');
  off.innerHTML = d && d.czekam
    ? 'Panel zamknie się za chwilę – kończy bieżący krok (rolka dokończy się po ponownym uruchomieniu). Potem uruchom go skrótem <b>Rolki AI</b> na pulpicie.'
    : 'Panel zamknięty. Uruchom ponownie skrótem <b>Rolki AI</b> na pulpicie.';
  off.hidden = false;
  toast(d && d.czekam ? 'Zamknę panel po bieżącym kroku – nic nie zostanie zapłacone dwa razy.' : 'Panel zamknięty. Uruchom ponownie skrótem Rolki AI.', 'info');
  window.scrollTo({ top: 0 });
}
function nazwaPersony(slug) { const m = state.modelki.find(x => x.slug === slug); return m ? (m.nazwa || m.slug) : slug; }

function renderPersonaSelect() {
  const sel = $('#wybor-modelki');
  const html = state.modelki.length
    ? state.modelki.map(m => `<option value="${esc(m.slug)}">${esc(m.nazwa || m.slug)}${m.autopilot ? ' · autopilot' : ''}</option>`).join('')
    : '<option value="">— brak persony —</option>';
  if (sel.innerHTML !== html) sel.innerHTML = html;
  sel.value = state.aktywna || '';
  sel.disabled = !state.modelki.length;
  renderAvatarPersony();
}

// Avatar = pierwsze zdjęcie persony (avatar_url z /api/stan) albo pierwsza litera nazwy.
function avatarHtml(m, klasa) {
  const nazwa = String((m && (m.nazwa || m.slug)) || '?').trim();
  const litera = nazwa.charAt(0).toUpperCase() || '?';
  return m && m.avatar_url
    ? `<span class="avatar ${klasa}"><img src="${esc(m.avatar_url)}" alt="" loading="lazy" data-litera="${esc(litera)}"></span>`
    : `<span class="avatar ${klasa} litera">${esc(litera)}</span>`;
}

function renderAvatarPersony() {
  const el = $('#persona-avatar');
  const m = state.modelki.find(x => x.slug === state.aktywna);
  if (!el) return;
  if (!m) { el.hidden = true; el.innerHTML = ''; return; }
  const litera = String(m.nazwa || m.slug).trim().charAt(0).toUpperCase();
  const html = m.avatar_url ? `<img src="${esc(m.avatar_url)}" alt="" data-litera="${esc(litera)}">` : esc(litera);
  if (el.innerHTML !== html) el.innerHTML = html;
  el.title = `Persona: ${m.nazwa || m.slug}`;
  el.hidden = false;
}

// Pasek sald u góry: po jednej „pastylce” na konto (Higgsfield · yapper.so · ElevenLabs) + „dziś wydałeś X z Y” dla konta,
// które robi rolki tej persony. Kropka w pastylce: zielona (jest), czerwona (za mało / nie widzę), szara (sprawdzam).
const NAZWY_SALD = { higgsfield: 'Higgsfield', yapper: 'yapper.so', wavespeed: 'WaveSpeed', elevenlabs: 'ElevenLabs' };
const JEDNOSTKI_SALD = { kr: ['kredyt', 'kredyty', 'kredytów'], zn: ['znak', 'znaki', 'znaków'], c: ['cent', 'centy', 'centów'] };

function pillSalda(id, s, aktywny, minKr) {
  const nazwa = NAZWY_SALD[id] || id;
  const formy = JEDNOSTKI_SALD[s.jednostka || 'kr'] || JEDNOSTKI_SALD.kr;
  const dolary = (s.jednostka || 'kr') === 'c';
  const tytul = [];
  let klasa = 'szary', tresc;
  if (s.kredyty !== null && s.kredyty !== undefined) {
    klasa = 'ok';
    // kredyty skracamy do „kr” (jak w całym panelu), centy USD (WaveSpeed) pokazujemy jako dolary, znaki ElevenLabs piszemy słowem
    const jedn = (s.jednostka || 'kr') === 'kr' ? 'kr' : odmiana(s.kredyty, ...formy);
    tresc = dolary ? `<b>${esc(usd(s.kredyty))}</b>` : `<b>${esc(liczba(s.kredyty))}</b> <small>${esc(jedn)}</small>`;
    if (id === 'elevenlabs') tytul.push(`ElevenLabs: zostało ${liczba(s.kredyty)}${s.limit ? ' z ' + liczba(s.limit) : ''} znaków do czytania tekstu w tym miesiącu${s.plan ? ' (plan ' + s.plan + ')' : ''}.`);
    else if (id === 'wavespeed') tytul.push(`WaveSpeed: ${usd(s.kredyty)} na koncie na rolki (Seedance 2.5 Turbo) – 10-sekundowa rolka to ok. $2,40–2,60.`);
    else tytul.push(`${nazwa}: kredyty na rolki${id === 'yapper' ? ' (Wan)' : ' i zdjęcia'} – każda rolka kosztuje ich kilkadziesiąt.`);
    if (aktywny) {
      tytul.push('To konto robi teraz rolki tej persony.');
      if (s.kredyty < minKr) { klasa = 'zle'; tytul.push(`To mniej niż ${kwotaKrotko(minKr, s.jednostka)} – tyle bezpiecznik każe zostawić na koncie, więc rolki się nie zrobią.`); }
      else if (minKr) tytul.push(`Bezpiecznik zostawia na koncie co najmniej ${kwotaKrotko(minKr, s.jednostka)}.`);
    }
    if (s.czas) tytul.push(`Stan z ${formatCzas(s.czas)}.`);
  } else if (s.blad) {
    klasa = 'zle';
    tresc = `<small>nie widzę ${id === 'elevenlabs' ? 'znaków' : (dolary ? 'salda' : 'kredytów')}</small>`;
    tytul.push(prostyBlad(s.blad));
  } else {
    tresc = '<small>sprawdzam…</small>';
  }
  return `<span class="saldo-pill ${klasa}${aktywny ? ' aktywny' : ''}" data-saldo="${esc(id)}" title="${esc(tytul.join(' '))}"><i class="kropka" aria-hidden="true"></i><span class="saldo-nazwa">${esc(nazwa)}</span> ${tresc}</span>`;
}

function renderKredyty() {
  const s = state.stan;
  const u = (s && s.ustawienia) || {};
  const b = (s && s.budzet) || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const wrap = $('#kredyty'), el = $('#kredyty-tekst');
  const minKr = Number(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty) || 0;
  const wydano = Number(b.wydano_dzis) || 0, limit = Number(b.limit_dzienny) || 0;
  const znaneKonta = Object.keys(NAZWY_SALD);
  const ids = znaneKonta.filter(id => state.saldo[id]).concat(Object.keys(state.saldo).filter(id => !znaneKonta.includes(id)));
  if (!ids.includes(dost)) ids.unshift(dost);   // konto robiące rolki zawsze widać, nawet zanim saldo przyjdzie
  let html = ids.map(id => pillSalda(id, state.saldo[id] || {}, id === dost, minKr)).join('');
  const aktywne = state.saldo[dost] || {};
  const tytul = [];
  let klasa = '';
  if (aktywne.kredyty !== null && aktywne.kredyty !== undefined) { if (aktywne.kredyty < minKr) klasa = 'zle'; }
  else if (aktywne.blad) klasa = 'zle';
  if (s) {
    const j = b.jednostka || 'kr';
    const ile = v => (j === 'c' ? usd(v) : liczba(v));
    html += ` <span class="kredyty-dzis">· dziś ${wydano ? 'wydałeś ' + esc(ile(wydano)) : 'nic nie wydałeś'}${limit ? ' z ' + esc(ile(limit)) : ''}</span>`;
    if (limit && wydano >= limit) { klasa = klasa || 'zle'; tytul.push('Dzisiejszy limit jest wykorzystany – jutro liczy się od nowa.'); }
    else if (limit && wydano >= limit * 0.8) { klasa = klasa || 'uwaga'; tytul.push(`Zbliżasz się do dziennego limitu ${ile(limit)}.`); }
    else if (limit) tytul.push(`Dzienny limit: ${ile(limit)} (Ustawienia → Limity, tryb pełny).`);
    else if (dost === 'wavespeed') { klasa = klasa || 'zle'; tytul.push('WaveSpeed nie ma dziennego limitu – bez niego fabryka nic tam nie wyda (Ustawienia → Limity, tryb pełny).'); }
  }
  if (el.innerHTML !== html) el.innerHTML = html;
  const znane = aktywne.kredyty !== null && aktywne.kredyty !== undefined;
  wrap.className = 'kredyty' + (klasa ? ' ' + klasa : (znane ? ' ok' : ''));
  wrap.title = tytul.join(' ');
}

function renderOdznaki() {
  const st = (state.stan && state.stan.statystyki) || {};
  const nowe = $('#odznaka-rolki'), bledy = $('#odznaka-rolki-bledy');
  nowe.hidden = !st.nowy; nowe.textContent = st.nowy || '';
  bledy.hidden = !st.blad; bledy.textContent = st.blad || '';
}

// --- konsola „Co się dzieje” ---
function otworzKonsole(otwarta) {
  state.konsola.otwarta = otwarta;
  document.body.classList.toggle('konsola-otwarta', otwarta);
  $('.konsola-przelacz').setAttribute('aria-expanded', String(otwarta));
  if (otwarta) { const pre = $('#konsola-log'); pre.scrollTop = pre.scrollHeight; }
}

function coRobie(z, a) {
  if (z.typ === 'autopilot' || z.typ === 'autopilot_raz') return `autopilot${a.etap ? ' – ' + (ETAPY_AUTOPILOTA[a.etap] || a.etap) : ''}${a.modelka ? ' (' + a.modelka + ')' : ''}`;
  return (CO_ROBIE[z.typ] || z.typ || 'zadanie') + (z.modelka && z.modelka !== state.aktywna ? ` (${z.modelka})` : '');
}

function renderKonsolaStan() {
  const z = state.zadanie || {};
  const a = state.autopilot || {};
  const kropka = $('#konsola-kropka'), tytul = $('#konsola-tytul'), czas = $('#konsola-czas'), surowe = $('#konsola-surowe');
  $('#konsola-stop').hidden = !z.trwa;
  if (z.trwa) {
    kropka.className = 'kropka kredyty pulsuje';
    tytul.textContent = `Robię: ${coRobie(z, a)}`;
    tytul.className = 'konsola-tytul trwa';
    czas.textContent = z.start ? `(${odstepSlownie(sekundOd(z.start))})` : '';
  } else if (z.blad) {
    kropka.className = 'kropka blad';
    tytul.textContent = `Nie wyszło: ${prostyBlad(z.blad)}`;
    tytul.className = 'konsola-tytul blad';
    czas.textContent = z.koniec ? formatCzas(z.koniec) : '';
  } else if (z.typ) {
    kropka.className = 'kropka ok';
    const w = prostyWynik(z.typ, z.wynik);
    tytul.textContent = `Gotowe: ${NAZWY_AKCJI[z.typ] || z.typ}${w ? ' – ' + w : ''}`;
    tytul.className = 'konsola-tytul ok';
    czas.textContent = z.koniec ? formatCzas(z.koniec) : '';
  } else {
    kropka.className = 'kropka';
    tytul.textContent = 'Nic się teraz nie dzieje';
    tytul.className = 'konsola-tytul';
    czas.textContent = '';
  }
  surowe.textContent = z.typ ? `${z.typ}${z.modelka ? ' · ' + z.modelka : ''}${z.blad ? ' · ' + z.blad : (z.wynik ? ' · ' + tekstWyniku(z.wynik) : '')}` : '';
  surowe.title = surowe.textContent;
}

function startKonsoli() {
  if (state.konsola.timer) return;
  state.konsola.timer = setInterval(sprawdzZadanie, 1500);
  sprawdzZadanie();
}
function stopKonsoli() {
  if (state.konsola.timer) { clearInterval(state.konsola.timer); state.konsola.timer = null; }
}
// Obietnica rozwiązana końcowym stanem zadania (po zakończeniu bieżącego zadania w tle).
function czekajNaZadanie() {
  return new Promise(resolve => { state.konsola.oczekujacy.push(resolve); });
}

async function sprawdzZadanie() {
  if (state.konsola.sprawdzanie) return;
  state.konsola.sprawdzanie = true;
  try {
    let z = await api('/api/zadanie?od=' + state.konsola.logOd);
    const dl = typeof z.log_dlugosc === 'number' ? z.log_dlugosc : null;
    if (z.start !== state.konsola.start || (dl !== null && dl < state.konsola.logOd)) {
      // nowe zadanie (albo log zaczęty od nowa) – czyścimy i dociągamy od zera
      state.konsola.start = z.start;
      state.konsola.logOd = 0;
      state.konsola.linie = [];
      $('#konsola-log').textContent = '';
      $('#konsola-skrot').textContent = '';
      z = await api('/api/zadanie?od=0');
    }
    if (Array.isArray(z.log) && z.log.length) dopiszLog(z.log);
    state.konsola.logOd = typeof z.log_dlugosc === 'number' ? z.log_dlugosc : state.konsola.logOd + ((z.log || []).length);
    state.zadanie = z;
    renderKonsolaStan();
    if (state.strona === 'start') { renderKrok2(); renderBanner(); }
    if (z.trwa) {
      state.konsola.trwalo = true;
    } else {
      stopKonsoli();
      if (state.konsola.trwalo) {
        state.konsola.trwalo = false;
        zapamietajPodpisKosztu(z);
        const czekajacy = state.konsola.oczekujacy.splice(0);
        // kroki pośrednie łańcucha „Zrób rolki” (skanuj, koszt) pokazuje karta kroku 2, bez toastów
        const cicho = state.lancuch.trwa && z.typ !== 'generuj';
        if (!cicho) {
          if (z.blad) toast(`Nie wyszło: ${prostyBlad(z.blad)}`, 'blad');
          else if (z.typ === 'podpis' && !(z.wynik && z.wynik.tekst)) {
            // pusty bank podpisów: bank jest w Ustawieniach (tryb pełny) – od razu podsuwamy drogę
            toast('Bank podpisów jest pusty albo wszystko użyte – dodaj podpisy.', 'uwaga', { akcja: 'Dodaj podpisy', cb: () => { location.hash = '#ustawienia/teksty'; } });
          } else { const w = prostyWynik(z.typ, z.wynik); toast(`Gotowe: ${NAZWY_AKCJI[z.typ] || z.typ}${w ? ' – ' + w : ''}`, 'ok'); }
        }
        czekajacy.forEach(r => r(z));
        odswiez();
        if (state.stan && STRONY_PO_ZADANIU.includes(state.strona)) ladujStrone(state.strona);
      }
    }
  } catch (e) {
    // chwilowy błąd – spróbujemy przy następnym ticku
  } finally {
    state.konsola.sprawdzanie = false;
  }
}

function dopiszLog(linie) {
  const k = state.konsola;
  k.linie.push(...linie);
  if (k.linie.length > 3000) k.linie.splice(0, k.linie.length - 3000);
  const pre = $('#konsola-log');
  const naDole = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 40;
  pre.appendChild(document.createTextNode(linie.join('\n') + '\n'));
  if (pre.childNodes.length > 60) pre.textContent = pre.textContent.split('\n').slice(-3000).join('\n');
  if (naDole) pre.scrollTop = pre.scrollHeight;
  // tryb prosty: tylko 3 ostatnie linie, bez znacznika czasu
  $('#konsola-skrot').textContent = k.linie.slice(-3).map(l => l.replace(/^\d\d:\d\d:\d\d /, '')).join('\n');
}

// ============================================================ 7. STRONY
// ---------- Start ----------
async function ladujStart(cicho) {
  renderStart();
  // lista kontrolna (co 30 s) i statystyki 14 dni (co 60 s) – dodatki, ich błędy nie psują Startu
  ladujDiagnoze(!cicho).catch(() => {});
  ladujStatystyki(!cicho).catch(() => {});
  const wyniki = await Promise.allSettled([api('/api/pomysly'), api('/api/dziennik?ile=5')]);
  const [p, d] = wyniki.map(w => (w.status === 'fulfilled' ? w.value : null));
  let zmiana = false;
  if (p) {
    const json = JSON.stringify(p.pomysly || []);
    if (json !== state.pomyslyJson) { state.pomysly = p.pomysly || []; state.pomyslyJson = json; zmiana = true; }
    if (p.statusy && p.statusy.length) state.statusy = p.statusy;
  }
  const telefon = telefonGotowy();
  if (telefon !== state.odbierzTelefon) { state.odbierzTelefon = telefon; zmiana = true; }
  const gra = $$('#odbierz-lista video').some(v => !v.paused);
  if ((zmiana || !cicho || !$('#odbierz-lista').children.length) && !gra) renderOdbierz();
  if (d) renderWpisy($('#start-ostatnio'), (d.wpisy || []).slice().reverse());
  if (!cicho) wyniki.forEach(w => { if (w.status === 'rejected') bladToast(w.reason); });
}

function renderStart() {
  const s = state.stan;
  if (!s) return;
  const u = s.ustawienia || {};
  $('#start-podtytul').textContent = `${nazwaPersony(state.aktywna) || s.modelka} · rolki robi ${opisDostawcy(u)}`;
  renderBanner();
  const niez = (s.niezeskanowane || []).length;
  $('#krok1-info').textContent = niez
    ? `${niez} ${odmiana(niez, 'nowy filmik czeka', 'nowe filmiki czekają', 'nowych filmików czeka')} na sprawdzenie.`
    : 'Nic nowego nie czeka. Wrzuć filmiki, a potem kliknij „Zrób rolki”.';
  $('#folder-wrzutnia').textContent = s.wrzutnia || '—';
  $('#folder-gotowe').textContent = s.gotowe_dir || '—';
  // tani podgląd (Seedance draft) jest tylko u Higgsfield
  $('#krok2-podglad-link').hidden = (u.dostawca || 'higgsfield') !== 'higgsfield';
  renderGdzie();
  renderPersony();
  renderPierwszeKroki();
  renderKrok2();
  renderAutopilot();
  renderDzis();
}

// Foldery aktywnej persony (pulpit): /api/stan -> foldery {wrzutnia, gotowe, zdjecia}; gdy ich nie ma – ścieżki ze stanu persony.
function folderyPersony() {
  const s = state.stan || {};
  const f = state.foldery || {};
  return { wrzutnia: f.wrzutnia || s.wrzutnia || '', gotowe: f.gotowe || s.gotowe_dir || '', zdjecia: f.zdjecia || '' };
}

// Karta „Gdzie wrzucam, gdzie odbieram” na Starcie.
function renderGdzie() {
  const f = folderyPersony();
  const ust = (el, v) => { if (el && el.textContent !== (v || '—')) el.textContent = v || '—'; };
  ust($('#gdzie-wrzutnia'), f.wrzutnia);
  ust($('#gdzie-gotowe'), f.gotowe);
  ust($('#gdzie-zdjecia'), f.zdjecia);
  ust($('#gdzie-pulpit'), state.pulpit || 'ROLKI AI');
}

const NAZWY_FOLDEROW = { wrzutnia: 'tu wrzucasz rolki', gotowe: 'tu rolki zrobione', zdjecia: 'tu zdjęcia zrobione', pulpit: 'ROLKI AI (pulpit)' };
// „Otwórz folder” -> POST /api/folder/otworz (Eksplorator Windows). Folder innej persony: najpierw przełączamy personę.
async function otworzFolder(co, slug) {
  co = co || 'wrzutnia';
  if (slug && slug !== state.aktywna) await zmienPersone(slug);
  const d = await api('/api/folder/otworz', 'POST', { co });
  toast(`Otwieram folder „${NAZWY_FOLDEROW[co] || co}”${d.sciezka ? `: ${nazwaPliku(d.sciezka)}` : ''}.`, 'info');
}

// Sygnalizator na Starcie: czerwony = coś blokuje robienie rolek, pomarańczowy = coś wymaga uwagi, zielony = wszystko gra.
function stanBanera() {
  const s = state.stan;
  if (!s) return null;
  const u = s.ustawienia || {}, b = s.budzet || {}, st = s.statystyki || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const saldo = state.saldo[dost] || {};
  const konto = (state.konta || {})[dost] || {};
  // 1. dostawca rolek nie odpowiada (CLI, logowanie, klucz)
  if (dost === 'higgsfield') {
    const kom = konto.komunikat || saldo.blad || '';
    if (!konto.ok && kom) {
      if (/nie znaleziono cli/i.test(kom)) return { kolor: 'zle', tekst: 'Program Higgsfield nie jest zainstalowany. Kliknij dwa razy w plik <b>instaluj.bat</b>.' };
      if (/zalogowan|auth login|not authenticated|session expired|workspace/i.test(kom)) return { kolor: 'zle', tekst: 'Program Higgsfield nie jest zalogowany. Kliknij dwa razy w plik <b>zaloguj-higgsfield.bat</b>.' };
      return { kolor: 'zle', tekst: `Higgsfield nie odpowiada: ${esc(prostyBlad(kom))}`, przycisk: { tekst: 'Zobacz konta', hash: '#ustawienia/konta' } };
    }
  } else if (saldo.blad) {
    return { kolor: 'zle', tekst: `${esc(NAZWY_SALD[dost] || dost)} nie odpowiada: ${esc(prostyBlad(saldo.blad))}`, przycisk: { tekst: 'Zobacz konta', hash: '#ustawienia/konta' } };
  }
  // 1b. hamulec: autopilot zatrzymał się (np. kilka nieudanych rolek z rzędu) – stoi, dopóki user nie kliknie Wznów
  const pauza = (state.autopilotStan || {}).pauza;
  if (pauza) return { kolor: 'zle', tekst: tekstHamulca(pauza), przycisk: { tekst: 'Wznów', akcja: 'autopilot-wznow' } };
  // 2. za mało kredytów / limit dzienny
  const minKr = Number(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty) || 0;
  if (saldo.kredyty !== null && saldo.kredyty !== undefined && saldo.kredyty < minKr) {
    if (dost === 'wavespeed') return { kolor: 'zle', tekst: `Za mało pieniędzy na koncie WaveSpeed (${esc(usd(saldo.kredyty))}). Doładuj je na wavespeed.ai (Billing).` };
    return { kolor: 'zle', tekst: `Za mało kredytów na koncie (${esc(liczba(saldo.kredyty))}). Doładuj albo zaloguj się na inne konto.` };
  }
  const wyd = Number(b.wydano_dzis) || 0, lim = Number(b.limit_dzienny) || 0;
  if (dost === 'wavespeed' && !lim) return { kolor: 'zle', tekst: 'Rolki robi WaveSpeed, ale nie ma <b>dziennego limitu</b> – bez niego fabryka nic tam nie wyda. Ustaw go w Ustawienia → Limity (tryb pełny – przełącznik w lewym dolnym rogu).', przycisk: { tekst: 'Ustaw limit', hash: '#ustawienia/limity' } };
  if (lim && wyd >= lim) return { kolor: 'zle', tekst: 'Dzisiejszy limit wykorzystany. Jutro zacznie od nowa.' };
  // 3. persona nie jest gotowa
  if (!(s.referencje || []).length) return { kolor: 'zle', tekst: 'Dodaj zdjęcia persony – bez nich AI nie wie, kogo wstawić do filmiku.', przycisk: { tekst: 'Dodaj zdjęcia persony', hash: '#ustawienia/persona' } };
  if (!s.prompt_a) return { kolor: 'zle', tekst: 'Brak promptu persony – to opis dla AI, co zrobić z filmikiem.', przycisk: { tekst: 'Wpisz prompt', hash: '#ustawienia/prompty' } };
  // 4. coś wymaga uwagi
  if (st.blad) return { kolor: 'uwaga', tekst: `${st.blad} ${odmiana(st.blad, 'rolka nie wyszła', 'rolki nie wyszły', 'rolek nie wyszło')} – zobacz w Rolki.`, przycisk: { tekst: 'Zobacz', hash: '#rolki?status=blad' } };
  const bezP = (s.bez_promptu || []).length;
  if (bezP) return { kolor: 'uwaga', tekst: `${bezP} ${odmiana(bezP, 'rolka czeka na prompt', 'rolki czekają na prompt', 'rolek czeka na prompt')} – wpisz go w Rolki.`, przycisk: { tekst: 'Zobacz', hash: '#rolki?status=nowy' } };
  // 5. wszystko gra
  if (state.zadanie && state.zadanie.trwa) return { kolor: 'ok', praca: true, tekst: `Pracuję: ${esc(postepZadania(state.zadanie, state.konsola.linie))}` };
  const doZrob = (s.niezeskanowane || []).length + (s.do_generacji || []).length;
  if (doZrob) return { kolor: 'ok', tekst: `Wszystko gra. Masz ${doZrob} ${odmiana(doZrob, 'filmik', 'filmiki', 'filmików')} do zrobienia.` };
  return { kolor: 'ok', tekst: 'Wszystko zrobione. Wrzuć nowe filmiki.' };
}

function renderBanner() {
  const b = stanBanera();
  if (!b) return;
  $('#banner').className = 'banner ' + (b.kolor || '') + (b.praca ? ' praca' : '');
  $('#banner-tekst').innerHTML = b.tekst;
  let akcja = '';
  if (b.przycisk && b.przycisk.akcja) akcja = `<button class="btn btn-glowny" type="button" data-akcja="${esc(b.przycisk.akcja)}">${esc(b.przycisk.tekst)}</button>`;
  else if (b.przycisk) akcja = `<a class="btn${b.kolor === 'zle' ? ' btn-glowny' : ''}" href="${esc(b.przycisk.hash)}">${esc(b.przycisk.tekst)}</a>`;
  $('#banner-akcja').innerHTML = akcja;
}

// Hamulec autopilota: ten sam tekst na Starcie (duży baner) i na Rolkach (mały pasek).
function tekstHamulca(pauza) {
  return `Autopilot zatrzymał się: <b>${esc(pauza)}</b>. Sprawdź <a href="#rolki?status=blad">rolki, które nie wyszły</a>, i kliknij Wznów.`;
}

function renderHamulecRolek() {
  const el = $('#rolki-hamulec');
  if (!el) return;
  const pauza = state.stan ? (state.autopilotStan || {}).pauza : null;
  el.hidden = !pauza;
  if (pauza) $('#rolki-hamulec-tekst').innerHTML = tekstHamulca(pauza);
}

async function wznowAutopilot(btn) {
  if (btn) btn.disabled = true;
  try {
    const d = await api('/api/autopilot/wznow', 'POST', {});
    state.autopilotStan = d.autopilot_stan || { bledy_z_rzedu: 0, pauza: null, pauza_od: null };
    toast('Wznowione', 'ok');
    renderBanner(); renderHamulecRolek();
    odswiez();
  } finally {
    if (btn) btn.disabled = false;
  }
}

function telefonGotowy() {
  const t = state.telegram || {};
  return !!(t.skonfigurowany && t.sparowany);
}

async function wyslijNaTelefon(id) {
  if (!telefonGotowy()) { toast('Najpierw podłącz telefon: Ustawienia → Konta → Telefon (Telegram).', 'uwaga'); return; }
  await akcja({ typ: 'telegram_wyslij', id }, 'wysyłam na telefon');
}

// Nazwy zestawów „Jakość i koszt” (fabryka.PRESETY_JAKOSCI) po ludzku.
const PRESETY_JAKOSCI = {
  oszczednie: { nazwa: 'Oszczędnie', opis: 'rolki do 10 s – najtaniej, w sam raz na telefon' },
  normalnie: { nazwa: 'Normalnie', opis: 'rolki do 15 s – dobry kompromis' },
  najlepiej: { nazwa: 'Najlepiej', opis: 'rolki do 8 s – zawsze 1080p, najostrzej' },
};
function nazwaPresetu(p) { return (PRESETY_JAKOSCI[p] || {}).nazwa || (p === 'wlasne' ? 'Własne ustawienia' : p); }

// Karta „Dziś” na Starcie: wydane z limitu, ile rolek jeszcze dziś wejdzie (dzis.rolek_zostalo), rolki, problemy (+ zdjęcia w pełnym)
// i jedno zdanie o koszcie jednej rolki (jakosc.koszt_rolki).
function renderDzis() {
  const d = state.dzis, karta = $('#karta-dzis');
  if (!karta) return;
  if (!d) { karta.hidden = true; return; }
  karta.hidden = false;
  const kr = d.kredyty || {}, b = (state.stan && state.stan.budzet) || {}, j = state.jakosc || {};
  const u = (state.stan && state.stan.ustawienia) || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const yapperRobi = dost === 'yapper', wsRobi = dost === 'wavespeed';
  const rolki = Number(d.rolki) || 0, zdjecia = Number(d.zdjecia) || 0, bledy = Number(d.bledy) || 0;
  // kafelek liczy kredyty Higgsfield – limit dzienny bierzemy tylko wtedy, gdy to Higgsfield robi rolki (dla yapper b.limit_dzienny jest w skali yapper);
  // persona na WaveSpeed: kafelek w dolarach (centy z budżetu WaveSpeed) i jej limit
  const hf = Number(kr.higgsfield) || 0, yapper = Number(kr.yapper) || 0, ws = Number(kr.wavespeed) || 0, limit = yapperRobi ? 0 : (Number(b.limit_dzienny) || 0);
  const dodatki = [yapper > 0 ? `+ ${liczba(yapper)} yapper` : '', ws > 0 && !wsRobi ? `+ ${usd(ws)} WaveSpeed` : '', hf > 0 && wsRobi ? `+ ${liczba(hf)} kr Higgsfield` : ''].filter(Boolean).join(' · ');
  const zostalo = d.rolek_zostalo === null || d.rolek_zostalo === undefined ? null : Number(d.rolek_zostalo);
  const kafelekKredytow = wsRobi
    ? { id: 'kredyty', n: ws, tekst: usd(ws), dop2: limit ? ` <small>z ${esc(usd(limit))}</small>` : '', e: limit ? 'wydane dziś na WaveSpeed' : 'WaveSpeed bez dziennego limitu – nic nie wyda', dop: dodatki, klasa: !limit || ws >= limit ? 'zle' : (ws >= limit * 0.8 ? 'uwaga' : '') }
    : { id: 'kredyty', n: hf, dop2: limit ? ` <small>z ${esc(liczba(limit))}</small>` : '', e: limit ? 'kr wydane dziś' : `${odmiana(hf, 'kredyt wydany', 'kredyty wydane', 'kredytów wydanych')} dziś`, dop: dodatki, klasa: limit && hf >= limit ? 'zle' : (limit && hf >= limit * 0.8 ? 'uwaga' : '') };
  const poz = [
    kafelekKredytow,
    { id: 'zostalo', n: zostalo, tekst: zostalo === null ? '?' : `~${liczba(zostalo)}`, e: zostalo === null ? 'rolek jeszcze dziś – nie wiem' : `${odmiana(zostalo, 'rolka', 'rolki', 'rolek')} jeszcze dziś`, klasa: zostalo === 0 ? 'zle' : (zostalo !== null && zostalo <= 2 ? 'uwaga' : ''), tytul: 'Ile rolek jeszcze dziś wejdzie: liczone z dziennego limitu kredytów i z salda na koncie (ponad minimum z bezpiecznika), co niższe.' },
    { id: 'rolki', n: rolki, e: `${odmiana(rolki, 'rolka zrobiona', 'rolki zrobione', 'rolek zrobionych')}` },
    { id: 'problemy', n: bledy, e: odmiana(bledy, 'problem', 'problemy', 'problemów'), klasa: bledy ? 'zle' : '' },
    { id: 'zdjecia', n: zdjecia, e: odmiana(zdjecia, 'zdjęcie', 'zdjęcia', 'zdjęć'), zaawansowane: true },
  ];
  $('#dzis-liczby').innerHTML = poz.map(p => `<div class="dzis-poz${p.klasa ? ' ' + p.klasa : ''}" id="dzis-${p.id}"${p.zaawansowane ? ' data-zaawansowane' : ''}${p.tytul ? ` title="${esc(p.tytul)}"` : ''}><b>${p.tekst !== undefined ? esc(p.tekst) : esc(liczba(p.n))}${p.dop2 || ''}</b><span>${esc(p.e)}</span>${p.dop ? `<small>${esc(p.dop)}</small>` : ''}</div>`).join('');
  $('#dzis-podtytul').textContent = state.modelki.length > 1 ? 'wszystkie persony razem' : '';
  const koszt = $('#dzis-koszt');
  // zdanie o koszcie rolki: stawki Higgsfield (kr) albo WaveSpeed ($) – przy yapper (inna skala kredytów) go nie pokazujemy
  if (j.koszt_rolki && !yapperRobi) {
    koszt.hidden = false;
    koszt.innerHTML = `Jedna rolka to ok. <b>${esc(kwotaKrotko(j.koszt_rolki, j.jednostka))}</b> (zestaw „${esc(nazwaPresetu(j.preset))}”${j.max_sekund_rolki ? `, do ${esc(j.max_sekund_rolki)}&nbsp;s, ${esc(j.resolution || '')}` : ''}${j.jednostka === 'c' ? ', WaveSpeed' : ''}). <a href="#ustawienia/jakosc">Zmień jakość i koszt →</a>`
      + (j.za_drogo ? `<span class="zle dzis-uwaga">Uwaga: to więcej niż Twój limit na rolkę (${esc(kwotaKrotko(j.max_kredyty_na_rolke, j.jednostka))}) – fabryka ją pominie.</span>` : '');
  } else {
    koszt.hidden = true;
  }
}

function ustawWynikKroku(tekst, klasa) {
  state.lancuch.wynik = tekst ? { tekst, klasa: klasa || '' } : null;
  if (state.strona === 'start') renderKrok2();
}

function renderKrok2() {
  const s = state.stan;
  if (!s) return;
  const z = state.zadanie || {}, L = state.lancuch;
  const niez = (s.niezeskanowane || []).length, doGen = (s.do_generacji || []).length, bezP = (s.bez_promptu || []).length;
  const czesci = [];
  if (niez) czesci.push(`${niez} ${odmiana(niez, 'nowy filmik', 'nowe filmiki', 'nowych filmików')} do sprawdzenia`);
  if (doGen) czesci.push(`${doGen} ${odmiana(doGen, 'rolka gotowa', 'rolki gotowe', 'rolek gotowych')} do zrobienia`);
  if (bezP) czesci.push(`${bezP} bez promptu`);
  $('#krok2-info').textContent = czesci.length ? `Czeka: ${czesci.join(', ')}.` : 'Nic nie czeka. Najpierw wrzuć filmiki (krok 1).';
  const trwa = !!z.trwa || L.trwa;
  const btn = $('#btn-zrob-rolki');
  btn.disabled = trwa;
  btn.textContent = trwa ? 'Pracuję…' : 'Zrób rolki';
  $$('#krok-2 .krok-drugie .btn').forEach(b => { b.disabled = trwa; });
  const postep = $('#krok2-postep');
  postep.hidden = !trwa;
  if (trwa) $('#krok2-postep-tekst').textContent = L.etap === 'pytanie' ? 'Czekam na Twoją decyzję…' : postepZadania(z, state.konsola.linie);
  const w = $('#krok2-wynik');
  w.hidden = !L.wynik;
  if (L.wynik) { w.textContent = L.wynik.tekst; w.className = 'krok-wynik' + (L.wynik.klasa ? ' ' + L.wynik.klasa : ''); }
}

function tytulRolki(p) {
  if (p.wariant === 'prompt') return p.opis || `rolka z promptu #${p.id}`;
  const n = nazwaPliku(p.plik_wynikowy || p.zrodlo || '');
  return (n ? bezRozszerzenia(n).replace(/\.raw$/, '') : '') || p.opis || `rolka #${p.id}`;
}

function renderOdbierz() {
  const lista = state.pomysly.filter(p => ['gotowe', 'wygenerowany', 'postprodukcja'].includes(p.status) && p.wideo_url)
    .slice().sort((a, b) => b.id - a.id).slice(0, 6);
  const kont = $('#odbierz-lista');
  if (!lista.length) {
    // pusty stan z jednym jasnym następnym krokiem: wrzuć filmik (gdy nic nie czeka) albo zrób rolki (gdy już czekają)
    const s = state.stan || {};
    const nicNieCzeka = !(s.niezeskanowane || []).length && !(s.do_generacji || []).length;
    kont.innerHTML = `<div class="pusto cicho"><b>Jeszcze nie ma gotowych rolek</b><span>${nicNieCzeka ? 'Najpierw wrzuć filmik (krok 1), potem kliknij „Zrób rolki”.' : 'Kliknij „Zrób rolki” (krok 2) – gotowe pojawią się tutaj.'}</span><button class="btn btn-maly" type="button" data-akcja="${nicNieCzeka ? 'fokus-wrzuc' : 'zrob-rolki'}">${nicNieCzeka ? 'Wrzuć filmik' : 'Zrób rolki'}</button></div>`;
    return;
  }
  kont.innerHTML = lista.map(kartaOdbioru).join('');
}

// Siatka klatek GOTOWEJ rolki (wynik), a gdy jej nie ma – klatki filmiku źródłowego.
function miniaturaRolki(p) {
  return p.wynik_miniatura_url || p.miniatura_url || null;
}

function kartaOdbioru(p) {
  const id = Number(p.id);
  const gra = state.odtwarzane.has(id);
  const nazwa = tytulRolki(p);
  const mini = miniaturaRolki(p);
  const telefon = telefonGotowy() && p.wideo_url;
  return `<div class="odbior" data-id="${id}">
    <button class="odbior-miniatura" type="button" data-akcja="odtworz" data-id="${id}" aria-label="Odtwórz ${esc(nazwa)}">${mini ? `<img src="${esc(mini)}" alt="" loading="lazy">` : ikona('film')}<span class="odbior-play">${ikona('play')}</span></button>
    <div class="odbior-tresc">
      <div class="odbior-nazwa" title="${esc(nazwa)}">${esc(nazwa)}</div>
      <div class="odbior-status"><span class="kropka ${kolorStatusu(p.status)}"></span>${esc(slowoStatusu(p.status))}${p.lipsync_plik ? ' · usta dopasowane' : ''}${p.telegram_wyslano ? `<span class="wyslane" title="Ta rolka poleciała już na telefon">${ikona('ok')}wysłane na telefon</span>` : ''}</div>
      <div class="odbior-akcje">
        <button class="btn btn-maly" type="button" data-akcja="odtworz" data-id="${id}">${ikona('play')}${gra ? 'Ukryj' : 'Odtwórz'}</button>
        ${p.podpis
    ? `<button class="btn btn-maly" type="button" data-akcja="kopiuj" data-tekst="${esc(p.podpis)}" title="${esc(p.podpis)}">${ikona('kopiuj')}Kopiuj podpis</button>`
    : `<button class="btn btn-maly" type="button" data-akcja="podpis" data-id="${id}">Daj podpis</button>`}
        ${telefon ? `<button class="btn btn-maly" type="button" data-akcja="telegram-wyslij" data-id="${id}" title="${p.telegram_wyslano ? 'Wyślij tę rolkę na telefon jeszcze raz' : 'Wyślij gotową rolkę na telefon (Telegram)'}">${ikona('telefon')}${p.telegram_wyslano ? 'Wyślij jeszcze raz' : 'Wyślij na telefon'}</button>` : ''}
      </div>
    </div>
    ${gra ? `<video class="odbior-wideo" controls autoplay preload="metadata" src="${esc(p.wideo_url)}"></video>` : ''}
  </div>`;
}

function renderAutopilot() {
  const a = state.autopilot || {};
  const u = (state.stan && state.stan.ustawienia) || {};
  const chk = $('#autopilot-przelacznik');
  const dlaPersony = !!a.wlaczony && !!u.autopilot;
  if (document.activeElement !== chk) chk.checked = dlaPersony;
  $('#autopilot-opis').textContent = `Co ${u.autopilot_co_minut || 15} min sprawdzi folder, zrobi rolki, wypierze je w Media Tool, zrobi zdjęcia, dobierze podpisy i wyśle gotowe na Telegram. Pilnuje limitów kredytów. Ust nie dopasowuje – lipsync robisz ręcznie.`;
  let txt, klasa = '';
  if (a.trwa) {
    txt = `teraz pracuje: ${ETAPY_AUTOPILOTA[a.etap] || 'sprawdza, co jest do zrobienia'}${a.modelka ? ` (${a.modelka})` : ''}`; klasa = 'praca';
  } else if (dlaPersony) {
    const m = a.nastepny ? minutDo(a.nastepny) : null;
    txt = 'włączony · ' + (m === null ? 'zaraz pierwsze sprawdzenie' : (m <= 0 ? 'zaraz sprawdzi folder' : `następne sprawdzenie za ${m} min`));
    klasa = 'aktywny';
  } else if (a.wlaczony) {
    txt = 'wyłączony dla tej persony (pracuje dla innych person)';
  } else {
    txt = 'wyłączony' + (a.przebiegi ? ` · przebiegów od startu panelu: ${a.przebiegi}` : '');
  }
  const el = $('#autopilot-status');
  el.innerHTML = `<span class="kropka ${klasa === 'praca' ? 'kredyty pulsuje' : (klasa ? 'ok' : '')}"></span>${esc(txt)}`;
  el.className = 'autopilot-status' + (klasa ? ' ' + klasa : '');
  // telefon (Telegram): podłączony / czeka na /start / nie podłączony
  const t = state.telegram || {};
  const tel = $('#autopilot-telefon');
  if (t.skonfigurowany && t.sparowany) {
    const konto = kontoTelegram(u.telegram_czat);
    tel.innerHTML = u.telegram_wysylaj === false
      ? `${ikona('telefon')}<span>Telefon podłączony — wysyłanie gotowych rolek jest wyłączone (<a href="#ustawienia/autopilot">Ustawienia → Autopilot</a>)</span>`
      : `${ikona('telefon')}<span>Telefon podłączony — gotowe rolki lecą na Telegram${konto ? ` (konto <b>${esc(konto)}</b>)` : ''}</span>`;
    tel.className = 'autopilot-telefon ok';
  } else if (t.skonfigurowany) {
    tel.innerHTML = `${ikona('telefon')}<a href="#ustawienia/konta">Telefon: napisz /start do bota</a>`;
    tel.className = 'autopilot-telefon uwaga';
  } else {
    tel.innerHTML = '<a href="#ustawienia/konta">Podłącz telefon →</a>';
    tel.className = 'autopilot-telefon cicho';
  }
}

// Przełącznik na Starcie: włącza pętlę w tle ORAZ zaznacza personę (ustawienie `autopilot`), bo pętla obsługuje
// tylko persony z autopilot=true. Wyłączenie odznacza personę; pętlę gasimy, gdy żadna inna jej nie używa.
async function przelaczAutopilot(wlacz) {
  try {
    if (wlacz) {
      await api('/api/ustawienia', 'POST', { autopilot: true });
      if (state.stan && state.stan.ustawienia) state.stan.ustawienia.autopilot = true;
      const d = await api('/api/autopilot', 'POST', { wlacz: true });
      state.autopilot = d.autopilot || state.autopilot;
      toast('Autopilot włączony. Od teraz sam robi rolki z filmików w folderze.', 'ok');
    } else {
      await api('/api/ustawienia', 'POST', { autopilot: false });
      if (state.stan && state.stan.ustawienia) state.stan.ustawienia.autopilot = false;
      const inne = state.modelki.some(m => m.slug !== state.aktywna && m.autopilot);
      if (!inne) {
        const d = await api('/api/autopilot', 'POST', { wlacz: false });
        state.autopilot = d.autopilot || state.autopilot;
      }
      toast(inne ? 'Autopilot wyłączony dla tej persony (dla innych dalej pracuje).' : 'Autopilot wyłączony.', 'info');
    }
  } catch (e) {
    bladToast(e);
  }
  renderAutopilot();
  odswiez();
}

function renderWpisy(ul, wpisy, pusty = 'Jeszcze nic się nie wydarzyło.') {
  ul.innerHTML = wpisy.length
    ? wpisy.map(w => `<li class="wpis"><span class="kropka ${esc(w.typ || 'info')}"></span><span class="wpis-czas" title="${esc(formatData(w.czas))}">${esc(formatCzas(w.czas))}</span><span class="wpis-tekst" title="${esc(w.tekst)}">${esc(state.pelny ? w.tekst : prostyTekstWpisu(w))}${w.modelka && w.modelka !== state.aktywna ? ` <small>(${esc(w.modelka)})</small>` : ''}</span></li>`).join('')
    : `<li class="wpis"><span class="kropka"></span><span class="wpis-czas"></span><span class="wpis-tekst muted">${esc(pusty)}</span></li>`;
}

// „@huy7128” z ustawienia telegram_czat (dodaje @, gdy user wpisał samą nazwę; id liczbowe zostaje bez @)
function kontoTelegram(v) {
  const k = String(v || '').trim();
  if (!k) return '';
  return k.startsWith('@') || /^-?\d+$/.test(k) ? k : '@' + k;
}

// ---------- Start: pasek person (gdy jest więcej niż jedna) ----------
function renderPersony() {
  const el = $('#persony-pasek');
  if (!el) return;
  const lista = state.modelki || [];
  if (lista.length < 2) { el.hidden = true; if (state.personyHtml) { el.innerHTML = ''; state.personyHtml = ''; } return; }
  const html = lista.map(m => {
    const st = m.statystyki || {}, ap = m.autopilot_stan || {};
    const aktywna = m.slug === state.aktywna;
    const nazwa = m.nazwa || m.slug;
    const dzis = Number(m.rolki_dzis) || 0;
    const konto = kontoTelegram(m.telegram_czat);
    const odznaki = (m.autopilot ? '<span class="persona-odznaka" title="Autopilot obsługuje tę personę">autopilot</span>' : '')
      + (ap.pauza ? `<span class="persona-odznaka stop" title="${esc('Autopilot zatrzymał się: ' + ap.pauza)}">STOP</span>` : '')
      + (konto ? `<span class="persona-odznaka tg" title="${esc('Gotowe rolki tej persony lecą na konto Telegram ' + konto)}">→ ${esc(konto)}</span>` : '');
    return `<button type="button" class="persona-karta${aktywna ? ' aktywna' : ''}" data-akcja="persona-wybierz" data-slug="${esc(m.slug)}" aria-pressed="${aktywna ? 'true' : 'false'}" title="${aktywna ? 'To jest aktywna persona' : 'Przełącz na ' + esc(nazwa)}">
      ${avatarHtml(m, 'persona-karta-avatar')}
      <span class="persona-karta-tresc">
        <span class="persona-karta-nazwa">${esc(nazwa)}${odznaki}</span>
        <span class="persona-karta-meta" data-zaawansowane>czeka ${Number(st.nowy) || 0} · gotowe ${Number(st.gotowe) || 0} · dziś ${dzis} ${esc(odmiana(dzis, 'rolka', 'rolki', 'rolek'))}</span>
      </span>
    </button>`;
  }).join('');
  if (html !== state.personyHtml) { el.innerHTML = html; state.personyHtml = html; }
  el.hidden = false;
}

// ---------- Start: „Pierwsze kroki” (lista kontrolna z /api/diagnoza) ----------
const NAZWY_DIAGNOZY = { ffmpeg: 'ffmpeg (program do filmików)', higgsfield: 'Higgsfield (robi rolki i zdjęcia)', mediatool: 'Media Tool (pranie rolek)', telegram: 'Telefon (Telegram)',
  wavespeed: 'WaveSpeed (tańsze rolki)', 'limit wavespeed': 'Dzienny limit WaveSpeed', yapper: 'yapper.so', 'limit yappera': 'Dzienny limit yappera' };
const TLUMACZENIA_DIAGNOZY = [
  [/brak zdjec persony/g, 'brak zdjęć persony'],
  [/brak promptu A \(stroj z filmu\) - rolki z filmiku beda bez promptu/g, 'brak promptu A'],
  [/zdjecia_dziennie bez modelu zdjec/g, 'autopilot ma robić zdjęcia, ale nie wybrano modelu zdjęć'],
  [/sa zdjecia strojow, ale prompt B \(stroj ze zdjecia\) jest pusty/g, 'są zdjęcia strojów, ale prompt B jest pusty'],
  [/odwoluje sie do/g, 'odwołuje się do'], [/a zdjec jest/g, 'a zdjęć jest'], [/referencje \+ stroj/g, 'zdjęcia + strój'],
  [/najwyzszy numer musi byc rowny liczbie zdjec/g, 'najwyższy numer musi być równy liczbie zdjęć'],
  [/nie podlaczony \(opcjonalnie\)/g, 'nie podłączony'],
  [/token jest, napisz \/start do bota/g, 'token jest – napisz /start do bota na telefonie'],
  [/nie napisal jeszcze \/start do bota/g, 'musi najpierw napisać /start do bota (Telegram nie pozwala botom pisać pierwszym)'],
  [/bot Telegram nie jest podlaczony/g, 'bot Telegram nie jest podłączony – wklej token w Ustawienia → Konta'],
  [/nie moge utworzyc folderow/g, 'nie mogę utworzyć folderów'],
];
function poLudzkuDiagnoza(t) {
  t = String(t || '');
  TLUMACZENIA_DIAGNOZY.forEach(([re, z]) => { t = t.replace(re, z); });
  return t;
}

async function ladujDiagnoze(wymus = false) {
  if (Date.now() - state.diagnozaCzas < (wymus ? 2000 : 30000)) return;
  state.diagnozaCzas = Date.now();
  let d;
  try { d = await api('/api/diagnoza'); }
  catch (e) {
    // lista kontrolna to dodatek – Start działa bez niej; karta mówi tylko, że nie udało się sprawdzić
    if (!state.diagnoza.length) { state.diagnozaStan = 'blad'; if (state.strona === 'start') renderPierwszeKroki(); }
    return;
  }
  state.diagnoza = Array.isArray(d.diagnoza) ? d.diagnoza : [];
  state.diagnozaStan = 'ok';
  if (state.strona === 'start') renderPierwszeKroki();
}
// Po zapisie ustawień / kluczy / zdjęć persony lista kontrolna ma się odświeżyć od razu.
function odswiezDiagnoze() { state.diagnozaCzas = 0; ladujDiagnoze(true).catch(() => {}); }

function wierszDiagnozy(w) {
  const co = String(w.co || ''), ok = w.ok;
  const info = poLudzkuDiagnoza(w.info);
  const link = (t, hash, glowny) => `<a class="btn btn-maly${glowny ? ' btn-glowny' : ''}" href="${esc(hash)}">${esc(t)}</a>`;
  let nazwa = NAZWY_DIAGNOZY[co] || co, tekst = '', akcja = '';
  let klasa = ok === true ? 'ok' : (ok === false ? 'zle' : 'opcja');
  if (co.startsWith('persona ')) {
    const slug = co.slice(8).trim();
    nazwa = `Persona ${nazwaPersony(slug)}`;
    if (ok) tekst = 'gotowa';
    else {
      tekst = info;
      // najpierw zdjęcia (bez nich nic nie ruszy), potem prompt, potem model zdjęć
      const hash = /zdjęć persony/i.test(info) ? '#ustawienia/persona'
        : (/prompt/i.test(info) ? '#ustawienia/prompty' : (/modelu zdj/i.test(info) ? '#ustawienia/zdjecia' : '#ustawienia/persona'));
      akcja = `<button class="btn btn-maly btn-glowny" type="button" data-akcja="pk-persona" data-slug="${esc(slug)}" data-hash="${esc(hash)}">Uzupełnij</button>`;
    }
  } else if (co === 'ffmpeg') {
    tekst = ok ? 'zainstalowany' : 'Kliknij dwa razy instaluj.bat';
  } else if (co === 'higgsfield') {
    if (ok) tekst = 'zalogowany';
    else { tekst = prostyBlad(w.info) || 'nie działa'; akcja = link('Otwórz Konta', '#ustawienia/konta', true); }
  } else if (co === 'mediatool') {
    if (ok) tekst = 'jest';
    else { klasa = 'opcja'; tekst = 'Media Tool nie znaleziony — rolki zostaną bez prania'; }
  } else if (co === 'telegram') {
    if (ok === true) tekst = 'podłączony';
    else if (ok === null || ok === undefined) { tekst = 'nie podłączony'; akcja = link('Podłącz telefon', '#ustawienia/konta', false); }
    else { tekst = info; akcja = link('Otwórz Konta', '#ustawienia/konta', true); }
  } else if (co.startsWith('foldery ')) {
    // foldery persony na pulpicie: „wrzucasz tu … / gotowe tu …” + „Otwórz” (folder innej persony = najpierw przełącz personę)
    const slug = co.slice(8).trim();
    nazwa = `Foldery ${nazwaPersony(slug)}`;
    if (ok && w.wrzutnia) {
      const dodatek = `<span class="pk-foldery"><span><em>wrzucasz tu:</em> <code title="${esc(w.wrzutnia)}">${esc(krotkaSciezka(w.wrzutnia))}</code></span><span><em>gotowe tu:</em> <code title="${esc(w.gotowe || '')}">${esc(krotkaSciezka(w.gotowe || ''))}</code></span></span>`;
      akcja = `<button class="btn btn-maly" type="button" data-akcja="otworz-folder" data-co="wrzutnia" data-slug="${esc(slug)}">${ikona('folder')}Otwórz „wrzucasz”</button>`
        + `<button class="btn btn-maly" type="button" data-akcja="otworz-folder" data-co="gotowe" data-slug="${esc(slug)}">${ikona('folder')}Otwórz „gotowe”</button>`;
      return wierszHtml(co, ok, 'ok', nazwa, '', dodatek, akcja, '');
    }
    tekst = info || 'nie udało się utworzyć folderów';
    akcja = `<button class="btn btn-maly btn-glowny" type="button" data-akcja="pk-persona" data-slug="${esc(slug)}" data-hash="#ustawienia/foldery">Sprawdź foldery</button>`;
  } else if (co === 'wavespeed') {
    if (ok) tekst = String(w.info || '').replace('klucz dziala, saldo', 'działa, na koncie').replace(/\$(\d+)\.(\d\d)/, '$$$1,$2').replace(' - doladuj konto', ' – doładuj konto');
    else { tekst = prostyBlad(w.info) || 'nie działa'; akcja = link('Otwórz Konta', '#ustawienia/konta', true); }
  } else if (co === 'limit wavespeed') {
    if (ok) tekst = 'dziś ' + String(w.info || '').replace(/^dzis /, '').replace(/\$(\d+)\.(\d\d)/g, '$$$1,$2');
    else { tekst = 'nie ustawiony – bez niego fabryka nic nie wyda na WaveSpeed'; akcja = link('Ustaw limit', '#ustawienia/limity', ok === false); }
  } else if (co.startsWith('telefon ')) {
    // osobne konto Telegram persony (ustawienie telegram_czat) – musi raz napisać /start do bota
    const slug = co.slice(8).trim();
    nazwa = `Telegram ${nazwaPersony(slug)}`;
    const m = String(w.info || '').match(/->\s*(\S+)/);
    if (ok) tekst = `gotowe rolki lecą na ${m ? m[1] : 'osobne konto'}`;
    else {
      tekst = info;
      akcja = `<button class="btn btn-maly btn-glowny" type="button" data-akcja="pk-persona" data-slug="${esc(slug)}" data-hash="#ustawienia/persona">Zobacz konto</button>`;
    }
  } else {
    tekst = info;
  }
  const surowe = state.pelny && w.info && w.info !== tekst ? `<small>${esc(w.info)}</small>` : '';
  return wierszHtml(co, ok, klasa, nazwa, tekst, '', akcja, surowe);
}

function wierszHtml(co, ok, klasa, nazwa, tekst, dodatek, akcja, surowe) {
  return `<div class="pk-wiersz ${klasa}" data-co="${esc(co)}" data-ok="${ok === true ? '1' : (ok === false ? '0' : '')}">
    <span class="pk-kropka" aria-hidden="true"></span>
    <div class="pk-tekst"><b>${esc(nazwa)}${tekst ? ':' : ''}</b>${tekst ? `<span>${esc(tekst)}</span>` : ''}${klasa === 'opcja' ? '<span class="pk-opcja">opcjonalnie</span>' : ''}${dodatek || ''}${surowe}</div>
    <div class="pk-akcja">${akcja}</div>
  </div>`;
}

// Karta jest widoczna od razu (nagłówek zawsze „Pierwsze kroki”); pigułka obok mówi: sprawdzam… / N z M gotowe / wszystko gotowe ✓.
function renderPierwszeKroki() {
  const karta = $('#pierwsze-kroki');
  if (!karta) return;
  if (!state.stan) { karta.hidden = true; return; }
  karta.hidden = false;
  const lista = state.diagnoza || [];
  const pill = $('#pk-pill'), licznik = $('#pk-licznik'), ul = $('#pk-lista'), btn = $('#pk-przelacz'), opis = $('#pk-opis');
  if (!lista.length) {
    const blad = state.diagnozaStan === 'blad';
    pill.textContent = blad ? 'nie udało się sprawdzić' : 'sprawdzam…';
    pill.className = 'pk-pill ' + (blad ? 'uwaga' : 'czekam');
    licznik.textContent = '';
    karta.classList.remove('gotowe');
    btn.hidden = true; opis.hidden = false;
    const html = `<div class="pk-wiersz ${blad ? 'zle' : 'czekam'}"><span class="pk-kropka" aria-hidden="true"></span><div class="pk-tekst"><span>${blad ? 'Nie udało się sprawdzić, czy wszystko jest na miejscu. Spróbuję za chwilę – jeśli to nie minie, zrób zrzut ekranu i wyślij go Claude\'owi.' : 'Sprawdzam, czy wszystko jest na miejscu (programy, konto, zdjęcia persony, foldery)…'}</span></div></div>`;
    if (ul.innerHTML !== html) ul.innerHTML = html;
    ul.hidden = false;
    return;
  }
  // wymagane = wszystko poza „opcjonalnie” (ok: null) i brakującym Media Tool (nie blokuje – rolki będą tylko bez prania)
  const wymagane = lista.filter(w => w.ok !== null && w.ok !== undefined && !(w.co === 'mediatool' && w.ok === false));
  const gotowe = wymagane.filter(w => w.ok === true);
  const komplet = wymagane.length > 0 && gotowe.length === wymagane.length;
  // nowy problem -> karta sama się rozwija (reset ręcznego zwinięcia)
  const klucz = lista.filter(w => w.ok === false).map(w => w.co).join('|');
  if (klucz !== state.pkKlucz) { state.pkKlucz = klucz; state.pkOtwarte = null; }
  const otwarte = state.pkOtwarte === null ? !komplet : state.pkOtwarte;
  karta.classList.toggle('gotowe', komplet);
  pill.textContent = komplet ? 'wszystko ustawione ✓' : `${gotowe.length} z ${wymagane.length} gotowe`;
  pill.className = 'pk-pill ' + (komplet ? 'ok' : 'uwaga');
  const opc = lista.length - wymagane.length;
  licznik.textContent = opc ? `· ${opc} ${odmiana(opc, 'opcjonalny', 'opcjonalne', 'opcjonalnych')}` : '';
  opis.hidden = komplet;
  btn.hidden = false;
  btn.textContent = otwarte ? 'zwiń' : 'pokaż';
  btn.setAttribute('aria-expanded', String(otwarte));
  const html = lista.map(wierszDiagnozy).join('');
  if (ul.innerHTML !== html) ul.innerHTML = html;
  ul.hidden = !otwarte;
}

// ---------- Statystyki: ostatnie 14 dni (Start + Historia) ----------
async function ladujStatystyki(wymus = false) {
  if (state.statystyki && Date.now() - state.statystykiCzas < (wymus ? 2000 : 60000)) { renderStatystyki(); return; }
  state.statystykiCzas = Date.now();
  let d;
  try { d = await api('/api/statystyki?dni=14'); }
  catch (e) { if (!state.statystyki) renderStatystyki(e); return; }
  state.statystyki = d;
  renderStatystyki();
}

// Domyślnie: Start zwinięty w trybie prostym, rozwinięty w pełnym; Historia rozwinięta. Wybór użytkownika zostaje w localStorage.
function zastosujDomyslneStaty() {
  $$('details[data-staty]').forEach(det => {
    let zap = null;
    try { zap = localStorage.getItem(KLUCZ_STATY + det.dataset.staty); } catch (e) { /* prywatne okno */ }
    const chce = zap === '1' || zap === '0' ? zap === '1' : (det.dataset.staty === 'historia' ? true : state.pelny);
    if (det.open !== chce) det.open = chce;
  });
}

function etykietaDnia(iso) {
  const d = data(iso + 'T12:00:00');
  return d ? `${dwaZnaki(d.getDate())}.${dwaZnaki(d.getMonth() + 1)}` : String(iso || '');
}
function dzisIso() {
  const d = new Date();
  return `${d.getFullYear()}-${dwaZnaki(d.getMonth() + 1)}-${dwaZnaki(d.getDate())}`;
}
// „ładna” górna granica osi: 1–5 bez zmian, wyżej zaokrąglone do 1 / 2 / 2,5 / 5 × 10^n
function ladnyMax(v) {
  v = Number(v) || 0;
  if (v <= 0) return 1;
  if (v <= 5) return Math.ceil(v);
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const k of [1, 2, 2.5, 5, 10]) if (v <= k * p) return k * p;
  return 10 * p;
}
function opisDnia(d, dzis) {
  const dt = data(d.dzien + 'T12:00:00');
  const kr = d.kredyty || {};
  const r = Number(d.rolki) || 0, hf = Number(kr.higgsfield) || 0, yap = Number(kr.yapper) || 0, ws = Number(kr.wavespeed) || 0, z = Number(d.zdjecia) || 0, b = Number(d.bledy) || 0;
  return `${dt ? DNI_TYGODNIA[dt.getDay()] + ' ' : ''}${etykietaDnia(d.dzien)}${dzis ? ' (dziś)' : ''}: ${r} ${odmiana(r, 'rolka', 'rolki', 'rolek')}, ${kredytow(hf)}${yap ? ` (+ ${liczba(yap)} yapper)` : ''}${ws ? ` (+ ${usd(ws)} WaveSpeed)` : ''}, ${z} ${odmiana(z, 'zdjęcie', 'zdjęcia', 'zdjęć')}, ${b} ${odmiana(b, 'problem', 'problemy', 'problemów')}`;
}

// Jeden SVG, dwa panele na wspólnej osi dni: słupki = rolki dziennie, pod nimi linia z kropkami = kredyty Higgsfield.
// Bez bibliotek; podpowiedzi przez <title>; etykiety dni co drugi dzień, dziś wyróżnione.
function rysujWykres(dni, W) {
  const n = Math.max(1, dni.length);
  const padL = 46, padR = 14, padT = 28, h1 = 104, przerwa = 44, h2 = 60, osX = 34;
  const H = padT + h1 + przerwa + h2 + osX;
  const sw = (W - padL - padR) / n;
  const bw = Math.max(4, Math.min(24, Math.floor(sw) - 6));
  const y0a = padT + h1, top2 = y0a + przerwa, y0b = top2 + h2;
  const rolki = dni.map(d => Number(d.rolki) || 0);
  const kredyty = dni.map(d => Number((d.kredyty || {}).higgsfield) || 0);
  const maxR = ladnyMax(Math.max(0, ...rolki)), maxK = ladnyMax(Math.max(0, ...kredyty));
  const idxMaxR = rolki.indexOf(Math.max(...rolki)), idxMaxK = kredyty.indexOf(Math.max(...kredyty));
  const dzis = dzisIso();
  const cx = i => padL + i * sw + sw / 2;
  const yR = v => y0a - (v / maxR) * h1, yK = v => y0b - (v / maxK) * h2;
  const f = v => liczba(v);
  const out = [];
  // siatka + osie Y (hairline, bez kresek)
  const tickiR = Number.isInteger(maxR / 2) ? [0, maxR / 2, maxR] : [0, maxR];
  tickiR.forEach(t => { out.push(`<line class="siatka" x1="${padL}" x2="${W - padR}" y1="${yR(t).toFixed(1)}" y2="${yR(t).toFixed(1)}"/><text class="os-tekst" x="${padL - 8}" y="${(yR(t) + 4).toFixed(1)}" text-anchor="end">${esc(f(t))}</text>`); });
  [0, maxK].forEach(t => { out.push(`<line class="siatka" x1="${padL}" x2="${W - padR}" y1="${yK(t).toFixed(1)}" y2="${yK(t).toFixed(1)}"/><text class="os-tekst" x="${padL - 8}" y="${(yK(t) + 4).toFixed(1)}" text-anchor="end">${esc(f(t))}</text>`); });
  out.push(`<text class="panel-tytul" x="${padL}" y="13">Rolki dziennie</text>`);
  out.push(`<text class="panel-tytul" x="${padL}" y="${y0a + 18}">Kredyty Higgsfield dziennie</text>`);
  // dziś – delikatne tło kolumny
  const idxDzis = dni.findIndex(d => d.dzien === dzis);
  if (idxDzis >= 0) out.push(`<rect class="dzis-tlo" x="${(padL + idxDzis * sw).toFixed(1)}" y="${padT - 6}" width="${sw.toFixed(1)}" height="${(y0b - padT + 6).toFixed(1)}" rx="6"/>`);
  // słupki, kropki problemów, etykiety dni – jedna grupa na dzień (tooltip <title> z wszystkimi wartościami)
  const linia = [];
  dni.forEach((d, i) => {
    const jestDzis = d.dzien === dzis;
    const v = rolki[i], h = (v / maxR) * h1, x = cx(i) - bw / 2, y = y0a - h, r = Math.min(4, bw / 2, h);
    let slupek = '';
    if (v > 0) slupek = h > r
      ? `<path class="slupek" d="M${x.toFixed(1)},${y0a} V${(y + r).toFixed(1)} Q${x.toFixed(1)},${y.toFixed(1)} ${(x + r).toFixed(1)},${y.toFixed(1)} H${(x + bw - r).toFixed(1)} Q${(x + bw).toFixed(1)},${y.toFixed(1)} ${(x + bw).toFixed(1)},${(y + r).toFixed(1)} V${y0a} Z"/>`
      : `<rect class="slupek" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw}" height="${h.toFixed(1)}"/>`;
    const k = kredyty[i];
    linia.push(`${cx(i).toFixed(1)},${yK(k).toFixed(1)}`);
    const problem = (Number(d.bledy) || 0) > 0 ? `<circle class="kropka-problem" cx="${cx(i).toFixed(1)}" cy="${y0b + 11}" r="3"/>` : '';
    // etykieta dnia co drugi dzień, licząc od dziś (dziś zawsze podpisane)
    const podpis = (n - 1 - i) % 2 === 0 ? `<text class="os-tekst${jestDzis ? ' dzis' : ''}" x="${cx(i).toFixed(1)}" y="${y0b + 26}" text-anchor="middle">${jestDzis ? 'dziś' : esc(etykietaDnia(d.dzien))}</text>` : '';
    // etykiety wartości tylko tam, gdzie coś mówią: największy słupek i dziś
    let etykieta = '';
    if (v > 0 && (i === idxMaxR || jestDzis)) etykieta += `<text class="etykieta${i === idxMaxR ? '' : ' cicha'}" x="${cx(i).toFixed(1)}" y="${(y - 5).toFixed(1)}" text-anchor="middle">${esc(f(v))}</text>`;
    if (k > 0 && i === idxMaxK) etykieta += `<text class="etykieta cicha" x="${cx(i).toFixed(1)}" y="${(yK(k) - 9).toFixed(1)}" text-anchor="middle">${esc(f(k))}</text>`;
    out.push(`<g class="dzien"><title>${esc(opisDnia(d, jestDzis))}</title><rect class="hit" x="${(padL + i * sw).toFixed(1)}" y="${padT - 6}" width="${sw.toFixed(1)}" height="${(H - padT + 6 - 8).toFixed(1)}"/>${slupek}${problem}${podpis}${etykieta}</g>`);
  });
  // linia kredytów pod kropkami (kropki rysują się w grupach dni, więc linia idzie przed nimi w kolejności DOM – dlatego osobna warstwa)
  out.push(`<polyline class="linia-kredyty" points="${linia.join(' ')}"/>`);
  dni.forEach((d, i) => { if (kredyty[i] > 0) out.push(`<circle class="kropka-kredyty" cx="${cx(i).toFixed(1)}" cy="${yK(kredyty[i]).toFixed(1)}" r="4"><title>${esc(opisDnia(d, d.dzien === dzis))}</title></circle>`); });
  out.push(`<line class="os" x1="${padL}" x2="${W - padR}" y1="${y0a}" y2="${y0a}"/><line class="os" x1="${padL}" x2="${W - padR}" y1="${y0b}" y2="${y0b}"/>`);
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Wykres: rolki i kredyty Higgsfield z ostatnich ${n} dni" preserveAspectRatio="xMinYMin meet">${out.join('')}</svg>`;
}

// Tabela-bliźniak wykresu (tryb pełny) – te same liczby bez kolorów.
function tabelaStatystyk(dni) {
  const wiersze = dni.slice().reverse().map(d => {
    const kr = d.kredyty || {};
    return `<tr><td class="czas">${esc(etykietaDnia(d.dzien))}</td><td>${esc(liczba(d.rolki || 0))}</td><td>${esc(liczba(d.zdjecia || 0))}</td><td>${esc(liczba(kr.higgsfield || 0))}</td><td>${esc(liczba(kr.yapper || 0))}</td><td>${esc(usd(kr.wavespeed || 0))}</td><td>${esc(liczba(d.bledy || 0))}</td></tr>`;
  }).join('');
  return `<details class="zwijane cicho" data-zaawansowane><summary>${ikona('chevron-dol')}pokaż jako tabelę</summary><div class="tabela-wrap"><table class="tabela staty-tabela"><thead><tr><th>Dzień</th><th>Rolki</th><th>Zdjęcia</th><th>Kredyty HF</th><th>yapper</th><th>WaveSpeed</th><th>Problemy</th></tr></thead><tbody>${wiersze}</tbody></table></div></details>`;
}

function renderStatystyki(blad = null) {
  const s = state.statystyki;
  $$('details[data-staty]').forEach(det => {
    const kont = det.querySelector('[data-staty-tresc]'), skrot = det.querySelector('[data-staty-skrot]');
    if (!kont) return;
    if (!s) {
      kont.innerHTML = `<div class="staty-pusto">${blad ? 'Nie udało się pobrać statystyk: ' + esc(prostyBlad(blad)) : 'Liczę…'}</div>`;
      det.dataset.klucz = '';
      return;
    }
    const dni = s.dni || [], r = s.razem || {}, kr = r.kredyty || {};
    const rolki = Number(r.rolki) || 0, hf = Number(kr.higgsfield) || 0, yap = Number(kr.yapper) || 0, ws = Number(kr.wavespeed) || 0, bledy = Number(r.bledy) || 0, nsfw = Number(r.nsfw) || 0;
    if (skrot) skrot.textContent = `${rolki} ${odmiana(rolki, 'rolka', 'rolki', 'rolek')} · ${kredytow(hf)}${bledy ? ` · ${bledy} ${odmiana(bledy, 'problem', 'problemy', 'problemów')}` : ''}${nsfw ? ` · filtr NSFW: ${nsfw}` : ''}`;
    // szerokość: gdy karta jest zwinięta, treść ma 0 px – bierzemy szerokość karty minus jej padding
    const szer = Math.max(300, Math.round(kont.clientWidth || (det.clientWidth - 48) || 600));
    const klucz = JSON.stringify([dni, r, szer, state.pelny]);
    if (det.dataset.klucz === klucz) return;
    det.dataset.klucz = klucz;
    const liczby = `<div class="staty-liczby">
      <div class="dzis-poz" data-staty-rolki><b>${esc(liczba(rolki))}</b><span>${esc(odmiana(rolki, 'rolka', 'rolki', 'rolek'))} razem</span></div>
      <div class="dzis-poz" data-staty-kredyty><b>${esc(liczba(hf))}</b><span>${esc(odmiana(hf, 'kredyt', 'kredyty', 'kredytów'))} Higgsfield</span>${yap > 0 || ws > 0 ? `<small>${[yap > 0 ? `+ ${esc(liczba(yap))} yapper` : '', ws > 0 ? `+ ${esc(usd(ws))} WaveSpeed` : ''].filter(Boolean).join(' · ')}</small>` : ''}</div>
      <div class="dzis-poz${bledy ? ' zle' : ''}" data-staty-problemy><b>${esc(liczba(bledy))}</b><span>${esc(odmiana(bledy, 'problem', 'problemy', 'problemów'))}</span>${nsfw ? `<small title="Rolki odrzucone przez filtr treści (NSFW) w ostatnich 14 dniach – kredyty wróciły">odrzucone przez filtr: ${esc(liczba(nsfw))}</small>` : ''}</div>
    </div>`;
    const pusto = !dni.some(d => (Number(d.rolki) || 0) || (Number((d.kredyty || {}).higgsfield) || 0) || (Number(d.bledy) || 0) || (Number(d.zdjecia) || 0));
    const wykres = pusto
      ? '<div class="staty-pusto">Jeszcze nic tu nie ma. Zrób pierwszą rolkę na <a href="#start">Starcie</a> – wykres zacznie się rysować.</div>'
      : `<div class="wykres-legenda"><span><i></i>rolki dziennie</span><span><i class="linia"></i>kredyty Higgsfield</span><span><i class="problem"></i>dni z problemami</span></div><div class="wykres">${rysujWykres(dni, szer)}</div>${tabelaStatystyk(dni)}`;
    kont.innerHTML = liczby + wykres;
  });
}

// ---------- Pomoc ----------
function renderPomoc() {
  const s = state.stan;
  const brak = 'dodaj personę – wtedy pokażę ścieżkę';
  const f = folderyPersony();
  $('#pomoc-wrzutnia').textContent = s && f.wrzutnia ? f.wrzutnia : brak;
  $('#pomoc-gotowe').textContent = s && f.gotowe ? f.gotowe : brak;
  $('#pomoc-zdjecia').textContent = s && f.zdjecia ? f.zdjecia : brak;
  $$('#pomoc-gdzie [data-akcja="otworz-folder"]').forEach(b => { b.disabled = !s; });
  renderNsfw();
  if (s) ladujNsfw().catch(() => {});
}

// Pomoc → „Filtr NSFW”: /api/nsfw aktywnej persony (ile odrzuceń, ryzykowne słowa w promptach, wskazówki).
async function ladujNsfw() {
  const d = await api('/api/nsfw');
  state.nsfw = d;
  renderNsfw();
}

const NAZWY_PROMPTOW_NSFW = { A: 'Prompt A (strój z filmu)', B: 'Prompt B (strój ze zdjęcia)', zdjecia: 'Prompty zdjęć' };
// Wskazówki z /api/nsfw przychodzą bez polskich znaków (backend) – tu dopisujemy ogonki. Kolejność ma znaczenie (zdjecia przed zdjec).
const POLSKIE_WSKAZOWKI = [
  [/odrzucil/g, 'odrzucił'], [/wracaja/g, 'wracają'], [/\bsa\b/g, 'są'], [/ktore/g, 'które'], [/blokowac/g, 'blokować'],
  [/Zamien/g, 'Zamień'], [/materialu/g, 'materiału'], [/zdjecia/g, 'zdjęcia'], [/zdjeciu/g, 'zdjęciu'], [/zdjec\b/g, 'zdjęć'],
  [/strojow/g, 'strojów'], [/stroj z filmu/g, 'strój z filmu'], [/stroj ze zdj/g, 'strój ze zdj'], [/skapy stroj/g, 'skąpy strój'],
  [/przeswity/g, 'prześwity'], [/duzo skory/g, 'dużo skóry'], [/odrzucaja/g, 'odrzucają'], [/CALA rolke/g, 'CAŁĄ rolkę'],
  [/odwazniejsze/g, 'odważniejsze'], [/zwyklym/g, 'zwykłym'], [/kapielowego/g, 'kąpielowego'], [/ida do kazdej/g, 'idą do każdej'],
  [/wiecej/g, 'więcej'], [/\bwiec\b/g, 'więc'], [/zrodlowy/g, 'źródłowy'], [/lozko/g, 'łóżko'], [/\bbron\b/g, 'broń'],
  [/Sprobuj/g, 'Spróbuj'], [/krotszego ujecia/g, 'krótszego ujęcia'], [/\(potnij w panelu: dziel_dlugie\)/g, '(Ustawienia → Autopilot, tryb pełny → „Długi filmik potnij na kawałki”)'],
  [/Jesli masz pewnosc/g, 'Jeśli masz pewność'], [/pomylka/g, 'pomyłka'], [/oddaja/g, 'oddają'], [/cofaja/g, 'cofają'], [/zglos/g, 'zgłoś'],
  [/dwoch odrzuceniach z rzedu/g, 'dwóch odrzuceniach z rzędu'], [/probowac/g, 'próbować'], [/jedna powtorka/g, 'jedna powtórka'],
  [/\bslowa\b/g, 'słowa'], [/tresci/g, 'treści'], [/\bWYNIKU\b/g, 'WYNIKU'],
  [/dalby/g, 'dałby'], [/wlaczonym/g, 'włączonym'], [/probuje/g, 'próbuje'], [/Recznie/g, 'Ręcznie'],
];
function poLudzkuWskazowka(t) {
  t = String(t || '');
  POLSKIE_WSKAZOWKI.forEach(([re, z]) => { t = t.replace(re, z); });
  return t;
}

function renderNsfw() {
  const el = $('#nsfw-tresc');
  if (!el) return;
  if (!state.stan) { el.innerHTML = '<p class="muted">Dodaj personę – wtedy sprawdzę jej prompty i odrzucone rolki.</p>'; return; }
  const n = state.nsfw;
  if (!n) { el.innerHTML = '<p class="muted">Sprawdzam odrzucone rolki tej persony…</p>'; return; }
  const slowa = n.slowa || {};
  const razem = Number(n.odrzucone) || 0, ostatnio = Number(n.odrzucone_ostatnio) || 0, dni = Number(n.dni) || 14;
  const liczby = `<div class="nsfw-liczby">
    <div class="dzis-poz${ostatnio ? ' zle' : ''}"><b>${esc(liczba(ostatnio))}</b><span>${esc(odmiana(ostatnio, 'odrzucona', 'odrzucone', 'odrzuconych'))} w ${dni} dni</span></div>
    <div class="dzis-poz"><b>${esc(liczba(razem))}</b><span>razem (${esc(nazwaPersony(state.aktywna) || 'persona')})</span></div>
  </div>`;
  const wiersze = ['A', 'B', 'zdjecia'].map(k => {
    const lista = Array.isArray(slowa[k]) ? slowa[k] : [];
    return `<div class="nsfw-slowa-wiersz"><b>${esc(NAZWY_PROMPTOW_NSFW[k])}:</b>${lista.length ? lista.map(s => `<span class="slowo">${esc(s)}</span>`).join('') : '<span class="slowo czyste">bez ryzykownych słów ✓</span>'}</div>`;
  }).join('');
  const wsk = Array.isArray(n.wskazowki) ? n.wskazowki : [];
  el.innerHTML = `${liczby}
    <p><b>Ryzykowne słowa w Twoich promptach</b> (filtr lubi je blokować – zamień na neutralne, np. „black top” zamiast „mesh top”):</p>
    <div class="nsfw-slowa">${wiersze}</div>
    ${wsk.length ? `<p><b>Co pomaga:</b></p><ul class="nsfw-wskazowki">${wsk.map(w => `<li>${esc(poLudzkuWskazowka(w))}</li>`).join('')}</ul>` : ''}
    <p class="muted">Prompty zmienisz w <a href="#ustawienia/prompty">Ustawienia → Prompty</a>, zdjęcia strojów w <a href="#ustawienia/persona">Ustawienia → Persona</a>. Odrzucone rolki znajdziesz w <a href="#rolki?status=blad">Rolki → nie wyszły</a>.</p>`;
}

// ---------- Rolki ----------
async function ladujRolki(cicho) {
  let d;
  try { d = await api('/api/pomysly'); }
  catch (e) { if (!cicho) throw e; return; }
  const json = JSON.stringify(d.pomysly || []);
  state.statusy = (d.statusy && d.statusy.length) ? d.statusy : STATUSY.slice();
  const telefon = telefonGotowy();
  if (cicho) {
    // bez zmian w rolkach, telefonie i zestawie jakości (szacunki „ok. N kr” zależą od zestawu) – nic nie przerysowujemy
    if (json === state.pomyslyJson && telefon === state.rolkiTelefon && podpisRolek() === state.rolkiJakosc) return;
    const akt = document.activeElement;
    if (akt && akt.tagName === 'TEXTAREA' && $('#rolki-lista').contains(akt)) return; // nie przerywaj edycji promptu
    if ($$('#rolki-lista video').some(v => !v.paused)) return;                        // ani odtwarzania
  }
  state.pomysly = d.pomysly || [];
  state.pomyslyJson = json;
  state.rolkiTelefon = telefon;
  renderRolki();
}

function renderRolki() {
  renderZpLista();
  const u = (state.stan && state.stan.ustawienia) || {};
  state.rolkiJakosc = podpisRolek();
  renderHamulecRolek();
  $('#pomysl-tekst-hint').hidden = !!u.mode_bez_zrodla;
  if (!FILTRY_ROLEK.some(f => f.id === state.filtr)) state.filtr = 'wszystkie';
  const liczby = {};
  FILTRY_ROLEK.forEach(f => { liczby[f.id] = f.statusy ? state.pomysly.filter(p => f.statusy.includes(p.status)).length : state.pomysly.length; });
  $('#rolki-filtry').innerHTML = FILTRY_ROLEK.map(f =>
    `<button type="button" class="chip${state.filtr === f.id ? ' aktywny' : ''}" data-akcja="filtr" data-filtr="${esc(f.id)}">${esc(f.nazwa)} <span class="n">${liczby[f.id] || 0}</span></button>`
  ).join('');
  const filtr = FILTRY_ROLEK.find(f => f.id === state.filtr);
  const lista = state.pomysly.filter(p => !filtr.statusy || filtr.statusy.includes(p.status)).slice().sort((a, b) => b.id - a.id);
  const kont = $('#rolki-lista');
  if (!lista.length) {
    const s = state.stan || {};
    kont.innerHTML = state.pomysly.length
      ? '<div class="pusto"><b>Nic w tej grupie</b><span>Kliknij „wszystkie”, żeby zobaczyć całą listę.</span></div>'
      : `<div class="pusto"><span class="ikona">${ikona('film')}</span><b>Nie ma jeszcze żadnej rolki</b><span>Wrzuć filmiki powyżej albo do folderu:</span><span class="sciezka">${esc(s.wrzutnia || '')}</span><span>a potem kliknij „Zrób rolki” na Starcie – każdy filmik stanie się rolką.</span><a class="btn btn-glowny" href="#start">Przejdź do Startu</a></div>`;
    return;
  }
  kont.innerHTML = lista.map(kartaRolki).join('');
}

// Szacunek kosztu rolki w kredytach: sekundy × stawka (jakosc.koszt_sekundy); bez długości – jakosc.koszt_rolki. null = nie wiem.
function szacunekKosztu(sekundy) {
  const j = state.jakosc;
  if (!j) return null;
  const s = Number(sekundy);
  // rozdzielczość wybiera długość klipu: ≤ prog_1080p_s → 1080p, dłuższy → 720p (backend: fabryka.PROG_1080P_S)
  const stawka = (s > 0 && j.prog_1080p_s) ? (s <= Number(j.prog_1080p_s) ? j.koszt_sekundy_1080p : j.koszt_sekundy_720p) : j.koszt_sekundy;
  if (s > 0 && stawka) return Math.max(1, Math.round(s * Number(stawka)));
  return j.koszt_rolki ? Number(j.koszt_rolki) : null;
}

// Podpis tego, co decyduje o cenie rolki: rozdzielczość i stawka za sekundę. Koszt policzony przy innym podpisie jest nieaktualny.
// (Długość rolki max_sekund_rolki nie wchodzi – już zeskanowane filmiki nie są cięte na nowo, więc ich cena się nie zmienia.)
function podpisJakosci() {
  const j = state.jakosc || {};
  return `${j.resolution || ''}|${j.koszt_sekundy || ''}`;
}
// Podpis listy rolek: cena + koszt typowej rolki (szacunek dla pomysłów bez filmiku) – zmiana przerysowuje „ok. N kr”.
function podpisRolek() {
  const j = state.jakosc || {};
  return `${podpisJakosci()}|${j.koszt_rolki || ''}`;
}

// Po zadaniu „koszt” zapamiętujemy, przy jakim zestawie jakości policzono każdą rolkę (pozycje [id, koszt]).
function zapamietajPodpisKosztu(z) {
  if (!z || z.typ !== 'koszt' || z.blad || !z.wynik || !Array.isArray(z.wynik.pozycje)) return;
  const sig = podpisJakosci();
  z.wynik.pozycje.forEach(x => { if (Array.isArray(x) && x[1] !== null && x[1] !== undefined) state.kosztJakosc[Number(x[0])] = sig; });
}

// Czy zapisany koszt czekającej rolki (p.koszt) jest jeszcze aktualny? Nie, gdy od policzenia zmienił się zestaw „Jakość i koszt”
// (np. 720p -> 1080p) albo gdy odbiega od bieżącego szacunku (długość × stawka za sekundę) o ponad 30 %.
// Backend liczy koszt od nowa tuż przed generacją, więc bez tego panel pokazywałby zaniżoną kwotę i pytał o inną, niż user zapłaci.
function kosztNieaktualny(p) {
  if (!p || p.koszt === null || p.koszt === undefined) return false;
  const sig = state.kosztJakosc[Number(p.id)];
  if (sig && sig !== podpisJakosci()) return true;
  const czas = Number((p.info_zrodla || {}).czas) || 0;
  const sz = czas ? szacunekKosztu(czas) : null;
  if (!sz) return false;   // bez długości filmiku nie ma z czym porównać
  return Math.abs(Number(p.koszt) - sz) / sz > 0.3;
}

function przyciskRolki(akcja, id, tekst, klasa = '') {
  return `<button class="btn btn-maly${klasa ? ' ' + klasa : ''}" type="button" data-akcja="${akcja}" data-id="${id}">${tekst}</button>`;
}

function kartaRolki(p) {
  const id = Number(p.id);
  const status = p.status || 'nowy';
  const info = p.info_zrodla || {};
  const nazwa = tytulRolki(p);
  const u = (state.stan && state.stan.ustawienia) || {};
  const dostPersony = u.dostawca || 'higgsfield';
  const zPromptu = p.wariant === 'prompt';
  const higgsfield = dostPersony === 'higgsfield' || zPromptu;   // rolki z promptu robi zawsze Higgsfield
  // szacunek „ok. N” z /api/stan.jakosc umiemy dla Higgsfield (kredyty) i WaveSpeed (dolary) – yapper ma inną skalę
  const szacuje = higgsfield || dostPersony === 'wavespeed';
  // kto liczył koszt rolki: zrobiona/nieudana – jej dostawca, czekająca – dostawca persony
  const jednostkaKosztu = zPromptu ? 'kr' : jednostkaDostawcy(status !== 'nowy' && p.dostawca ? p.dostawca : dostPersony);
  const fakty = [];
  fakty.push(zPromptu ? `${ikona('pioro')}z promptu` : (p.wariant === 'tekst' ? 'z tekstu' : (p.wariant === 'B' ? 'strój ze zdjęcia' : 'strój z filmu')));
  const nieaktualny = status === 'nowy' && szacuje && kosztNieaktualny(p);
  if (p.koszt !== null && p.koszt !== undefined && !nieaktualny) fakty.push(esc(kwota(p.koszt, jednostkaKosztu)));
  else if (status === 'nowy' && szacuje) {
    // szacunek dla rolki, która czeka: długość filmiku × stawka za sekundę (jakosc.koszt_sekundy); bez długości – koszt typowej rolki.
    const sz = szacunekKosztu(info.czas);
    const j = state.jakosc || {};
    const dol = j.jednostka === 'c';
    const stawka = info.czas && j.prog_1080p_s ? (Number(info.czas) <= Number(j.prog_1080p_s) ? j.koszt_sekundy_1080p : j.koszt_sekundy_720p) : j.koszt_sekundy;
    const jak = info.czas ? `${esc(Number(info.czas).toFixed(1).replace('.', ','))} s × ${dol ? esc(usd(stawka)) + '/s' : esc(String(stawka).replace('.', ',')) + ' kr/s'} (${esc(p.resolution || '')})` : 'typowa rolka w Twoim zestawie jakości';
    const ok = esc(kwotaKrotko(sz, j.jednostka));
    if (sz && nieaktualny) fakty.push(`<span class="uwaga" title="Od ostatniego liczenia (${esc(kwota(p.koszt, jednostkaKosztu))}) zmienił się zestaw „Jakość i koszt”. Szacunek: ${jak}. „Zrób tę rolkę” policzy koszt na nowo, zanim zapyta.">ok. ${ok} · policz ponownie</span>`);
    else if (sz) fakty.push(`<span title="Szacunek: ${jak}. Dokładną cenę policzy „Ile kosztuje?”.">ok. ${ok}</span>`);
  }
  if (p.resolution && p.zrodlo) fakty.push(`<span title="Rozdzielczość wybiera długość klipu: ≤8 s → 1080p, dłuższe → 720p">${esc(p.resolution)}</span>`);
  if (p.zapas_opis) {
    const zapasowy = NAZWY_SALD[p.dostawca] || p.dostawca || 'zapasowy dostawca';
    fakty.push(`<span class="ok rolka-zapas" title="Pierwszy model odrzucił tę rolkę (filtr NSFW), więc zrobił ją zapasowy model (${esc(zapasowy)}). Koszt u ${esc(zapasowy)}.">${esc(p.zapas_opis)}</span>`);
  }
  if (p.audio_nazwa || p.audio) fakty.push(`${ikona('audio')}z głosem`);
  if (p.lipsync_plik) fakty.push('usta dopasowane');
  if (p.telegram_wyslano) fakty.push(`<span class="ok" title="Ta rolka poleciała już na telefon">${ikona('ok')}wysłane na telefon</span>`);
  if (status === 'nowy' && !p.prompt_higgsfield) fakty.push('<span class="zle">brak promptu</span>');
  const meta = [];
  if (state.pelny) {
    meta.push(`#${id}`, `status: ${esc(status)}`);
    if (p.zrodlo) meta.push(`źródło: ${esc(nazwaPliku(p.zrodlo))}`);
    if (info.czas) meta.push(`${esc(Number(info.czas).toFixed(1).replace('.', ','))} s`);
    if (info.szer && info.wys) meta.push(`${esc(info.szer)}×${esc(info.wys)}`);
    if (p.dostawca) meta.push(esc(p.dostawca));
    if (p.job_id) meta.push(`job ${esc(p.job_id)}`);
    if (p.plik_wynikowy) meta.push(`wynik: ${esc(nazwaPliku(p.plik_wynikowy))}`);
    if (p.lipsync_plik) meta.push(`lipsync: ${esc(nazwaPliku(p.lipsync_plik))}`);
    if (p.wygenerowano) meta.push(`wygenerowano ${esc(formatCzas(p.wygenerowano))}`);
  }
  const bezPromptu = status === 'nowy' && !p.prompt_higgsfield;
  const promptOtwarty = state.otwartePrompty.has(id) || bezPromptu;
  const gra = state.odtwarzane.has(id) && p.wideo_url;
  const telefon = telefonGotowy() && !!p.wideo_url;
  // tani podgląd (Seedance draft, ~21 kr): tylko Higgsfield i tylko rolki, które czekają
  const podgladMozliwy = status === 'nowy' && higgsfield;
  const maPodglad = !!p.podglad_url;
  const podgladGra = maPodglad && !gra && state.podglady.has(id);
  if (p.podglad_koszt !== null && p.podglad_koszt !== undefined) fakty.push(`podgląd: ${esc(kredytow(p.podglad_koszt))}`);
  else if (maPodglad) fakty.push('jest tani podgląd');
  const mini = miniaturaRolki(p);
  const obraz = mini ? `<img src="${esc(mini)}" alt="" loading="lazy">` : ikona('film');
  // miniatura gotowej rolki = przycisk „Odtwórz” (klik otwiera film na karcie); rolki z tanim podglądem = przycisk „Zobacz podgląd”
  let miniatura;
  if (p.wideo_url) {
    miniatura = `<button class="rolka-miniatura klik" type="button" data-akcja="odtworz" data-id="${id}" title="${gra ? 'Ukryj film' : 'Odtwórz'}" aria-label="${gra ? 'Ukryj film' : 'Odtwórz'} ${esc(nazwa)}">${obraz}<span class="rolka-play">${ikona(gra ? 'stop' : 'play')}</span></button>`;
  } else if (maPodglad) {
    const obrazPodgladu = p.podglad_miniatura_url ? `<img src="${esc(p.podglad_miniatura_url)}" alt="" loading="lazy">` : obraz;
    miniatura = `<button class="rolka-miniatura klik" type="button" data-akcja="podglad-pokaz" data-id="${id}" title="${podgladGra ? 'Ukryj podgląd' : 'Zobacz tani podgląd'}" aria-label="${podgladGra ? 'Ukryj podgląd' : 'Zobacz tani podgląd'} ${esc(nazwa)}"><span class="rolka-tag">podgląd</span>${obrazPodgladu}<span class="rolka-play">${ikona(podgladGra ? 'stop' : 'play')}</span></button>`;
  } else {
    miniatura = `<div class="rolka-miniatura">${obraz}</div>`;
  }
  let glowny = '', drugi = '';
  if (status === 'nowy') glowny = przyciskRolki('generuj-pomysl', id, 'Zrób tę rolkę', 'btn-glowny');
  else if (status === 'blad') glowny = przyciskRolki('ponow', id, 'Spróbuj jeszcze raz', 'btn-glowny');
  else if (p.wideo_url) glowny = przyciskRolki('odtworz', id, gra ? 'Ukryj film' : `${ikona('play')}Odtwórz`, 'btn-glowny');
  // drugi przycisk: tani podgląd (oszczędza kredyty, więc widoczny także w trybie prostym) albo wysyłka na telefon
  if (status === 'nowy' && maPodglad) drugi += przyciskRolki('podglad-pokaz', id, `${ikona(podgladGra ? 'stop' : 'play')}${podgladGra ? 'Ukryj podgląd' : 'Zobacz podgląd'}`);
  else if (podgladMozliwy) drugi += przyciskRolki('podglad', id, `Tani podgląd (~${KOSZT_PODGLADU} kr)`);
  if (telefon && !p.telegram_wyslano) drugi += przyciskRolki('telegram-wyslij', id, `${ikona('telefon')}Wyślij na telefon`);
  if (p.mozna_dograc_glos) drugi += przyciskRolki('dograj-glos', id, `${ikona('audio')}Dograj głos (ElevenLabs)`);
  const menu = [przyciskRolki('prompt-pokaz', id, p.prompt_higgsfield ? 'Pokaż / zmień prompt' : 'Wpisz prompt')];
  if (status === 'nowy') menu.push(przyciskRolki('koszt-pomysl', id, 'Ile kosztuje?'));
  if (podgladMozliwy && maPodglad) menu.push(przyciskRolki('podglad', id, `Tani podgląd jeszcze raz (~${KOSZT_PODGLADU} kr)`));
  if (maPodglad && status !== 'nowy') menu.push(`<a class="btn btn-maly" href="${esc(p.podglad_url)}" target="_blank" rel="noopener">Zobacz tani podgląd</a>`);
  if (['wygenerowany', 'postprodukcja', 'gotowe'].includes(status)) {
    menu.push(przyciskRolki('pierz', id, 'Wypierz w Media Tool'));
    menu.push(przyciskRolki('lipsync-pomysl', id, 'Dopasuj usta (lipsync)'));
    menu.push(przyciskRolki('podpis', id, p.podpis ? 'Daj nowy podpis' : 'Daj podpis'));
  }
  if (p.lipsync_url) menu.push(`<a class="btn btn-maly" href="${esc(p.lipsync_url)}" target="_blank" rel="noopener">Otwórz wersję z dopasowanymi ustami</a>`);
  if (telefon && p.telegram_wyslano) menu.push(przyciskRolki('telegram-wyslij', id, `${ikona('telefon')}Wyślij na telefon jeszcze raz`));
  if (status === 'w_toku') menu.push(przyciskRolki('przerwij-pomysl', id, 'Przestań czekać (sprawdziłem w apce)', 'btn-zly'));
  else menu.push(przyciskRolki('usun-pomysl', id, 'Usuń', 'btn-zly'));
  let powod = '';
  if (status === 'w_toku') {
    const maJob = !!(p.w_toku && p.w_toku.job_id);
    powod = maJob
      ? `<div class="rolka-meta"><b>Generuje się</b> u dostawcy${p.w_toku_opis ? ` (${esc(p.w_toku_opis)})` : ''}. Możesz zamknąć panel – fabryka dokończy tę rolkę sama po ponownym uruchomieniu (ten sam job, bez drugiej opłaty).</div>`
      : `<div class="rolka-meta"><b>Wysyłanie</b> do dostawcy${p.w_toku_opis ? ` (${esc(p.w_toku_opis)})` : ''} – numer joba jeszcze niepotwierdzony. Fabryka sprawdza, czy rolka powstała, i <b>nie wyśle jej drugi raz</b> sama.</div>`;
  }
  const filtr = status === 'blad' ? (p.powod === 'nsfw' || p.powod === 'ip' ? p.powod : (p.powod ? null : (/nsfw/i.test(p.notatki || '') ? 'nsfw' : (/ip_detected/i.test(p.notatki || '') ? 'ip' : null)))) : null;
  if (filtr === 'nsfw') {
    // odrzucone przez filtr treści: wyraźna plakietka + jedno zdanie + link do Pomocy (czemu i co z tym zrobić)
    const kto = p.dostawca === 'wavespeed'
      ? 'Moderacja WaveSpeed uznała filmik, zdjęcie albo słowo w prompcie za ryzykowne – nie patrzy na kontekst. Koszt liczę do limitu na wszelki wypadek (WaveSpeed nie pisze, czy go oddaje).'
      : 'Filtr Higgsfield uznał filmik, zdjęcie stroju albo słowo w prompcie za ryzykowne – nie patrzy na kontekst. Kredyty wróciły.';
    powod = `<div class="rolka-filtr"><span class="rolka-filtr-plakietka">${ikona('filtr')}odrzucone przez filtr treści (NSFW)</span><span>${kto} <a href="#pomoc/nsfw">Dlaczego? → Pomoc</a></span>${state.pelny && p.notatki ? `<small>${esc(p.notatki)}</small>` : ''}</div>`;
  } else if (filtr === 'ip') {
    powod = `<div class="rolka-filtr"><span class="rolka-filtr-plakietka">${ikona('filtr')}model wykrył znaną postać/markę</span><span>W filmiku, na zdjęciu albo w prompcie jest coś, co wygląda jak znana osoba, logo albo marka. Wrzuć inny fragment albo zasłoń logo. <a href="#pomoc/niewyszla">Co zrobić? → Pomoc</a></span>${state.pelny && p.notatki ? `<small>${esc(p.notatki)}</small>` : ''}</div>`;
  } else if (status === 'blad' && p.notatki) powod = `<div class="rolka-powod"><b>Dlaczego:</b> ${esc(prostyBlad(p.notatki))}${state.pelny ? `<small>${esc(p.notatki)}</small>` : ''}</div>`;
  else if (status !== 'w_toku' && p.notatki && state.pelny) powod = `<div class="rolka-meta">${esc(p.notatki)}</div>`;
  if (filtr) {
    // zapas po NSFW (yapper/Wan): czemu nie ruszył albo co dał – z notatek i listy prób
    const zp = /zapas (?:po NSFW )?pominiety:?\s*(.*)$/i.exec(p.notatki || '');
    const proby = (p.proby || []).filter(x => Number(x.krok) > 0);
    if (zp) powod += `<div class="rolka-meta">Zapas nie ruszył: ${esc(zp[1].slice(0, 300))}</div>`;
    else if (proby.length) powod += `<div class="rolka-meta">Zapas też nie przeszedł: ${proby.map(x => `${esc(x.model || '?')} – ${esc(x.status || '?')}`).join(', ')}</div>`;
  }
  return `<article class="rolka" data-id="${id}">
    ${miniatura}
    <div class="rolka-tresc">
      <div class="rolka-gora"><h3 class="rolka-nazwa">${esc(nazwa)}</h3><span class="status ${kolorStatusu(status)}"><span class="kropka ${kolorStatusu(status)}"></span>${esc(slowoStatusu(status))}</span></div>
      ${meta.length ? `<div class="rolka-meta">${meta.join(' · ')}</div>` : ''}
      ${p.opis && p.opis !== nazwa && p.wariant === 'tekst' ? `<div class="rolka-meta">${esc(p.opis)}</div>` : ''}
      ${zPromptu && p.z_promptu_opis ? `<div class="rolka-meta">${esc(p.z_promptu_opis)}</div>` : ''}
      ${zPromptu && p.z_promptu_dlaczego ? `<div class="rolka-meta">Asystent: ${esc(p.z_promptu_dlaczego)}</div>` : ''}
      ${zPromptu && ['gotowe', 'wygenerowany'].includes(status) ? `<div class="rolka-ocena"><span>Jak wyszła?</span><button class="btn btn-maly${p.ocena === 'dobra' ? ' aktywny' : ''}" type="button" data-akcja="ocena" data-id="${id}" data-ocena="dobra" aria-pressed="${p.ocena === 'dobra'}">${ikona('ok')}Dobra – więcej takich</button><button class="btn btn-maly${p.ocena === 'slaba' ? ' aktywny' : ''}" type="button" data-akcja="ocena" data-id="${id}" data-ocena="slaba" aria-pressed="${p.ocena === 'slaba'}">Słaba</button></div>` : ''}
      <div class="rolka-fakty">${fakty.map(f => `<span class="fakt">${f}</span>`).join('')}</div>
      ${powod}
      ${p.podpis ? `<div class="rolka-podpis"><span>${esc(p.podpis)}</span><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(p.podpis)}" title="kopiuj podpis">${ikona('kopiuj')}kopiuj</button></div>` : ''}
      ${promptOtwarty ? `<div class="rolka-prompt"><label for="prompt-${id}">Prompt – opis dla AI, co zrobić z tym filmikiem</label><textarea id="prompt-${id}" data-prompt="${id}" spellcheck="false" placeholder="Wklej prompt persony albo własny…">${esc(p.prompt_higgsfield || '')}</textarea><div class="rzad"><button class="btn btn-maly btn-glowny" type="button" data-akcja="zapisz-prompt" data-id="${id}">Zapisz prompt</button>${bezPromptu ? '' : `<button class="btn btn-maly" type="button" data-akcja="prompt-pokaz" data-id="${id}">Zwiń</button>`}</div></div>` : ''}
      ${gra ? `<video controls autoplay preload="metadata" src="${esc(p.wideo_url)}"></video>` : ''}
      ${podgladGra ? `<video class="rolka-podglad-wideo" controls autoplay preload="metadata" src="${esc(p.podglad_url)}"></video><div class="rolka-podglad-info">To tylko tani podgląd (gorsza jakość). Jeśli persona wygląda dobrze – kliknij „Zrób tę rolkę”.</div>` : ''}
      <div class="rolka-akcje">${glowny}${drugi}<details class="menu"><summary class="btn btn-maly">więcej ${ikona('chevron-dol')}</summary><div class="menu-lista">${menu.join('')}</div></details></div>
    </div>
  </article>`;
}

// Treść pytania „Robić?” z kosztem w kredytach.
function trescKosztu(razem, n, nieznane = 0) {
  const s = state.stan || {};
  const u = s.ustawienia || {}, b = s.budzet || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const j = jednostkaDostawcy(dost);
  const ile = v => (j === 'c' ? usd(v) : liczba(v));
  const saldo = (state.saldo[dost] || {}).kredyty;
  let html = '';
  if (razem !== null && razem !== undefined) {
    html += `<p>To będzie kosztować około <b>${esc(kwota(razem, j))}</b> (${n} ${odmiana(n, 'rolka', 'rolki', 'rolek')}${j === 'c' ? ', WaveSpeed' : ''}).`;
    if (nieznane) html += ` Dla ${nieznane} ${odmiana(nieznane, 'rolki', 'rolek', 'rolek')} nie udało się policzyć kosztu – fabryka policzy go tuż przed zrobieniem.`;
    html += '</p>';
    if (saldo !== null && saldo !== undefined) html += `<p>Na koncie masz ${esc(ile(saldo))}, po zrobieniu zostanie około <b>${esc(ile(saldo - razem))}</b>.</p>`;
  } else {
    html += `<p><b>Nie udało się policzyć kosztu.</b> Fabryka policzy go tuż przed zrobieniem każdej rolki i zatrzyma się, gdyby przekroczył bezpiecznik.</p>`;
  }
  if (b.limit_dzienny) html += `<p>Dziś wydano ${esc(ile(b.wydano_dzis || 0))} z ${esc(ile(b.limit_dzienny))} dozwolonych.</p>`;
  html += j === 'c' ? '<p class="dialog-uwaga">To wyda dolary z konta WaveSpeed.</p>' : '<p class="dialog-uwaga">To wyda kredyty.</p>';
  return html;
}

function kosztZWyniku(z, id) {
  const poz = (z && z.wynik && Array.isArray(z.wynik.pozycje)) ? z.wynik.pozycje : [];
  const w = poz.find(x => Array.isArray(x) && Number(x[0]) === id);
  return w && w[1] !== null && w[1] !== undefined ? Number(w[1]) : null;
}
// Kto wycenił rolkę (trzeci element pozycji): inny niż dostawca persony = zapas po NSFW (yapper: kredyty yapper.so, WaveSpeed: dolary).
function dostawcaZWyniku(z, id) {
  const poz = (z && z.wynik && Array.isArray(z.wynik.pozycje)) ? z.wynik.pozycje : [];
  const w = poz.find(x => Array.isArray(x) && Number(x[0]) === id);
  return w && w[2] ? String(w[2]) : null;
}

async function generujPomysl(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (p && !p.prompt_higgsfield) { toast('Ta rolka nie ma promptu – wpisz go (więcej → Wpisz prompt) i zapisz.', 'uwaga'); return; }
  if (state.zadanie && state.zadanie.trwa) { toast('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 'uwaga'); return; }
  let koszt = p && p.koszt !== null && p.koszt !== undefined ? Number(p.koszt) : null;
  let zapas = null;
  if (koszt === null || kosztNieaktualny(p) || (p && p.krok_startowy) || (p && p.wariant === 'prompt')) {
    // brak kosztu albo koszt sprzed zmiany zestawu „Jakość i koszt” – liczymy na nowo (tanie, ~12 s), żeby pytać o prawdziwą kwotę
    const z = await akcjaCzekaj({ typ: 'koszt', ids: [id] }, 'liczę koszt', true);
    if (!z) return;
    koszt = z.blad ? null : kosztZWyniku(z, id);
    const dz = dostawcaZWyniku(z, id);
    zapas = dz && dz !== ((state.stan && state.stan.dostawca) || 'higgsfield') ? dz : null;
  }
  const nazwaZapasu = zapas === 'wavespeed' ? 'WaveSpeed' : 'yapper.so (Wan 3.0)';
  const tresc = zapas
    ? `<p>Zapas po NSFW: rolka pójdzie na <b>${esc(nazwaZapasu)}</b>${koszt !== null ? ` za ok. <b>${esc(zapas === 'wavespeed' ? usd(koszt) : liczba(koszt) + ' kredytów yapper')}</b>` : ''} – to inne pieniądze niż kredyty Higgsfield. Pilnuje tego dzienny limit ${zapas === 'wavespeed' ? 'WaveSpeed' : 'yappera'}.</p><p class="dialog-uwaga">To wyda ${zapas === 'wavespeed' ? 'dolary z konta WaveSpeed' : 'kredyty yapper.so'}.</p>`
    : trescKosztu(koszt, 1, koszt === null ? 0 : 0);
  const zPromptu = p && p.wariant === 'prompt';
  const w = await potwierdz({ tytul: 'Zrobić tę rolkę?', tresc: zPromptu ? trescKosztuZPromptu(koszt) : tresc, ok: 'Zrób' });
  if (!w) return;
  // max_kr: backend liczy cenę jeszcze raz tuż przed wysłaniem i nie wyśle, gdy wyjdzie wyższa niż ta z pytania
  await akcja(Object.assign({ typ: 'generuj', ids: [id] }, koszt !== null && (!zapas || zPromptu) ? { max_kr: koszt } : {}), 'robię rolkę');
}

// Pytanie „Robić?” dla rolki z promptu z kolejki – zawsze Higgsfield (kredyty), niezależnie od dostawcy persony.
function trescKosztuZPromptu(koszt) {
  const saldo = (state.saldo.higgsfield || {}).kredyty;
  let html = koszt !== null && koszt !== undefined
    ? `<p>Rolka z promptu (Higgsfield): około <b>${esc(kredytow(koszt))}</b>.` + (saldo !== null && saldo !== undefined ? ` Po zrobieniu zostanie około <b>${esc(liczba(saldo - koszt))} kr</b>.` : '') + '</p>'
    : '<p><b>Nie udało się policzyć kosztu.</b> Fabryka policzy go tuż przed zrobieniem i zatrzyma się, gdyby przekroczył bezpiecznik.</p>';
  html += '<p class="dialog-uwaga">To wyda kredyty Higgsfield.</p>';
  return html;
}

// Tani podgląd: Seedance draft (~21 kr) tym samym promptem – rolka dalej „czeka”, a Ty widzisz, czy prompt działa.
async function taniPodglad(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (p && !p.prompt_higgsfield) { toast('Ta rolka nie ma promptu – wpisz go (więcej → Wpisz prompt) i zapisz.', 'uwaga'); return; }
  if (state.zadanie && state.zadanie.trwa) { toast('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 'uwaga'); return; }
  const w = await potwierdz({
    tytul: 'Tani podgląd rolki',
    tresc: `<p>Zrobię szybką, tanią wersję (gorsza jakość), żebyś zobaczył, czy prompt działa. Koszt ~${KOSZT_PODGLADU} kredytów. Robić?</p><p class="dialog-uwaga">To wyda kredyty.</p>`,
    ok: 'Zrób podgląd',
  });
  if (!w) return;
  await akcja({ typ: 'podglad', id }, 'robię tani podgląd');
}

async function ponowPomysl(id) {
  const d = await api(`/api/pomysly/${id}/ponow`, 'POST', {});
  if (d && d.od_zapasu) toast('Ta rolka odpadła na filtrze NSFW – tym razem spróbuję od razu na zapasowym modelu (z ustawienia „Gdy filtr odrzuci rolkę”).', 'info');
  await ladujRolki(false);
  odswiez();
  await generujPomysl(id);
}

async function policzKosztWszystkich() {
  const s = state.stan;
  if (s && !(s.do_generacji || []).length) {
    toast((s.niezeskanowane || []).length ? 'Najpierw „Tylko sprawdź nowe filmiki” – potem policzę koszt.' : 'Nie ma nic do policzenia – wrzuć filmiki.', 'uwaga');
    return;
  }
  await akcja({ typ: 'koszt' }, 'liczę koszt');
}

async function zapiszPrompt(id) {
  const ta = $(`textarea[data-prompt="${id}"]`);
  if (!ta) return;
  const d = await api(`/api/pomysly/${id}`, 'PATCH', { prompt_higgsfield: ta.value });
  const i = state.pomysly.findIndex(x => Number(x.id) === id);
  if (i >= 0 && d.pomysl) state.pomysly[i] = d.pomysl;
  state.pomyslyJson = JSON.stringify(state.pomysly);
  state.otwartePrompty.delete(id);
  toast('Prompt zapisany.', 'ok');
  renderRolki();
  odswiez();
}

// Rolka w toku, która utknęła (np. bez numeru joba): user sprawdza w apce i świadomie przestaje czekać.
async function przerwijPomysl(id) {
  const w = await potwierdz({
    tytul: 'Przestać czekać na tę rolkę?',
    tresc: '<p>Fabryka przestanie sprawdzać tę rolkę i oznaczy ją jako „nie wyszło”.</p><p><b>Najpierw sprawdź w apce Higgsfield</b> (lista generacji), czy rolka nie powstała – kredyty mogły już zejść. Jeśli powstała, pobierz ją stamtąd.</p><p class="dialog-uwaga">„Spróbuj jeszcze raz” po tym zrobi NOWĄ, płatną generację.</p>',
    ok: 'Przestań czekać', klasa: 'btn-zly',
  });
  if (!w) return;
  await api(`/api/pomysly/${id}/przerwij`, 'POST', { potwierdzam: true });
  toast('Przestałem czekać – rolka jest teraz „nie wyszło”.', 'info');
  await ladujRolki(false);
  odswiez();
}

async function usunPomysl(id) {
  const w = await potwierdz({ tytul: 'Usunąć tę rolkę z listy?', tresc: '<p>Filmik źródłowy w folderze zostaje. Jeśli chcesz, usunę też gotowy plik wideo.</p>', ok: 'Usuń', klasa: 'btn-zly', checkbox: 'Usuń też gotowy plik wideo' });
  if (!w) return;
  await api(`/api/pomysly/${id}${w.zaznaczone ? '?plik=1' : ''}`, 'DELETE');
  toast('Usunięto.', 'ok');
  state.otwartePrompty.delete(id); state.odtwarzane.delete(id);
  await ladujRolki(false);
  odswiez();
}

async function dodajPomyslTekstowy(f) {
  const opis = $('#pt-opis').value.trim();
  if (!opis) { toast('Napisz, o czym ma być rolka.', 'uwaga'); return; }
  let prompt = $('#pt-prompt').value.trim();
  if (!prompt) {
    // backend zapisuje pomysł z pustym promptem (i taki czeka „bez promptu”) – panel sam wstawia prompt A persony
    if (!state.ustawieniaPelne) state.ustawieniaPelne = await api('/api/ustawienia');
    prompt = ((state.ustawieniaPelne.prompty || {}).a || '').trim();
    if (!prompt) { toast('Wpisz prompt albo najpierw ustaw prompt persony (Ustawienia → Prompty).', 'uwaga'); return; }
  }
  const d = await api('/api/pomysly', 'POST', { opis, prompt });
  toast(`Dodano pomysł #${d.id} do listy.`, 'ok');
  f.reset();
  await ladujRolki(false);
  odswiez();
}

// ---------- Z promptu (rolka bez filmiku: krótki pomysł -> asystent dobiera resztę -> cena -> rolka) ----------
// Widok prosty: persona, pole „co ma się dziać” + Losuj, jedna linijka „Asystent dobrał…”, cena i duży „Zrób rolkę”.
// Asystent (/api/z-promptu/asystent: darmowy model OpenRouter albo reguły, 0 kr) wypełnia formularz „Zmień szczegóły”; pola,
// które user zmienił ręcznie (state.zp.reczne), zostają przy następnym dobieraniu. Potem DARMOWA wycena (/api/z-promptu/wycena);
// losowe drobiazgi wracają jako `ustalone` i lecą z powrotem przy „Zrób rolkę” – ten sam prompt, który wyceniono. Każda zmiana
// kasuje wycenę; „Zrób rolkę” bez świeżej ceny najpierw ją sprawdza, potem pyta „Zrobić za N kr?”.
state.zp = { katalog: null, slug: null, pomyslId: null, ustalone: null, wycena: null, edytowany: false, liczy: false,
  asystent: null, reczne: {}, seq: 0, dobiera: false, timer: null };

async function ladujZPromptu() {
  const slug = state.aktywna;
  if (!state.zp.katalog || state.zp.slug !== slug) {
    state.zp.katalog = await api('/api/z-promptu?slug=' + encodeURIComponent(slug || ''));
    state.zp.slug = slug;
    state.zp.pomyslId = null; state.zp.reczne = {}; state.zp.asystent = null;
    renderZpFormularz();
    zpZmiana(true);
    renderZpAsystent();
  } else {
    renderZpPersony();
  }
  await ladujRolki(false);
}

function opcjeHtml(lista, wybrana) {
  return lista.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(wybrana) ? ' selected' : ''}>${esc(t)}</option>`).join('');
}

function renderZpPersony() {
  $('#zp-persona').innerHTML = state.modelki.map(m => `<option value="${esc(m.slug)}"${m.slug === state.aktywna ? ' selected' : ''}>${esc(m.nazwa || m.slug)}</option>`).join('');
}

function renderZpModel() {
  const k = state.zp.katalog;
  const m = (k.modele || []).find(x => x.id === $('#zp-model').value) || (k.modele || [])[0];
  if (!m) return;
  const dl = $('#zp-dlugosc').value || String((k.domyslne || {}).dlugosc || k.dlugosc_domyslna);
  $('#zp-dlugosc').innerHTML = opcjeHtml(m.dlugosci.map(s => [s, `${s} s`]), m.dlugosci.map(String).includes(String(dl)) ? dl : m.dlugosci[m.dlugosci.length > 1 ? 1 : 0]);
  const r = $('#zp-rozdz').value || 'auto';
  $('#zp-rozdz').innerHTML = opcjeHtml([['auto', `Automatycznie (≤${k.prog_1080p_s} s → 1080p, dłuższe → 720p)`]].concat(m.rozdzielczosci.map(x => [x, x])), m.rozdzielczosci.includes(r) ? r : 'auto');
  $('#zp-model-info').textContent = m.opis || '';
}

// Lista prawdziwych obiektów (galerie, dworce, dzielnice) dla wybranego miejsca.
function renderZpObiekt(wybrany = '') {
  const k = state.zp.katalog || {};
  const lista = (k.obiekty || {})[$('#zp-miejsce').value] || [];
  $('#zp-obiekt').innerHTML = lista.length
    ? opcjeHtml([['', 'Dowolna – dobierze asystent']].concat(lista), wybrany)
    : '<option value="">— to miejsce ma już swoją nazwę</option>';
  $('#zp-obiekt').disabled = !lista.length || $('#zp-nazwy').value === 'opisowe';
}

function renderZpFormularz() {
  const k = state.zp.katalog;
  const dom = k.domyslne || {};
  const per = k.persona || {};
  renderZpPersony();
  $('#zp-pomysl').value = ''; $('#zp-stroj-tekst').value = ''; $('#zp-komentarz-tekst').value = '';   // nowa persona = czysty formularz
  $('#zp-prompt').value = '';
  $('#zp-model').innerHTML = opcjeHtml((k.modele || []).map(m => [m.id, m.nazwa]), dom.model || k.model_domyslny);
  $('#zp-dlugosc').innerHTML = ''; $('#zp-rozdz').innerHTML = '';
  renderZpModel();
  $('#zp-gotowe').innerHTML = '<option value="">…wybierz gotowy pomysł</option>' + (k.pomysly || []).map(p => `<option value="${esc(p.id)}">${esc(p.pl)}</option>`).join('');
  const grupy = (k.kategorie || []).map(kat => `<optgroup label="${esc(kat)}">${(k.miejsca || []).filter(m => m.kat === kat).map(m => `<option value="${esc(m.id)}">${esc(m.nazwa)}</option>`).join('')}</optgroup>`).join('');
  $('#zp-miejsce').innerHTML = `<option value="">Dobierze asystent</option><option value="losowe">Losowe miejsce</option>${grupy}`;
  $('#zp-nazwy').innerHTML = opcjeHtml(k.nazwy || [], dom.nazwy || 'prawdziwe');
  renderZpObiekt();
  const odwazne = (k.stroje_odwazne || []).map(([v, t]) => `<option value="odwazny:${esc(v)}">${esc(t)}</option>`).join('');
  const tryby = (k.stroje || []).filter(([v]) => v !== 'wlasny');
  const pliki = (per.stroje || []).map(n => [`plik:${n}`, `Ze zdjęcia: ${n}`]);
  $('#zp-stroj').innerHTML = opcjeHtml(tryby.concat(pliki, [['wlasny', 'Własny opis']]), dom.stroj || 'odwazny')
    + (odwazne ? `<optgroup label="Odważne – przyciągają wzrok">${odwazne}</optgroup>` : '');
  $('#zp-reakcja').innerHTML = opcjeHtml((k.reakcje || []).map(([v, t]) => [v, v === 'losowa' ? 'Dobierze asystent' : t]), dom.reakcja || 'losowa');
  $('#zp-kamera').innerHTML = opcjeHtml([['auto', 'Z ukrycia – dobierz do miejsca']].concat(k.kamery || []), dom.kamera || 'auto');
  $('#zp-komentarz').innerHTML = opcjeHtml([['losowy', 'Dobierze asystent'], ['bez', 'Bez komentarza']].concat((k.komentarze || []).map(t => [t, `„${t}”`]), [['wlasny', 'Własny…']]), dom.komentarz || 'losowy');
  $('#zp-glos').innerHTML = opcjeHtml(k.glosy || [], dom.glos || 'auto');
  $('#zp-wymowa').innerHTML = opcjeHtml(k.wymowy || [], dom.wymowa || 'fonetyczna');
  $('#zp-wlosy-kolor').innerHTML = opcjeHtml(k.wlosy.kolory, 'wlasne');
  $('#zp-wlosy-fryzura').innerHTML = opcjeHtml(k.wlosy.fryzury, 'wlasna');
  $('#zp-wlosy-grzywka').innerHTML = opcjeHtml(k.wlosy.grzywki, 'wlasna');
  const sezonTeraz = (k.sezony || []).find(([v]) => v === k.sezon_teraz);
  $('#zp-sezon').innerHTML = opcjeHtml([['auto', `Jak teraz (${sezonTeraz ? sezonTeraz[1].toLowerCase() : 'wg daty'})`]].concat(k.sezony || []), 'auto');
  $('#zp-pora').innerHTML = opcjeHtml([['auto', 'Dobierz do miejsca']].concat(k.pory || []), 'auto');
  $('#zp-glos-id').value = k.glos_id || '';
  const tts = k.glos_tts || {};
  $('#zp-glos-info').textContent = tts.ok ? 'Komentarz dogra ElevenLabs po generacji – poprawna polska wymowa.'
    : `Komentarz mówi model wideo (pisownia ą/ę poprawiona). Żeby mówił ElevenLabs: wklej klucz sk_… w Ustawienia → Konta → ElevenLabs.`;
  let info = 'Domyślnie jej własne włosy ze zdjęć. Zmiana włosów nie zmienia twarzy.';
  if (!per.wzrost_cm) info += ` Wpisz wzrost (Ustawienia → Persona) – rolka będzie lepiej wyskalowana obok ludzi.`;
  $('#zp-wlosy-info').textContent = info;
  $('#zp-stroj-tekst').hidden = $('#zp-stroj').value !== 'wlasny';
  $('#zp-komentarz-tekst').hidden = $('#zp-komentarz').value !== 'wlasny';
  wstawIkony($('#strona-z-promptu'));
}

function ustawSelect(sel, wartosc) {
  const el = $(sel);
  if (!el || wartosc === undefined || wartosc === null) return false;
  if (Array.from(el.options).some(o => o.value === String(wartosc))) { el.value = String(wartosc); return true; }
  return false;
}

// Wybory asystenta -> formularz „Zmień szczegóły” (pól zmienionych ręcznie nie rusza).
function ustawZpZOpcji(o) {
  const r = state.zp.reczne;
  if (!r.model) ustawSelect('#zp-model', o.model);
  renderZpModel();
  if (!r.dlugosc) ustawSelect('#zp-dlugosc', o.dlugosc);
  if (!r.rozdzielczosc) ustawSelect('#zp-rozdz', o.rozdzielczosc || 'auto');
  if (!r.miejsce) ustawSelect('#zp-miejsce', o.miejsce);
  if (!r.nazwy) ustawSelect('#zp-nazwy', o.nazwy);
  renderZpObiekt(r.obiekt ? $('#zp-obiekt').value : (o.obiekt || ''));
  if (!r.stroj) ustawSelect('#zp-stroj', o.stroj);
  if (!r.reakcja) ustawSelect('#zp-reakcja', o.reakcja);
  if (!r.kamera) ustawSelect('#zp-kamera', o.kamera);
  if (!r.komentarz) {
    if (!ustawSelect('#zp-komentarz', o.komentarz)) { $('#zp-komentarz').value = 'wlasny'; $('#zp-komentarz-tekst').value = o.komentarz || ''; }
  }
  if (!r.glos) ustawSelect('#zp-glos', o.glos);
  if (!r.wymowa) ustawSelect('#zp-wymowa', o.wymowa);
  if (!r.wlosy && o.wlosy) { ustawSelect('#zp-wlosy-kolor', o.wlosy.kolor); ustawSelect('#zp-wlosy-fryzura', o.wlosy.fryzura); ustawSelect('#zp-wlosy-grzywka', o.wlosy.grzywka); }
  $('#zp-stroj-tekst').hidden = $('#zp-stroj').value !== 'wlasny';
  $('#zp-komentarz-tekst').hidden = $('#zp-komentarz').value !== 'wlasny';
}

function zbierzZp() {
  const o = {
    slug: state.aktywna, tekst: $('#zp-pomysl').value.trim(), pomysl_id: state.zp.pomyslId || '',
    miejsce: $('#zp-miejsce').value, obiekt: $('#zp-obiekt').value, nazwy: $('#zp-nazwy').value,
    model: $('#zp-model').value, dlugosc: Number($('#zp-dlugosc').value),
    rozdzielczosc: $('#zp-rozdz').value || 'auto', stroj: $('#zp-stroj').value, stroj_tekst: $('#zp-stroj-tekst').value.trim(),
    reakcja: $('#zp-reakcja').value, komentarz: $('#zp-komentarz').value, komentarz_tekst: $('#zp-komentarz-tekst').value.trim(),
    glos: $('#zp-glos').value, wymowa: $('#zp-wymowa').value,
    wlosy: { kolor: $('#zp-wlosy-kolor').value, fryzura: $('#zp-wlosy-fryzura').value, grzywka: $('#zp-wlosy-grzywka').value },
    sezon: $('#zp-sezon').value, pora: $('#zp-pora').value, kamera: $('#zp-kamera').value,
  };
  if (state.zp.ustalone) o.ustalone = state.zp.ustalone;
  const a = state.zp.asystent;
  if (a) o.asystent = { dlaczego: a.dlaczego || '', zrodlo: a.zrodlo || '', podsumowanie: zpPodsumowanie() };
  return o;
}

function tekstOpcji(sel) {
  const el = $(sel);
  const o = el && el.options[el.selectedIndex];
  return o ? o.textContent : '';
}

// Jedna linijka „co dobrano” – z tego, co JEST w formularzu (asystent + ręczne zmiany).
function zpPodsumowanie() {
  const miejsce = $('#zp-miejsce').value ? tekstOpcji('#zp-miejsce') : 'miejsce dobierze asystent';
  const obiekt = $('#zp-obiekt').value && !$('#zp-obiekt').disabled ? tekstOpcji('#zp-obiekt') : '';
  const kom = $('#zp-komentarz').value === 'wlasny' ? $('#zp-komentarz-tekst').value.trim() : ($('#zp-komentarz').value === 'bez' ? '' : ($('#zp-komentarz').value === 'losowy' ? '' : $('#zp-komentarz').value));
  const glos = $('#zp-glos').value === 'auto' ? (((state.zp.katalog || {}).glos_tts || {}).ok ? 'głos ElevenLabs' : 'mówi model') : ($('#zp-glos').value === 'tts' ? 'głos ElevenLabs' : 'mówi model');
  const czesci = [obiekt ? `${miejsce}: ${obiekt}` : miejsce, `strój: ${tekstOpcji('#zp-stroj')}`, `kamera: ${tekstOpcji('#zp-kamera').toLowerCase()}`,
    `reakcja: ${tekstOpcji('#zp-reakcja').toLowerCase()}`];
  if (kom) czesci.push(`„${kom}” (${glos})`);
  czesci.push(`${$('#zp-dlugosc').value} s · ${tekstOpcji('#zp-model').split(' –')[0]}`);
  return czesci.join(' · ');
}

function renderZpAsystent() {
  const a = state.zp.asystent;
  const el = $('#zp-asystent-tekst');
  if (state.zp.dobiera) { el.innerHTML = '<span class="kropka akcent pulsuje"></span> dobieram miejsce, strój, kamerę i reakcje…'; $('#zp-asystent-dlaczego').textContent = ''; return; }
  if (!a) { el.textContent = 'napisz pomysł albo kliknij „Losuj”.'; $('#zp-asystent-dlaczego').textContent = ''; return; }
  el.textContent = zpPodsumowanie();
  const reczne = Object.keys(state.zp.reczne).length;
  const zrodlo = (a.zrodlo || '').startsWith('openrouter') ? 'AI' : 'reguły';
  $('#zp-asystent-dlaczego').textContent = `Dlaczego: ${a.dlaczego || ''}` + (reczne ? ` (zmieniłeś ręcznie: ${reczne})` : '') + ` · ${zrodlo}` + (a.uwaga && state.pelny ? ` · ${a.uwaga}` : '');
}

// Asystent dobiera wszystko do pomysłu (0 kr), potem od razu darmowa wycena.
async function zpAsystent(zCena = true) {
  const tekst = $('#zp-pomysl').value.trim();
  if (!tekst && !state.zp.pomyslId) { state.zp.asystent = null; renderZpAsystent(); return; }
  const seq = ++state.zp.seq;
  state.zp.dobiera = true; renderZpAsystent(); renderZpPrzyciski();
  try {
    const r = await api('/api/z-promptu/asystent', 'POST', { slug: state.aktywna, tekst, pomysl_id: state.zp.pomyslId || '', zablokowane: state.zp.reczne });
    if (seq !== state.zp.seq) return;
    state.zp.asystent = r;
    if (r.glos_tts && state.zp.katalog) state.zp.katalog.glos_tts = r.glos_tts;
    ustawZpZOpcji(r.opcje || {});
    state.zp.dobiera = false;
    zpZmiana(true);
    renderZpAsystent();
    if (zCena) await zpPytaj(true);
  } catch (e) {
    if (seq === state.zp.seq) { state.zp.dobiera = false; renderZpAsystent(); bladToast(e); }
  } finally {
    if (seq === state.zp.seq) { state.zp.dobiera = false; renderZpPrzyciski(); }
  }
}

function zpAsystentPozniej() {
  clearTimeout(state.zp.timer);
  state.zp.timer = setTimeout(() => zpAsystent(true), 1100);
}

// Coś zmieniono -> stara wycena i ustalone losowe drobiazgi są nieaktualne.
function zpZmiana(cicho = false) {
  state.zp.ustalone = null; state.zp.wycena = null; state.zp.edytowany = false;
  $('#zp-prompt-wrap').hidden = true;
  $('#zp-uwagi').hidden = true;
  $('#zp-cena').textContent = cicho ? 'Cena pojawi się tutaj (sprawdzenie nic nie kosztuje).' : 'Zmieniłeś coś – „Zrób rolkę” najpierw sprawdzi cenę (nic nie kosztuje).';
  $('#zp-cena').className = 'zp-cena';
  if (state.zp.asystent && !state.zp.dobiera) renderZpAsystent();
  renderZpPrzyciski();
}

function renderZpPrzyciski() {
  const w = state.zp.wycena;
  const btn = $('#zp-btn-zrob');
  const jest = !!($('#zp-pomysl').value.trim() || state.zp.pomyslId);
  btn.disabled = state.zp.liczy || state.zp.dobiera || !jest || (w && !w.mozna);
  btn.textContent = w && w.kr ? `Zrób rolkę (${liczba(w.kr)} kr)` : (state.zp.liczy ? 'Sprawdzam cenę…' : 'Zrób rolkę');
  $('#zp-btn-cena').disabled = state.zp.liczy;
  $('#zp-btn-pokaz').disabled = state.zp.liczy;
}

function renderZpWynik(w, zCena) {
  if (w.ustalone) state.zp.ustalone = w.ustalone;
  $('#zp-prompt').value = w.prompt || '';
  $('#zp-prompt').readOnly = !state.pelny;
  $('#zp-znaki').textContent = liczba(w.znaki || 0);
  $('#zp-prompt-wrap').hidden = false;
  const uwagi = (state.pelny ? (w.ostrzezenia || []) : (w.ostrzezenia || []).filter(u => !/znakow \(zalecane/.test(u)))
    .concat(zCena ? (w.powody || []).map(p => `Nie da się teraz: ${p}`) : []);
  $('#zp-uwagi').innerHTML = uwagi.map(u => `<li>${esc(u)}</li>`).join('');
  $('#zp-uwagi').hidden = !uwagi.length;
  if (!zCena) {
    $('#zp-cena').innerHTML = '<span class="muted">Ceny jeszcze nie sprawdziłem – „Zrób rolkę” sprawdzi ją najpierw (nic nie kosztuje).</span>';
    $('#zp-cena').className = 'zp-cena';
    return;
  }
  state.zp.wycena = w;
  const d = w.dzis || {};
  const saldo = w.saldo !== null && w.saldo !== undefined ? ` Masz ${esc(liczba(w.saldo))} kr.` : '';
  const limit = d.limit ? ` Dziś wydane ${esc(liczba(d.wydano || 0))} z ${esc(liczba(d.limit))}.` : '';
  $('#zp-cena').innerHTML = w.kr
    ? `Cena: <b>${esc(liczba(w.kr))} kr</b> <span class="muted">(${esc(String(w.dlugosc))} s, ${esc(w.rozdzielczosc || '')}; sprawdzone w Higgsfield, nic nie zeszło).${limit}${saldo}</span>`
    : 'Nie udało się sprawdzić ceny – spróbuj jeszcze raz za chwilę.';
  $('#zp-cena').className = 'zp-cena ' + (w.mozna ? 'ok' : 'zle');
}

async function zpPytaj(zCena) {
  if (state.zp.liczy) return null;
  const o = zbierzZp();
  if (!o.tekst && !o.pomysl_id && !o.miejsce) { toast('Napisz krótko, co ma się dziać, albo kliknij „Losuj”.', 'uwaga'); return null; }
  state.zp.liczy = true; renderZpPrzyciski();
  if (zCena) { $('#zp-cena').innerHTML = '<span class="kropka akcent pulsuje"></span> Sprawdzam cenę w Higgsfield… (ok. 15 s, nic nie kosztuje)'; $('#zp-cena').className = 'zp-cena'; }
  try {
    const w = await api('/api/z-promptu/wycena', 'POST', Object.assign(o, { bez_ceny: !zCena }));
    renderZpWynik(w, zCena);
    if (!zCena) { $('#zp-szczegoly').open = true; $('#zp-prompt-wrap').open = true; }
    return w;
  } catch (e) {
    $('#zp-cena').textContent = prostyBlad(e);
    $('#zp-cena').className = 'zp-cena zle';
    bladToast(e);
    return null;
  } finally {
    state.zp.liczy = false; renderZpPrzyciski();
  }
}

async function zpLosuj() {
  const d = await api('/api/z-promptu/losuj', 'POST', { slug: state.aktywna, bez: state.zp.pomyslId || '', sezon: $('#zp-sezon').value });
  const p = d.pomysl || {};
  $('#zp-pomysl').value = p.pl || '';
  $('#zp-gotowe').value = p.id || '';
  state.zp.pomyslId = p.id || null;
  delete state.zp.reczne.miejsce;
  await zpAsystent(true);
}

async function zpZrob() {
  let w = state.zp.wycena;
  if (state.zadanie && state.zadanie.trwa) { toast('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 'uwaga'); return; }
  if (!w || !w.kr) w = await zpPytaj(true);                // bez świeżej ceny: najpierw darmowa wycena
  if (!w || !w.kr) return;
  if (!w.mozna) { toast('Tej rolki nie da się teraz zrobić – powód jest pod ceną.', 'uwaga'); return; }
  const d = w.dzis || {};
  const tresc = `<p><b>${esc(w.tytul || w.miejsce_nazwa || '')}</b></p>`
    + `<p class="muted">${esc(zpPodsumowanie())}</p>`
    + `<p>To będzie kosztować <b>${esc(liczba(w.kr))} kr</b> (Higgsfield, ${esc(String(w.dlugosc))} s, ${esc(w.rozdzielczosc || '')}).`
    + (w.saldo !== null && w.saldo !== undefined ? ` Po zrobieniu zostanie około <b>${esc(liczba(w.saldo - w.kr))} kr</b>.` : '') + '</p>'
    + (d.limit ? `<p>Dziś wydano ${esc(liczba(d.wydano || 0))} z ${esc(liczba(d.limit))} dozwolonych.</p>` : '')
    + '<p class="dialog-uwaga">To wyda kredyty. Jeśli tuż przed wysłaniem cena wyjdzie wyższa – nic nie wyślę.</p>';
  const ok = await potwierdz({ tytul: 'Zrobić tę rolkę?', tresc, ok: `Zrób (${liczba(w.kr)} kr)` });
  if (!ok) return;
  const o = zbierzZp();
  o.ustalone = state.zp.ustalone;
  o.kr = w.kr;
  if (state.pelny && state.zp.edytowany) o.prompt = $('#zp-prompt').value;
  try {
    const r = await api('/api/z-promptu', 'POST', o);
    state.konsola.start = null; state.konsola.trwalo = true;
    state.zadanie = Object.assign({ trwa: true, typ: 'generuj' }, r.zadanie || {});
    toast(`Robię rolkę #${r.id} – zobaczysz ją niżej i w Rolkach. Gotowa trafi do folderu „tu rolki zrobione”.`, 'info');
    if (state.pelny) otworzKonsole(true);
    startKonsoli(); renderKonsolaStan();
    state.zp.wycena = null; renderZpPrzyciski();
    $('#zp-cena').innerHTML = `Wysłane do zrobienia (rolka #${esc(String(r.id))}, ok. 6–8 min). Kolejna? Napisz nowy pomysł albo „Losuj”.`;
    $('#zp-cena').className = 'zp-cena';
    await ladujRolki(false);
  } catch (e) {
    bladToast(e);
    await ladujRolki(false).catch(() => {});
  }
}

// Ręczna zmiana w „Zmień szczegóły” – asystent jej nie nadpisze.
function zpRecznie(el) {
  const pole = el.dataset.zpPole;
  if (!pole) return;
  const v = pole === 'wlosy' ? { kolor: $('#zp-wlosy-kolor').value, fryzura: $('#zp-wlosy-fryzura').value, grzywka: $('#zp-wlosy-grzywka').value } : el.value;
  const domyslne = ['', 'auto', 'losowa', 'losowy'];
  if (pole !== 'wlosy' && domyslne.includes(v)) delete state.zp.reczne[pole];
  else state.zp.reczne[pole] = v;
}

async function zpZapiszGlosId() {
  const v = $('#zp-glos-id').value.trim();
  await api('/api/ustawienia', 'POST', { z_promptu_glos: v });
  if (state.zp.katalog) state.zp.katalog.glos_id = v;
  toast(v ? 'Zapisane – komentarz będzie mówił ten głos ElevenLabs.' : 'Zapisane – głos dobiorę sam z Twojego konta ElevenLabs.', 'ok');
}

async function ocenRolke(id, ocena) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  const nowa = p && p.ocena === ocena ? null : ocena;
  const d = await api(`/api/pomysly/${id}/ocena`, 'POST', { ocena: nowa });
  const i = state.pomysly.findIndex(x => Number(x.id) === id);
  if (i >= 0 && d.pomysl) state.pomysly[i] = d.pomysl;
  toast(nowa === 'dobra' ? 'Zapamiętane – asystent częściej dobierze coś podobnego.' : (nowa === 'slaba' ? 'Zapamiętane – asystent będzie tego unikał.' : 'Ocena cofnięta.'), 'ok');
  renderRolki();
}

function renderZpLista() {
  const kont = $('#zp-lista');
  if (!kont) return;
  const lista = state.pomysly.filter(p => p.wariant === 'prompt').sort((a, b) => b.id - a.id).slice(0, 12);
  kont.innerHTML = lista.length ? lista.map(kartaRolki).join('')
    : '<div class="pusto cicho"><b>Jeszcze nie ma rolek z promptu</b><span>Napisz krótko pomysł albo kliknij „Losuj”, a potem „Zrób rolkę”.</span></div>';
}

// ---------- Zdjęcia ----------
async function ladujZdjecia() {
  const s = state.stan || {};
  const u = s.ustawienia || {};
  $('#zdjecia-brak-modelu').hidden = !!u.zdjecia_model;
  $('#form-zdjecia').hidden = !u.zdjecia_model;
  $('#zdjecia-opis-modelu').textContent = `Każde zdjęcie kosztuje ok. 2 kredyty Higgsfield.${state.pelny && u.zdjecia_model ? ` Model: ${u.zdjecia_model}.` : ''}`;
  $('#zdjecia-dzis').textContent = `dziś zrobione: ${s.zdjecia_dzis !== undefined ? s.zdjecia_dzis : 0}${u.zdjecia_dziennie ? ` z ${u.zdjecia_dziennie} (autopilot)` : ''}`;
  const [d, ust] = await Promise.allSettled([api('/api/zdjecia'), state.ustawieniaPelne ? Promise.resolve(state.ustawieniaPelne) : api('/api/ustawienia')]);
  if (ust.status === 'fulfilled') { state.ustawieniaPelne = ust.value; state.stroje = ust.value.stroje || []; }
  renderStrojWybor();
  if (d.status === 'rejected') throw d.reason;
  state.zdjecia = d.value.zdjecia || [];
  renderZdjecia();
}

// Zdjęcia → „Strój”: Automatycznie (wg ustawienia zdjecia_stroje) / Bez stroju / Następny strój / konkretny plik ze stroje/.
function renderStrojWybor() {
  const sel = $('#zd-stroj');
  if (!sel) return;
  const u = (state.stan && state.stan.ustawienia) || {};
  const biez = sel.value;
  const auto = state.stroje.length && u.zdjecia_stroje !== false ? 'Automatycznie (co drugie zdjęcie w stroju)' : 'Automatycznie (bez stroju)';
  sel.innerHTML = `<option value="">${esc(auto)}</option><option value="bez">Bez stroju</option>`
    + (state.stroje.length ? '<option value="auto">Następny strój z listy</option>' + state.stroje.map(s => `<option value="${esc(s.nazwa)}">strój: ${esc(s.nazwa)}</option>`).join('') : '');
  if (biez && Array.from(sel.options).some(o => o.value === biez)) sel.value = biez;
  $('#zd-stroj-info').textContent = state.stroje.length
    ? `${state.stroje.length} ${odmiana(state.stroje.length, 'strój', 'stroje', 'strojów')} w folderze Stroje. Zdjęcie stroju leci do modelu jako ostatni obraz.`
    : 'Nie masz jeszcze zdjęć strojów – dodasz je w Ustawienia → Persona → Stroje.';
  renderStrojMini();
}

function renderStrojMini() {
  const sel = $('#zd-stroj'), img = $('#zd-stroj-mini');
  if (!sel || !img) return;
  const s = state.stroje.find(x => x.nazwa === sel.value);
  img.hidden = !s;
  if (s) { img.src = s.url || ''; img.alt = s.nazwa; img.title = s.nazwa; }
}

function renderZdjecia() {
  const kont = $('#zdjecia-galeria');
  const lista = state.zdjecia.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    const u = (state.stan && state.stan.ustawienia) || {};
    kont.innerHTML = `<div class="pusto" style="grid-column:1/-1"><span class="ikona">${ikona('zdjecia')}</span><b>Jeszcze nie ma zdjęć</b><span>${u.zdjecia_model ? 'Wpisz, jakie zdjęcie chcesz, i kliknij „Zrób zdjęcie”.' : 'Najpierw wybierz model zdjęć w Ustawieniach – potem kliknij „Zrób zdjęcie”.'} Autopilot też może robić zdjęcia sam – ustaw „Ile zdjęć dziennie” w <a href="#ustawienia/autopilot">Ustawienia → Autopilot</a>.</span>${u.zdjecia_model ? '<button class="btn btn-maly btn-glowny" type="button" data-akcja="fokus-zdjecia">Zrób pierwsze zdjęcie</button>' : '<a class="btn btn-maly btn-glowny" href="#ustawienia/zdjecia">Wybierz model zdjęć</a>'}</div>`;
    return;
  }
  kont.innerHTML = lista.map(z => `<figure class="zdjecie" data-id="${Number(z.id)}">
    ${z.url ? `<a href="${esc(z.url)}" target="_blank" rel="noopener"><img src="${esc(z.url)}" alt="" loading="lazy"></a>` : `<div class="brak-obrazu"><span class="ikona">${ikona('zdjecia')}</span></div>`}
    <figcaption class="zdjecie-tresc">
      <div class="zdjecie-stopka"><span class="status ${kolorStatusu(z.status)}"><span class="kropka ${kolorStatusu(z.status)}"></span>${esc(slowoStatusu(z.status, 'zdjecie'))}</span><span class="muted">${z.koszt !== null && z.koszt !== undefined ? esc(kredytow(z.koszt)) : ''}</span></div>
      <div class="zdjecie-prompt" title="${esc(z.prompt)}">${esc(z.prompt || '')}</div>
      ${z.stroj ? `<span class="zdjecie-stroj" title="${esc(z.stroj)}">${ikona('stroj')}<span>strój: ${esc(bezRozszerzenia(nazwaPliku(z.stroj)))}</span></span>` : ''}
      ${z.notatki ? `<div class="muted">${esc(state.pelny ? z.notatki : prostyBlad(z.notatki))}</div>` : ''}
      <div class="zdjecie-stopka"><span class="muted">${esc(formatCzas(z.utworzono))}${state.pelny ? ` · #${Number(z.id)}` : ''}</span><span class="rzad" style="gap:4px">${z.prompt ? `<button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(z.prompt)}" title="kopiuj opis">${ikona('kopiuj')}</button>` : ''}<button class="btn btn-maly btn-zly" type="button" data-akcja="usun-zdjecie" data-id="${Number(z.id)}">Usuń</button></span></div>
    </figcaption>
  </figure>`).join('');
}

async function zrobZdjecia() {
  const u = (state.stan && state.stan.ustawienia) || {};
  if (!u.zdjecia_model) { toast('Najpierw wybierz model zdjęć w Ustawienia → Zdjęcia.', 'uwaga'); return; }
  const ile = Math.max(1, Math.min(20, Number($('#zd-ile').value) || 1));
  const prompt = $('#zd-prompt').value.trim();
  const stroj = ($('#zd-stroj') && $('#zd-stroj').value) || '';
  const opisStroju = stroj === 'bez' ? 'Bez stroju.' : (stroj === 'auto' ? 'W następnym stroju z listy.' : (stroj ? `W stroju <b>${esc(stroj)}</b>.` : ''));
  const w = await potwierdz({
    tytul: `Zrobić ${ile} ${odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}?`,
    tresc: `<p>${prompt ? `Opis: „${esc(prompt)}”.` : 'Opis weźmie się po kolei z listy w Ustawienia → Zdjęcia.'} ${opisStroju}${state.pelny ? ` Model: <b>${esc(u.zdjecia_model)}</b>.` : ''}</p><p class="dialog-uwaga">To kosztuje kredyty.</p>`,
    ok: 'Zrób',
  });
  if (!w) return;
  const dane = { typ: 'zdjecia', ile };
  if (prompt) dane.prompt = prompt;
  if (stroj) dane.stroj = stroj;   // puste = automatycznie (wg ustawienia zdjecia_stroje)
  await akcja(dane, 'robię zdjęcia');
}

async function usunZdjecie(id) {
  const w = await potwierdz({ tytul: 'Usunąć to zdjęcie?', tresc: '', ok: 'Usuń', klasa: 'btn-zly', checkbox: 'Usuń też plik z dysku' });
  if (!w) return;
  await api(`/api/zdjecia/${id}${w.zaznaczone ? '?plik=1' : ''}`, 'DELETE');
  toast('Usunięto zdjęcie.', 'ok');
  await ladujZdjecia();
}

// ---------- Lipsync ----------
async function ladujLipsync() {
  const wyniki = await Promise.allSettled([api('/api/lipsync'), api('/api/pomysly'), api('/api/ustawienia')]);
  const [l, p, u] = wyniki.map(w => (w.status === 'fulfilled' ? w.value : null));
  if (l) state.lipsync = l.lipsync || [];
  if (p) { state.pomysly = p.pomysly || []; state.pomyslyJson = JSON.stringify(state.pomysly); }
  if (u) state.ustawieniaPelne = u;
  wyniki.forEach(w => { if (w.status === 'rejected') bladToast(w.reason); });
  renderLipsyncFormularz();
  renderLipsyncHistoria();

  const ust = (state.stan && state.stan.ustawienia) || {};
  // model: lista z sync.so, a gdy niedostępna – stała lista
  const sel = $('#ls-model');
  const biezacy = sel.value || ust.lipsync_model || 'lipsync-2';
  const lista = await pobierzListe('modele?dostawca=sync');
  const modele = lista.pozycje.length ? lista.pozycje.map(m => ({ id: m.id, nazwa: m.nazwa || m.id })) : MODELE_SYNC_ZAPAS.map(id => ({ id, nazwa: id }));
  sel.innerHTML = modele.map(m => `<option value="${esc(m.id)}">${esc(m.nazwa)}</option>`).join('');
  ustawSelectWartosc(sel, biezacy);
  $('#ls-model-info').textContent = lista.blad ? `Lista modeli niedostępna (${prostyBlad(lista.blad)}) – pokazuję domyślne.` : '';
  // głosy do czytania tekstu
  const gsel = $('#tts-glos'), gid = $('#tts-glos-id');
  const biezacyGlos = (gsel.hidden ? gid.value : gsel.value) || ust.tts_glos || '';
  const glosy = await pobierzListe('glosy?dostawca=sync');
  if (glosy.pozycje.length) {
    gsel.innerHTML = '<option value="">— wybierz głos —</option>' + glosy.pozycje.map(g => `<option value="${esc(g.id)}">${esc(g.nazwa || g.id)}${g.opis ? ' – ' + esc(g.opis) : ''}</option>`).join('');
    ustawSelectWartosc(gsel, biezacyGlos);
    gsel.hidden = false; gid.hidden = true;
    $('#tts-glos-info').textContent = '';
  } else {
    gsel.hidden = true; gid.hidden = false;
    if (!gid.value) gid.value = biezacyGlos;
    $('#tts-glos-info').textContent = glosy.blad ? `Nie mogę pobrać listy głosów: ${prostyBlad(glosy.blad)} Wpisz id głosu ręcznie.` : 'Lista głosów pusta – wpisz id głosu ręcznie.';
  }
}

function renderLipsyncFormularz() {
  const selW = $('#ls-wideo');
  const biezW = selW.value;
  const gotowe = state.pomysly.filter(p => p.wideo_url).slice().sort((a, b) => b.id - a.id);
  selW.innerHTML = (gotowe.length
    ? gotowe.map(p => `<option value="${Number(p.id)}">${esc(tytulRolki(p))} – ${esc(slowoStatusu(p.status))}</option>`).join('')
    : '<option value="">— nie ma jeszcze gotowych rolek —</option>')
    + '<option value="__inny">inny plik (wpisz ścieżkę)…</option>';
  selW.value = biezW && Array.from(selW.options).some(o => o.value === biezW) ? biezW : (gotowe[0] ? String(gotowe[0].id) : '');
  $('#ls-wideo-sciezka-wrap').hidden = selW.value !== '__inny';

  const selA = $('#ls-audio');
  const biezA = selA.value;
  const audio = (state.ustawieniaPelne && state.ustawieniaPelne.audio) || [];
  selA.innerHTML = (audio.length
    ? audio.map(a => `<option value="${esc(a.sciezka)}">${esc(a.nazwa)}</option>`).join('')
    : '<option value="">— brak nagrań: wrzuć plik albo napisz tekst —</option>')
    + '<option value="__inny">inny plik (wpisz ścieżkę)…</option>';
  selA.value = biezA && Array.from(selA.options).some(o => o.value === biezA) ? biezA : (audio[0] ? audio[0].sciezka : '');
  $('#ls-audio-sciezka-wrap').hidden = selA.value !== '__inny';

  const ust = (state.stan && state.stan.ustawienia) || {};
  const tryb = $('#ls-tryb');
  if (!tryb.dataset.ustawiony) { ustawSelectWartosc(tryb, (ust.lipsync_parametry || {}).sync_mode || 'bounce'); tryb.dataset.ustawiony = '1'; }
  // brzmienie głosu: domyślnie z ustawienia persony (lipsync_glos_styl), user może zmienić na jedno dopasowanie
  const styl = $('#ls-styl');
  if (styl && !styl.dataset.ustawiony) {
    const s = String(ust.lipsync_glos_styl || 'telefon');
    styl.value = ['telefon', 'czysty', 'brak'].includes(s) ? s : 'telefon';
    styl.dataset.ustawiony = '1';
  }
}

function renderLipsyncHistoria() {
  const kont = $('#lipsync-historia');
  const lista = state.lipsync.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    kont.innerHTML = '<div class="pusto cicho"><b>Jeszcze nic nie dopasowywałem</b><span>Wybierz rolkę i głos powyżej. Autopilot nie robi lipsyncu – usta dopasowujesz tutaj ręcznie (albo przy ręcznym „Zrób rolkę”, gdy obok filmiku leży <span class="mono">nazwa.audio.mp3</span> i włączysz to w Ustawienia → Autopilot).</span></div>';
    return;
  }
  kont.innerHTML = `<div class="tabela-wrap"><table class="tabela"><thead><tr><th>Kiedy</th><th>Rolka</th><th>Głos</th>${state.pelny ? '<th>Model</th>' : ''}<th>Stan</th><th>Koszt</th><th></th></tr></thead><tbody>${lista.map(l => `<tr>
    <td class="czas" title="${esc(formatData(l.utworzono))}">${esc(formatCzas(l.utworzono))}${state.pelny ? ` <small>#${Number(l.id)}</small>` : ''}</td>
    <td title="${esc(l.wideo)}">${esc(bezRozszerzenia(nazwaPliku(l.wideo)))}${l.pomysl_id ? ` <small class="muted">(rolka #${Number(l.pomysl_id)})</small>` : ''}</td>
    <td title="${esc(l.audio)}">${esc(nazwaPliku(l.audio))}</td>
    ${state.pelny ? `<td class="nowrap">${esc(l.dostawca || '')} ${esc(l.model || '')}</td>` : ''}
    <td><span class="status ${kolorStatusu(l.status)}"><span class="kropka ${kolorStatusu(l.status)}"></span>${esc(slowoStatusu(l.status, 'lipsync'))}</span>${l.notatki ? `<div class="muted" style="font-size:13px">${esc(state.pelny ? l.notatki : prostyBlad(l.notatki))}</div>` : ''}</td>
    <td class="nowrap">${l.koszt !== null && l.koszt !== undefined ? (l.dostawca === 'sync' ? `${esc(liczba(l.koszt))} c (USD)` : esc(kredytow(l.koszt))) : '—'}</td>
    <td class="akcje">${l.url ? `<a class="btn btn-maly" href="${esc(l.url)}" target="_blank" rel="noopener">${ikona('play')}Odtwórz</a> ` : ''}<button class="btn btn-maly btn-zly" type="button" data-akcja="usun-lipsync" data-id="${Number(l.id)}">Usuń</button></td>
  </tr>`).join('')}</tbody></table></div>`;
}

async function startLipsync() {
  const selW = $('#ls-wideo').value, selA = $('#ls-audio').value;
  const wideoId = selW && selW !== '__inny' ? Number(selW) : null;
  const wideoSciezka = selW === '__inny' ? $('#ls-wideo-sciezka').value.trim() : '';
  const audio = selA && selA !== '__inny' ? selA : $('#ls-audio-sciezka').value.trim();
  if (!wideoId && !wideoSciezka) { toast('Krok 1: wybierz gotową rolkę (albo wpisz ścieżkę do pliku).', 'uwaga'); return; }
  if (!audio) { toast('Krok 2: wybierz nagranie głosu, wrzuć plik albo napisz tekst.', 'uwaga'); return; }
  const p = wideoId ? state.pomysly.find(x => Number(x.id) === wideoId) : null;
  const dane = { typ: 'lipsync', audio };
  if (wideoId) dane.id = wideoId; else dane.wideo = wideoSciezka;
  const stylSel = $('#ls-styl');
  if (stylSel && stylSel.value) dane.styl = stylSel.value;
  const NAZWY_STYLU = { telefon: 'jak z telefonu w pokoju', czysty: 'czysty', brak: 'bez zmian' };
  let szczegoly = dane.styl ? `<br>Brzmienie głosu: <b>${esc(NAZWY_STYLU[dane.styl] || dane.styl)}</b>.` : '';
  if (state.pelny) {
    // `model` i `sync_mode` to pola dodatkowe akcji lipsync – w trybie prostym obowiązują ustawienia persony
    dane.model = $('#ls-model').value;
    dane.sync_mode = $('#ls-tryb').value;
    szczegoly = `<br>Model: <b>${esc(dane.model)}</b>, tryb ${esc(dane.sync_mode)}.`;
  }
  const w = await potwierdz({
    tytul: 'Dopasować usta do głosu?',
    tresc: `<p>Rolka: <b>${esc(p ? tytulRolki(p) : nazwaPliku(wideoSciezka))}</b><br>Głos: <b>${esc(nazwaPliku(audio))}</b>${szczegoly}</p><p class="dialog-uwaga">To wyda kredyty (sync.so liczy za sekundę filmu).</p>`,
    ok: 'Dopasuj',
  });
  if (!w) return;
  await akcja(dane, 'dopasowuję usta');
}

function nazwaGlosu(id) {
  const l = state.listy['glosy?dostawca=sync'];
  const g = l && l.pozycje.find(x => x.id === id);
  return g ? (g.nazwa || id) : id;
}

async function startTts() {
  const tekst = $('#tts-tekst').value.trim();
  if (!tekst) { toast('Napisz, co ma powiedzieć głos.', 'uwaga'); return; }
  const voice = ($('#tts-glos').hidden ? $('#tts-glos-id').value : $('#tts-glos').value).trim();
  if (!voice) { toast('Wybierz głos (albo wpisz jego id).', 'uwaga'); return; }
  const nazwa = $('#tts-nazwa').value.trim();
  const w = await potwierdz({
    tytul: 'Zrobić nagranie z tekstu?',
    tresc: `<p>${tekst.length} ${odmiana(tekst.length, 'znak', 'znaki', 'znaków')}, głos <b>${esc(nazwaGlosu(voice))}</b>${nazwa ? `, nagranie <b>${esc(nazwa)}.mp3</b>` : ''}.</p><p class="dialog-uwaga">To wyda kredyty (sync.so / ElevenLabs).</p>`,
    ok: 'Zrób głos',
  });
  if (!w) return;
  const dane = { typ: 'tts', tekst, voice_id: voice };
  if (nazwa) dane.nazwa = nazwa;
  if (await akcja(dane, 'robię głos z tekstu')) $('#tts-tekst').value = '';
}

async function otworzLipsyncDialog(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (!state.ustawieniaPelne) {
    try { state.ustawieniaPelne = await api('/api/ustawienia'); } catch (e) { state.ustawieniaPelne = { audio: [] }; }
  }
  const audio = state.ustawieniaPelne.audio || [];
  const sel = $('#ls-dlg-audio');
  let opcje = '<option value="">— wpisz ścieżkę poniżej —</option>';
  if (p && p.audio) opcje += `<option value="${esc(p.audio)}">głos tego filmiku: ${esc(p.audio_nazwa || nazwaPliku(p.audio))}</option>`;
  opcje += audio.map(a => `<option value="${esc(a.sciezka)}">${esc(a.nazwa)}</option>`).join('');
  sel.innerHTML = opcje;
  sel.value = p && p.audio ? p.audio : (audio[0] ? audio[0].sciezka : '');
  $('#ls-dlg-sciezka').hidden = !!sel.value;
  $('#ls-dlg-sciezka').value = '';
  $('#ls-dlg-id').value = String(id);
  $('#ls-dlg-tytul').textContent = `Dopasuj usta: ${p ? tytulRolki(p) : '#' + id}`;
  const stylDlg = $('#ls-dlg-styl');
  if (stylDlg) stylDlg.value = stylGlosuZUstawien();
  otworzDialog('#dlg-lipsync');
}

// Domyślne brzmienie głosu (ustawienie lipsync_glos_styl persony): telefon | czysty | brak
function stylGlosuZUstawien() {
  const u = (state.ustawieniaPelne && state.ustawieniaPelne.ustawienia) || {};
  const s = String(u.lipsync_glos_styl || 'telefon');
  return ['telefon', 'czysty', 'brak'].includes(s) ? s : 'telefon';
}

async function startLipsyncZDialogu() {
  const id = Number($('#ls-dlg-id').value);
  const audio = $('#ls-dlg-audio').value || $('#ls-dlg-sciezka').value.trim();
  if (!audio) { toast('Wybierz nagranie głosu albo wpisz ścieżkę do pliku.', 'uwaga'); return; }
  const stylDlg = $('#ls-dlg-styl');
  const dane = { typ: 'lipsync', id, audio };
  if (stylDlg && stylDlg.value) dane.styl = stylDlg.value;
  $('#dlg-lipsync').close();
  await akcja(dane, 'dopasowuję usta');
}

async function usunLipsync(id) {
  const w = await potwierdz({ tytul: 'Usunąć ten wpis z listy?', tresc: '<p>Zniknie tylko z listy – gotowy plik zostaje.</p>', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api(`/api/lipsync/${id}`, 'DELETE');
  toast('Usunięto.', 'ok');
  await ladujLipsync();
}

// ---------- Ustawienia: formularze ----------
function etykietaPola(el) {
  const l = el.id ? $(`label[for="${el.id}"]`) : null;
  return l ? l.textContent.trim() : el.name;
}

function zbierzFormularz(form) {
  const dane = {};
  Array.from(form.elements).forEach(el => {
    if (!el.name || el.disabled || el.type === 'submit' || el.type === 'button') return;
    let v;
    if (el.type === 'checkbox') v = el.checked;
    else if (el.type === 'radio') { if (!el.checked) return; v = el.value; }
    else if (el.dataset.typ === 'tri') v = el.value === '' ? null : el.value === 'true';
    else if (el.dataset.typ === 'usd') {
      // pole w dolarach (WaveSpeed) -> centy w ustawieniach/budżecie; puste = domyślne (data-domyslne w centach)
      const t = String(el.value).trim().replace(',', '.');
      const x = Number(t);
      v = t === '' ? (el.dataset.domyslne !== undefined ? Number(el.dataset.domyslne) : null) : (Number.isFinite(x) ? Math.max(0, Math.round(x * 100)) : null);
    } else if (el.dataset.typ === 'json') {
      const t = el.value.trim();
      if (!t) v = {};
      else {
        try { v = JSON.parse(t); } catch (e) { throw new Error(`Pole „${etykietaPola(el)}” musi być poprawnym JSON-em, np. {"seed": 42}.`); }
        if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error(`Pole „${etykietaPola(el)}” musi być słownikiem w klamrach {…}.`);
      }
    } else if (el.type === 'number') {
      if (el.value.trim() === '') v = el.dataset.domyslne !== undefined ? Number(el.dataset.domyslne) : null;
      else v = Number(el.value);
    } else v = el.value;
    ustawW(dane, el.name, v);
  });
  return dane;
}

function ustawSelectWartosc(sel, v) {
  v = v === null || v === undefined ? '' : String(v);
  if (!Array.from(sel.options).some(o => o.value === v)) {
    const o = document.createElement('option');
    o.value = v; o.textContent = v || '—';
    sel.appendChild(o);
  }
  sel.value = v;
}

// tylkoPodane=true: zmienia wyłącznie pola, których nazwy są w `dane` (reszta formularza zostaje, jak była)
function wypelnijFormularz(form, dane, tylkoPodane = false) {
  Array.from(form.elements).forEach(el => {
    if (!el.name || el.type === 'submit' || el.type === 'button') return;
    if (tylkoPodane && wartoscZ(dane, el.name) === undefined) return;
    const v = wartoscZ(dane, el.name);
    if (el.type === 'checkbox') el.checked = !!v;
    else if (el.type === 'radio') el.checked = String(el.value) === String(v === null || v === undefined ? '' : v);
    else if (el.dataset.typ === 'tri') el.value = v === null || v === undefined ? '' : String(v);
    else if (el.dataset.typ === 'usd') el.value = v === null || v === undefined || v === '' ? '' : (Number(v) / 100).toFixed(2);
    else if (el.dataset.typ === 'json') el.value = v && typeof v === 'object' && Object.keys(v).length ? JSON.stringify(v) : '';
    else if (el.dataset.typ === 'lista-json') ustawSelectWartosc(el, JSON.stringify(Array.isArray(v) ? v : []));   // zapas_nsfw
    else if (el.tagName === 'SELECT') ustawSelectWartosc(el, v);
    else if (v === null || v === undefined) el.value = '';
    else el.value = typeof v === 'object' ? JSON.stringify(v) : String(v);
  });
}

async function pobierzListe(zapytanie, odswiezLista = false) {
  // zapytanie np. "modele?dostawca=sync" -> GET /api/modele?dostawca=sync (cache 10 min po stronie panelu)
  const c = state.listy[zapytanie];
  if (c && !odswiezLista && Date.now() - c.czas < 10 * 60 * 1000) return c;
  let wynik;
  try {
    const d = await api('/api/' + zapytanie + (odswiezLista ? '&odswiez=1' : ''));
    wynik = { czas: Date.now(), pozycje: (d.modele || d.glosy || []).filter(p => p && p.id !== undefined), blad: null };
  } catch (e) {
    wynik = { czas: Date.now(), pozycje: [], blad: e.message };
  }
  state.listy[zapytanie] = wynik;
  return wynik;
}

// Select z listą z API + zapasowe pole tekstowe (gdy dostawca niezalogowany / brak klucza).
async function podlaczListe(select, zapytanie, odswiezLista = false) {
  const pole = select.parentElement;
  const zapas = pole.querySelector('[data-zapas]');
  const info = pole.querySelector('[data-lista-info]');
  const biezaca = select.disabled && zapas ? zapas.value : select.value;
  const l = await pobierzListe(zapytanie, odswiezLista);
  if (l.pozycje.length) {
    select.innerHTML = (select.dataset.pusta !== undefined ? `<option value="">${esc(select.dataset.pusta)}</option>` : '')
      + l.pozycje.map(p => `<option value="${esc(p.id)}">${esc(p.nazwa || p.id)}${p.opis ? ' – ' + esc(p.opis) : ''}</option>`).join('');
    ustawSelectWartosc(select, biezaca);
    select.hidden = false; select.disabled = false;
    if (zapas) { zapas.hidden = true; zapas.disabled = true; }
    if (info) info.textContent = '';
  } else {
    select.hidden = true; select.disabled = true;
    if (zapas) { zapas.hidden = false; zapas.disabled = false; if (!zapas.value) zapas.value = biezaca; }
    if (info) info.textContent = l.blad ? `Nie mogę pobrać listy: ${prostyBlad(l.blad)} Wpisz nazwę ręcznie.` : 'Lista jest pusta – wpisz nazwę ręcznie.';
  }
}

function przelaczDostawce() {
  const f = $('#form-generowanie');
  const wybrany = f.querySelector('input[name="dostawca"]:checked');
  const d = wybrany ? wybrany.value : 'higgsfield';
  $$('[data-dostawca-blok]', f).forEach(b => { b.hidden = b.dataset.dostawcaBlok !== d; });
}

function przelaczLipsyncDostawce(odswiezLista = false) {
  const d = $('#u-lipsync-dostawca').value;
  const sel = $('#u-lipsync-model');
  const zapas = sel.parentElement.querySelector('[data-zapas]');
  const info = sel.parentElement.querySelector('[data-lista-info]');
  if (d === 'higgsfield') {
    // modele lipsync Higgsfield wpisuje się ręcznie (job_type z CLI)
    if (!sel.disabled && sel.value) zapas.value = sel.value;
    sel.hidden = true; sel.disabled = true; zapas.hidden = false; zapas.disabled = false;
    info.textContent = 'Dla Higgsfield wpisz job_type modelu lipsync (z `higgsfield model list --video`).';
  } else {
    podlaczListe(sel, 'modele?dostawca=sync', odswiezLista);
  }
}

async function ladujUstawienia() {
  const d = await api('/api/ustawienia');
  state.ustawieniaPelne = d;
  const u = d.ustawienia || {};
  const pr = d.prompty || {};
  const dane = Object.assign({}, u, { prompt_a_tekst: pr.a || '', prompt_b_tekst: pr.b || '', zdjecia_prompty_tekst: pr.zdjecia || '' });
  renderStrojDomyslny(d);
  $$('#strona-ustawienia form[data-ustawienia]').forEach(f => wypelnijFormularz(f, dane));
  przelaczDostawce();
  renderReferencje(d);
  renderFoldery(d);
  renderPromptyInfo();
  renderJakosc();
  // profil przychodzi z /api/ustawienia (pole profil); po zapisie trzymamy świeższą kopię w state.profile
  if (d.profil && !state.profile[state.aktywna]) state.profile[state.aktywna] = d.profil;
  const prof = state.profile[state.aktywna] || d.profil || {};
  wypelnijFormularz($('#form-profil'), {
    nazwa: prof.nazwa || nazwaPersony(state.aktywna) || '', instagram: prof.instagram || '', opis_stylu: prof.opis_stylu || '',
    hashtagi: prof.hashtagi || '', wzrost_cm: prof.wzrost_cm || '', wlosy: prof.wlosy || '',
    cechy: Array.isArray(prof.cechy) ? prof.cechy.join(', ') : (prof.cechy || ''),
    telegram_czat: u.telegram_czat || '',   // ustawienie persony (nie profil) – zapis w zapiszProfil idzie do /api/ustawienia
  });
  renderStanKontaTelegram(u.telegram_czat);
  state.stroje = d.stroje || [];
  try {
    const b = await api('/api/budzet');
    state.budzet = b;
    const dzis = b.dzis || {};
    $('#limit-higgsfield').value = (dzis.higgsfield && dzis.higgsfield.limit !== undefined) ? dzis.higgsfield.limit : ((b.budzet || {}).max_kredyty_dziennie || 0);
    $('#limit-yapper').value = (dzis.yapper && dzis.yapper.limit !== undefined) ? dzis.yapper.limit : 0;
    // WaveSpeed: limit w centach USD, pole w dolarach
    $('#limit-wavespeed').value = ((Number((dzis.wavespeed || {}).limit) || 0) / 100).toFixed(2);
  } catch (e) { /* limity są dodatkiem */ }
  ladujKonta().catch(bladToast);
  ladujTeksty().catch(bladToast);
  // listy modeli/głosów dociągamy w tle
  podlaczListe($('#u-yapper-model'), 'modele?dostawca=yapper');
  podlaczListe($('#u-ws-model'), 'modele?dostawca=wavespeed');
  podlaczListe($('#u-zdjecia-model'), 'modele?dostawca=higgsfield&typ=image');
  podlaczListe($('#u-tts-glos'), 'glosy?dostawca=sync');
  przelaczLipsyncDostawce();
}

function miniaturka(p, typ, numer) {
  return `<div class="miniaturka"><img src="${esc(p.url)}" alt="${esc(p.nazwa)}" loading="lazy">${numer ? `<span class="numer">${esc(numer)}</span>` : ''}<button class="btn btn-ikona btn-maly usun" type="button" data-akcja="usun-plik" data-typ="${esc(typ)}" data-nazwa="${esc(p.nazwa)}" title="Usuń ${esc(p.nazwa)}" aria-label="Usuń ${esc(p.nazwa)}">${ikona('kosz')}</button><div class="nazwa" title="${esc(p.nazwa)}">${esc(p.nazwa)}</div></div>`;
}

function renderReferencje(d) {
  const refs = d.referencje || [], stroje = d.stroje || [];
  $('#referencje-licznik').textContent = refs.length
    ? `${refs.length} ${odmiana(refs.length, 'zdjęcie', 'zdjęcia', 'zdjęć')} → @[Image 1] … @[Image ${refs.length}]`
    : 'Brak zdjęć – dodaj twarz i sylwetkę persony (2–6 zdjęć).';
  $('#referencje-lista').innerHTML = refs.map((r, i) => miniaturka(r, 'referencja', `@Image ${i + 1}`)).join('');
  $('#stroje-licznik').textContent = stroje.length ? `${stroje.length} ${odmiana(stroje.length, 'strój', 'stroje', 'strojów')}` : 'Brak strojów (nie są konieczne).';
  $('#stroje-lista').innerHTML = stroje.map(s => miniaturka(s, 'stroj', '')).join('');
}

function renderStrojDomyslny(d) {
  const sel = $('#u-stroj');
  const biez = sel.value;
  sel.innerHTML = '<option value="">— brak (strój z filmu, wariant A) —</option>' + (d.stroje || []).map(s => `<option value="stroje/${esc(s.nazwa)}">${esc(s.nazwa)}</option>`).join('');
  if (biez) ustawSelectWartosc(sel, biez);
}

// Ustawienia → Foldery: ścieżki teraz używane + „Otwórz” (Eksplorator) i „kopiuj”; nagrania głosu i folder programu tylko w pełnym.
function renderFoldery(d) {
  const f = d.foldery || {};
  const wiersze = [['Tu wrzucasz filmiki', f.wrzutnia, 'wrzutnia'], ['Tu odbierasz gotowe rolki', f.gotowe, 'gotowe'], ['Tu lądują zdjęcia persony', f.zdjecia, 'zdjecia'],
    ['Nagrania głosu (lipsync)', f.audio, null, true], ['Folder persony w programie', f.modelka, null, true]].filter(w => w[1]);
  $('#foldery-efektywne').innerHTML = wiersze.map(([n, s, co, zaaw]) => `<div class="folder-wiersz"${zaaw ? ' data-zaawansowane' : ''}><span class="etykieta">${esc(n)}</span><span class="sciezka">${esc(s)}</span><span class="folder-przyciski">${co ? `<button class="btn btn-maly" type="button" data-akcja="otworz-folder" data-co="${esc(co)}">${ikona('folder')}Otwórz</button>` : ''}<button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(s)}" title="kopiuj ścieżkę" aria-label="kopiuj ścieżkę">${ikona('kopiuj')}</button></span></div>`).join('');
}

// Ustawienia → „Jakość i koszt”: trzy karty-zestawy z /api/stan.jakosc.presety; klik -> POST /api/ustawienia/preset.
function renderJakosc() {
  const kont = $('#jakosc-karty');
  if (!kont) return;
  const j = state.jakosc;
  if (!j) { kont.innerHTML = '<div class="muted">Sprawdzam ustawienia…</div>'; kont.dataset.klucz = ''; $('#jakosc-ostrzezenie').hidden = true; return; }
  const presety = j.presety || {};
  // przerysowujemy tylko przy zmianie danych (nie porównujemy HTML – przeglądarka serializuje SVG inaczej, więc karta traciłaby fokus co 5 s)
  const klucz = JSON.stringify([j.preset, j.resolution, j.max_sekund_rolki, j.koszt_rolki, j.za_drogo, j.max_kredyty_na_rolke, j.jednostka, presety]);
  // persona na WaveSpeed: kwoty w dolarach (jakosc.jednostka 'c'), Higgsfield – kredyty
  const ok = v => esc(kwotaKrotko(v, j.jednostka));
  if (kont.dataset.klucz !== klucz) {
    kont.dataset.klucz = klucz;
    const karty = Object.keys(PRESETY_JAKOSCI).filter(k => presety[k]).map(k => {
      const p = presety[k], o = PRESETY_JAKOSCI[k], aktywna = j.preset === k;
      return `<button type="button" class="jakosc-karta${aktywna ? ' aktywna' : ''}" role="radio" aria-checked="${aktywna ? 'true' : 'false'}" data-akcja="jakosc-preset" data-preset="${esc(k)}">
        <span class="jakosc-nazwa">${esc(o.nazwa)}<span class="ikona">${ikona('ok')}</span></span>
        <span class="jakosc-opis">${esc(o.opis)}</span>
        <span class="jakosc-koszt"><b>ok. ${ok(p.koszt_rolki)}</b> <small>za rolkę · ${esc(p.resolution)}, do ${esc(p.max_sekund_rolki)}&nbsp;s</small></span>
      </button>`;
    });
    if (j.preset === 'wlasne') {
      karty.push(`<div class="jakosc-karta wlasne aktywna" role="radio" aria-checked="true" aria-disabled="true">
        <span class="jakosc-nazwa">Własne ustawienia<span class="ikona">${ikona('ok')}</span></span>
        <span class="jakosc-opis">${esc(j.resolution || '?')}, rolki do ${esc(j.max_sekund_rolki || '?')}&nbsp;s – ustawione ręcznie w „Jak robić rolki” (tryb pełny). Kliknij zestaw obok, żeby wrócić do gotowego.</span>
        <span class="jakosc-koszt"><b>ok. ${ok(j.koszt_rolki)}</b> <small>za rolkę</small></span>
      </div>`);
    }
    kont.innerHTML = karty.join('');
  }
  const ostrz = $('#jakosc-ostrzezenie');
  ostrz.hidden = !j.za_drogo;
  if (j.za_drogo) {
    $('#jakosc-ostrzezenie-tekst').innerHTML = `Ta rolka (ok. <b>${ok(j.koszt_rolki)}</b>) przekracza Twój limit na jedną rolkę (<b>${ok(j.max_kredyty_na_rolke)}</b>) – fabryka ją pominie. Wybierz <b>Normalnie</b> albo podnieś limit w trybie pełnym (<a href="#ustawienia/limity">Limity kredytów</a>).`;
  }
}

async function ustawPresetJakosci(nazwa, btn) {
  if (!nazwa || (state.jakosc && state.jakosc.preset === nazwa)) return;
  if (btn) btn.disabled = true;
  try {
    const d = await api('/api/ustawienia/preset', 'POST', { nazwa });
    if (d.jakosc) state.jakosc = d.jakosc;
    if (d.ustawienia) {
      // zestaw ustawia resolution (Higgsfield); pole „Rozdzielczość” obiecuje tę samą jakość u yapper – dosyłamy yapper.resolution
      const yr = (d.ustawienia.yapper || {}).resolution;
      if (d.ustawienia.resolution && yr !== d.ustawienia.resolution) {
        try {
          const dy = await api('/api/ustawienia', 'POST', { yapper: { resolution: d.ustawienia.resolution } });
          if (dy.ustawienia) d.ustawienia = dy.ustawienia;
        } catch (e) { console.warn('yapper.resolution nie zapisane:', e.message); }
      }
      if (state.ustawieniaPelne) state.ustawieniaPelne.ustawienia = d.ustawienia;
      if (state.stan) state.stan.ustawienia = d.ustawienia;
      // pola „Rozdzielczość” i „Długość rolki” w „Jak robić rolki” pokazują to samo, co zestaw
      const f = $('#form-generowanie');
      if (f) wypelnijFormularz(f, { resolution: d.ustawienia.resolution, max_sekund_rolki: d.ustawienia.max_sekund_rolki }, true);
    }
    renderJakosc();
    const j = state.jakosc || {};
    toast(`Zestaw „${nazwaPresetu(nazwa)}”: jedna rolka to ok. ${kwotaKrotko(j.koszt_rolki, j.jednostka)}.`, 'ok');
    odswiez();
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderPromptyInfo() {
  const refs = ((state.ustawieniaPelne && state.ustawieniaPelne.referencje) || []).length;
  const licz = t => (t.match(/@\[Image\s*\d+\]/gi) || []).length;
  const a = licz($('#u-prompt-a').value), b = licz($('#u-prompt-b').value);
  const el = $('#prompty-info'), txt = $('#prompty-info-tekst');
  const czesci = [`Zdjęć persony: ${refs}.`];
  czesci.push(a === refs ? `Prompt A ma ${a} × @Image ✓` : `Prompt A ma ${a} × @Image, a powinien ${refs} (tyle, ile zdjęć).`);
  if (b || refs) czesci.push(b === 0 ? 'Prompt B jest pusty (wariant „strój ze zdjęcia” wyłączony).' : (b === refs + 1 ? `Prompt B ma ${b} × @Image ✓` : `Prompt B ma ${b} × @Image, a powinien ${refs + 1} (zdjęcia + strój).`));
  txt.textContent = czesci.join(' ');
  el.className = 'callout ' + ((a === refs && (b === 0 || b === refs + 1)) ? 'info' : 'uwaga');
}

async function zapiszUstawienia(f) {
  const dane = zbierzFormularz(f);
  const btn = f.querySelector('button[type="submit"]');
  if (btn) btn.disabled = true;
  try {
    if (f.id === 'form-generowanie') {
      // „Rozdzielczość” -> resolution (Higgsfield) i yapper.resolution (ta sama jakość u obu dostawców)
      if (dane.resolution) ustawW(dane, 'yapper.resolution', dane.resolution);
      if (dane.max_sekund_rolki !== null && dane.max_sekund_rolki !== undefined) {
        const wpisane = Number(dane.max_sekund_rolki);
        dane.max_sekund_rolki = Math.max(4, Math.min(30, wpisane || 15));
        // przycięte do 4–30 s: pole pokazuje to, co naprawdę się zapisze, i mówimy o tym wprost
        const pole = f.elements.max_sekund_rolki;
        if (pole && String(pole.value).trim() !== '' && wpisane !== dane.max_sekund_rolki) {
          pole.value = dane.max_sekund_rolki;
          toast(`Długość rolki przycięta do ${dane.max_sekund_rolki} s (dozwolone 4–30 s).`, 'uwaga');
        }
      }
    }
    if (dane.budzet) {
      // limity dzienne to osobny plik (budzet.json), wspólny dla wszystkich person
      for (const [dost, v] of Object.entries(dane.budzet)) {
        state.budzet = await api('/api/budzet', 'POST', { dostawca: dost, max_kredyty_dziennie: Math.max(0, Number(v) || 0) });
      }
      delete dane.budzet;
      if (state.kontaPelne) renderKonta();      // karta WaveSpeed pokazuje dzienny limit
    }
    const d = await api('/api/ustawienia', 'POST', dane);
    if (d.ustawienia) {
      if (state.ustawieniaPelne) state.ustawieniaPelne.ustawienia = d.ustawienia;
      if (state.stan) state.stan.ustawienia = d.ustawienia;
      // to samo ustawienie może być w dwóch formularzach (np. zdjecia_dziennie) – odświeżamy pozostałe, żeby nie nadpisały go starą wartością
      const wspolne = {};
      Object.keys(dane).forEach(k => { if (!k.includes('.') && d.ustawienia[k] !== undefined) wspolne[k] = d.ustawienia[k]; });
      $$('#strona-ustawienia form[data-ustawienia]').forEach(inny => { if (inny !== f) wypelnijFormularz(inny, wspolne, true); });
      // ten formularz też dostaje wartości z serwera (np. max_sekund_rolki przycięte po stronie backendu)
      if (f.id === 'form-generowanie') wypelnijFormularz(f, { resolution: d.ustawienia.resolution, max_sekund_rolki: d.ustawienia.max_sekund_rolki }, true);
    }
    if (f.id === 'form-prompty' && state.ustawieniaPelne) {
      state.ustawieniaPelne.prompty = Object.assign({}, state.ustawieniaPelne.prompty, { a: dane.prompt_a_tekst, b: dane.prompt_b_tekst });
      renderPromptyInfo();
    }
    if (f.id === 'form-zdjecia-ust' && state.ustawieniaPelne) {
      state.ustawieniaPelne.prompty = Object.assign({}, state.ustawieniaPelne.prompty, { zdjecia: dane.zdjecia_prompty_tekst });
    }
    toast('Zapisane.', 'ok');
    odswiezDiagnoze();
    odswiez();
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Pod polem „Konto Telegram tej persony”: czy to konto już napisało /start do bota (lista sparowanych czatów z /api/stan).
function renderStanKontaTelegram(v) {
  const el = $('#p-telegram-stan');
  if (!el) return;
  const konto = kontoTelegram(v);
  const t = state.telegram || {};
  if (!konto) { el.textContent = t.sparowany ? `Rolki tej persony lecą na Twój główny czat${t.czat ? ` (${t.czat})` : ''}.` : ''; el.className = 'pole-info'; return; }
  const czaty = Array.isArray(t.czaty) ? t.czaty : [];
  const jest = czaty.some(c => kontoTelegram(c.nazwa).toLowerCase() === konto.toLowerCase());
  if (!t.skonfigurowany) { el.textContent = 'Bot Telegram nie jest jeszcze podłączony – wklej token w Ustawienia → Konta.'; el.className = 'pole-info zle'; }
  else if (jest) { el.textContent = `${konto} jest sparowane z botem ✓ – gotowe rolki tej persony polecą tam.`; el.className = 'pole-info ok'; }
  else { el.textContent = `${konto} nie napisało jeszcze /start do bota – gotowe rolki poczekają (dostaniesz o tym wiadomość na główny czat) i polecą tam, gdy to konto napisze /start.`; el.className = 'pole-info zle'; }
}

async function zapiszProfil(f) {
  const dane = zbierzFormularz(f);
  const znany = !!state.profile[state.aktywna];   // profil znamy tylko po zapisie w tej sesji (API nie ma GET profilu)
  const payload = { nazwa: dane.nazwa || '' };
  for (const k of ['instagram', 'opis_stylu', 'cechy', 'hashtagi', 'wzrost_cm', 'wlosy']) {
    const v = String(dane[k] === undefined || dane[k] === null ? '' : dane[k]).trim();
    if (v || znany) payload[k] = v;   // puste pole kasuje wartość tylko wtedy, gdy ją widzieliśmy – inaczej zostawiamy to, co zapisane
  }
  const d = await api('/api/profil', 'POST', payload);
  if (d.profil) state.profile[state.aktywna] = d.profil;
  // konto Telegram persony to ustawienie (telegram_czat), nie profil
  const czat = String(dane.telegram_czat || '').trim();
  const u = (state.stan && state.stan.ustawienia) || {};
  if (czat !== String(u.telegram_czat || '')) {
    const du = await api('/api/ustawienia', 'POST', { telegram_czat: czat });
    if (du.ustawienia) {
      if (state.ustawieniaPelne) state.ustawieniaPelne.ustawienia = du.ustawienia;
      if (state.stan) state.stan.ustawienia = du.ustawienia;
    }
  }
  renderStanKontaTelegram(czat);
  toast('Zapisane.', 'ok');
  odswiezDiagnoze();
  odswiez();
}

async function usunPlik(typ, nazwa) {
  const etykiety = { referencja: 'zdjęcie persony', stroj: 'zdjęcie stroju', audio: 'nagranie' };
  const w = await potwierdz({ tytul: `Usunąć ${etykiety[typ] || 'plik'} „${nazwa}”?`, tresc: typ === 'referencja' ? '<p>Numery @Image pozostałych zdjęć się nie zmienią – sprawdź potem prompt.</p>' : '', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api('/api/pliki/usun', 'POST', { typ, nazwa });
  toast(`Usunięto ${nazwa}.`, 'ok');
  if (state.strona === 'ustawienia') await ladujUstawienia();
  else if (state.strona === 'lipsync') { state.ustawieniaPelne = null; await ladujLipsync(); }
  if (typ === 'referencja') odswiezDiagnoze();
  odswiez();
}

async function odswiezListy() {
  state.listy = {};
  if (state.strona === 'ustawienia') {
    podlaczListe($('#u-yapper-model'), 'modele?dostawca=yapper', true);
    podlaczListe($('#u-ws-model'), 'modele?dostawca=wavespeed', true);
    podlaczListe($('#u-zdjecia-model'), 'modele?dostawca=higgsfield&typ=image', true);
    podlaczListe($('#u-tts-glos'), 'glosy?dostawca=sync', true);
    przelaczLipsyncDostawce(true);
  } else if (state.strona === 'lipsync') {
    await ladujLipsync();
  }
  toast('Odświeżam listy modeli i głosów…', 'info');
}

// ---------- Ustawienia: Konta ----------
async function ladujKonta() {
  const d = await api('/api/konta');
  state.kontaPelne = d.konta || {};
  renderKonta();
}

function renderKonta() {
  const k = state.kontaPelne || {};
  const kolejnosc = ['higgsfield', 'telegram', 'wavespeed', 'yapper', 'sync', 'elevenlabs'];
  const ids = kolejnosc.filter(x => k[x]).concat(Object.keys(k).filter(x => !kolejnosc.includes(x)));
  $('#konta-lista').innerHTML = ids.length ? ids.map(id => kartaKonta(id, k[id])).join('') : '<div class="pusto"><b>Brak danych o kontach</b></div>';
}

const OPISY_KONT = {
  higgsfield: 'Robi rolki i zdjęcia. Logowanie przez przeglądarkę, bez klucza.',
  yapper: 'Zapasowy sposób robienia rolek (Wan 3.0). Potrzebne tylko, jeśli wybierzesz go w „Jak robić rolki”.',
  wavespeed: 'Tańsze rolki w 1080p (Seedance 2.5 Edit Turbo, 10 s ≈ $2,60). Płacisz dolarami z doładowania. Potrzebne, jeśli wybierzesz WaveSpeed w „Jak robić rolki” albo jako zapas po NSFW.',
  sync: 'Dopasowanie ust do głosu (lipsync) i głos z tekstu.',
  elevenlabs: 'Opcjonalnie: głos z tekstu.',
  telegram: 'Wysyłasz botowi filmik → fabryka robi rolkę → bot odsyła gotową z podpisem. Komendy: /status, /raport, /stop, /wznow.',
};

function prostyWynikTestu(w, id = '') {
  if (!w) return '';
  if (!w.dziala) return prostyBlad(w.komunikat || 'nie działa');
  if (id === 'telegram') {
    // komunikat bota jest już po ludzku („bot @x, sparowany z czatem …”) – tylko polskie znaki
    const k = String(w.komunikat || '').replace('wyslalem testowa wiadomosc', 'wysłałem testową wiadomość na telefon')
      .replace('dziala - napisz do niego /start na telefonie, zeby sparowac', 'działa – teraz napisz do niego /start na telefonie');
    return `Działa. ${k}`.trim();
  }
  const dol = String(w.komunikat || '').match(/\$(\d+)\.(\d\d)/);
  if (dol) return `Działa. Na koncie $${dol[1]},${dol[2]}.` + (/doladuj/i.test(w.komunikat || '') ? ' Doładuj konto (wavespeed.ai → Billing), żeby robić rolki.' : '');
  const m = String(w.komunikat || '').match(/(\d+)\s*kr/);
  return 'Działa.' + (m ? ` Masz ${kredytow(m[1])}.` : '');
}

// Karta WaveSpeed w Kontach: dzienny limit (centy USD z /api/budzet) – bez niego fabryka nic tam nie wyda.
function limitWaveSpeedHtml() {
  const b = (state.budzet && state.budzet.dzis && state.budzet.dzis.wavespeed) || null;
  if (!b) return '';
  return b.limit
    ? `<div class="konto-czaty">Dzienny limit: <b>${esc(usd(b.limit))}</b> (dziś wydane ${esc(usd(b.wydano || 0))}). Zmienisz go w <a href="#ustawienia/limity">Ustawienia → Limity</a> (tryb pełny).</div>`
    : `<div class="konto-powod">Dzienny limit WaveSpeed nie jest ustawiony – bez niego fabryka nic tu nie wyda. Ustaw go w <a href="#ustawienia/limity">Ustawienia → Limity</a> (tryb pełny – przełącznik w lewym dolnym rogu).</div>`;
}

function kartaKonta(id, k) {
  k = k || {};
  const nazwa = id === 'telegram' ? 'Telefon (Telegram)' : (k.nazwa || id);
  const wynik = state.testyKont[id];
  const wynikHtml = `<span class="konto-wynik ${wynik ? (wynik.dziala ? 'ok' : 'blad') : ''}" data-test-wynik="${esc(id)}">${wynik ? esc(state.pelny ? wynik.komunikat : prostyWynikTestu(wynik, id)) : ''}</span>`;
  let stanKlasa, stanTekst, srodek;
  if (id === 'telegram') {
    // telefon jako pilot: token bota (klucz „telegram”) + parowanie przez /start
    if (k.sparowany) { stanKlasa = 'ok'; stanTekst = `Sparowany z: ${k.czat || 'telefon'}`; }
    else if (k.jest) { stanKlasa = 'uwaga'; stanTekst = 'Token jest. Teraz na telefonie napisz do swojego bota: /start'; }
    else { stanKlasa = ''; stanTekst = 'nie podłączony'; }
    // wszystkie konta, które napisały /start do bota (główny czat + konta person z ustawienia telegram_czat)
    const czaty = Array.isArray((state.telegram || {}).czaty) ? state.telegram.czaty : [];
    const sparowane = czaty.length
      ? `<div class="konto-czaty">sparowane konta: ${czaty.map(c => `<b>${esc(kontoTelegram(c.nazwa) || c.nazwa)}</b>${c.glowny ? ' (główny)' : ''}`).join(', ')}.<br>Osobne konto dla persony wpisujesz w <a href="#ustawienia/persona">Persona → Konto Telegram</a> – też musi raz napisać /start.</div>`
      : '';
    srodek = `${k.ok === false && k.komunikat ? `<div class="konto-powod">${esc(prostyBlad(k.komunikat))}</div>` : ''}${sparowane}
      <ol class="kroki-lista">
        <li>W Telegramie napisz do <b>@BotFather</b>: <span class="mono">/newbot</span>, nadaj nazwę – dostaniesz <b>token</b>.</li>
        <li>Wklej token poniżej i kliknij <b>Zapisz</b>.</li>
        <li>Na telefonie napisz do swojego bota: <span class="mono">/start</span>. Od tej chwili wysyłasz mu filmiki, a on odsyła gotowe rolki.</li>
      </ol>
      <div class="konto-jak" data-zaawansowane>${linkuj(k.jak || '')}${k.komunikat ? `\n${esc(k.komunikat)}` : ''}</div>
      ${k.jest ? `<div class="konto-maska" data-zaawansowane>token: ${esc(k.maska || '••••')}${k.z_env ? ' (ze zmiennej środowiskowej)' : ''}</div>` : ''}
      <form class="rzad" data-konto-form="telegram"><input type="password" name="klucz" placeholder="${k.jest ? 'wklej nowy token, żeby podmienić' : 'wklej token bota (od @BotFather)'}" autocomplete="off" aria-label="Token bota Telegram"><button class="btn btn-glowny" type="submit">Zapisz</button></form>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="telegram"${k.jest ? '' : ' disabled'}>Testuj</button>${k.jest && !k.z_env ? '<button class="btn btn-maly btn-zly" type="button" data-akcja="konto-usun" data-dostawca="telegram">Usuń token</button>' : ''}${wynikHtml}</div>`;
  } else if (k.typ === 'oauth') {
    stanKlasa = k.ok ? 'ok' : 'blad';
    stanTekst = k.ok ? 'połączone' : 'nie połączone';
    srodek = `${!k.ok && k.komunikat ? `<div class="konto-powod">${esc(prostyBlad(k.komunikat))}</div>` : ''}
      <ol class="kroki-lista"><li>Kliknij dwa razy w plik <b>zaloguj-higgsfield.bat</b> (leży w folderze programu).</li><li>Zaloguj się w przeglądarce, która się otworzy, i wróć tutaj.</li></ol>
      <div class="konto-jak" data-zaawansowane>${linkuj(k.jak || '')}${k.komunikat ? `\n${esc(k.komunikat)}` : ''}</div>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="${esc(id)}">Sprawdź połączenie</button>${wynikHtml}</div>`;
  } else {
    if (k.ok === true) { stanKlasa = 'ok'; stanTekst = 'połączone'; }
    else if (k.ok === false) { stanKlasa = 'blad'; stanTekst = 'klucz nie działa'; }
    else if (k.jest) { stanKlasa = 'uwaga'; stanTekst = 'klucz zapisany, jeszcze nie sprawdzony'; }
    else { stanKlasa = ''; stanTekst = 'nie połączone'; }
    srodek = `${k.ok === false && k.komunikat ? `<div class="konto-powod">${esc(prostyBlad(k.komunikat))}</div>` : ''}
      <ol class="kroki-lista"><li>Wejdź na stronę ${esc(nazwa)} i utwórz klucz API: <span class="konto-jak">${linkuj(k.jak || '')}</span></li><li>Wklej klucz poniżej, kliknij <b>Zapisz</b>, potem <b>Sprawdź</b>.</li></ol>
      ${id === 'wavespeed' ? limitWaveSpeedHtml() : ''}
      ${k.jest ? `<div class="konto-maska" data-zaawansowane>klucz: ${esc(k.maska || '••••')}${k.z_env ? ' (ze zmiennej środowiskowej)' : ''}</div>` : ''}
      <form class="rzad" data-konto-form="${esc(id)}"><input type="password" name="klucz" placeholder="${k.jest ? 'wklej nowy klucz, żeby podmienić' : 'wklej klucz API'}" autocomplete="off" aria-label="Klucz API ${esc(nazwa)}"><button class="btn btn-glowny" type="submit">Zapisz</button></form>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="${esc(id)}"${k.jest ? '' : ' disabled'}>Sprawdź</button>${k.jest && !k.z_env ? `<button class="btn btn-maly btn-zly" type="button" data-akcja="konto-usun" data-dostawca="${esc(id)}">Usuń klucz</button>` : ''}${wynikHtml}</div>`;
  }
  const opis = OPISY_KONT[id] || k.opis || '';
  // tryb prosty: Higgsfield, telefon i sync.so (klucz do lipsyncu – user go wkleja); yapper i ElevenLabs tylko w pełnym
  const zaawansowane = ['yapper', 'elevenlabs'].includes(id);
  return `<div class="karta konto" data-konto="${esc(id)}"${zaawansowane ? ' data-zaawansowane' : ''}>
    <div class="karta-naglowek"><div><h2>${esc(nazwa)}</h2>${opis ? `<p>${esc(opis)}</p>` : ''}</div></div>
    <div class="konto-stan ${stanKlasa}"><span class="kropka ${stanKlasa}"></span>${esc(stanTekst)}</div>
    ${srodek}
  </div>`;
}

async function zapiszKlucz(dostawca, klucz) {
  if (!klucz) { toast('Wklej klucz.', 'uwaga'); return; }
  const d = await api('/api/konta', 'POST', { dostawca, klucz });
  state.kontaPelne = d.konta || state.kontaPelne;
  delete state.testyKont[dostawca];
  toast('Klucz zapisany. Kliknij „Sprawdź”, żeby zobaczyć, czy działa.', 'ok');
  renderKonta();
  odswiezDiagnoze();
  odswiez();
}

async function usunKlucz(dostawca) {
  const telefon = dostawca === 'telegram';
  const w = await potwierdz({
    tytul: telefon ? 'Usunąć token bota?' : 'Usunąć klucz?',
    tresc: telefon ? '<p>Telefon przestanie dostawać rolki, dopóki nie wkleisz nowego tokena.</p>' : '<p>Ten serwis przestanie działać, dopóki nie wkleisz nowego klucza.</p>',
    ok: 'Usuń', klasa: 'btn-zly',
  });
  if (!w) return;
  const d = await api('/api/konta', 'POST', { dostawca, klucz: '' });
  state.kontaPelne = d.konta || state.kontaPelne;
  delete state.testyKont[dostawca];
  toast(telefon ? 'Token usunięty.' : 'Klucz usunięty.', 'ok');
  renderKonta();
  odswiezDiagnoze();
  odswiez();
}

async function testujKonto(dostawca, btn) {
  if (btn) btn.disabled = true;
  const el = $(`[data-test-wynik="${dostawca}"]`);
  if (el) { el.textContent = 'sprawdzam…'; el.className = 'konto-wynik'; }
  try {
    const d = await api('/api/konta/test', 'POST', { dostawca });
    state.testyKont[dostawca] = { dziala: !!d.dziala, komunikat: d.komunikat || (d.dziala ? 'działa' : 'nie działa') };
    const nazwa = dostawca === 'telegram' ? 'Telefon (Telegram)' : ((state.kontaPelne && state.kontaPelne[dostawca] && state.kontaPelne[dostawca].nazwa) || dostawca);
    toast(`${nazwa}: ${prostyWynikTestu(state.testyKont[dostawca], dostawca)}`, d.dziala ? 'ok' : 'uwaga');
  } catch (e) {
    state.testyKont[dostawca] = { dziala: false, komunikat: e.message };
    bladToast(e);
  } finally {
    if (btn) btn.disabled = false;
    try { await ladujKonta(); } catch (e) { renderKonta(); }
    odswiezDiagnoze();
    odswiez(true);
  }
}

// ---------- Ustawienia: Teksty ----------
async function ladujTeksty() {
  const [t, s] = await Promise.all([api('/api/teksty'), api('/api/szablony')]);
  state.teksty = t.teksty || [];
  state.szablony = s.szablony || [];
  renderTeksty();
}

function renderTeksty() {
  const lista = state.teksty.slice().reverse();
  $('#teksty-info').textContent = `${state.teksty.length} ${odmiana(state.teksty.length, 'podpis', 'podpisy', 'podpisów')} w banku`;
  $('#teksty-lista').innerHTML = lista.length
    ? lista.map(t => `<div class="tekst-wiersz"><span>${esc(t.tekst)}</span>${t.zrodlo ? `<small>${esc(t.zrodlo)}</small>` : ''}<button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(t.tekst)}" title="kopiuj">${ikona('kopiuj')}</button></div>`).join('')
    : '<div class="pusto cicho"><b>Bank jest pusty</b><span>Wklej podpisy powyżej – fabryka dobierze je do gotowych rolek.</span></div>';
  $('#szablony-lista').innerHTML = state.szablony.length
    ? state.szablony.map(s => `<div class="szablon"><div class="gora"><b>${esc(s.nazwa)}</b><span class="rzad" style="gap:4px"><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(s.tresc)}" title="kopiuj">${ikona('kopiuj')}</button><button class="btn btn-maly btn-zly" type="button" data-akcja="usun-szablon" data-nazwa="${esc(s.nazwa)}">Usuń</button></span></div><div class="tresc">${esc(s.tresc)}</div>${(s.placeholdery || []).length ? `<div class="muted" style="font-size:13px">pola: ${s.placeholdery.map(p => `<span class="mono">{${esc(p)}}</span>`).join(', ')}</div>` : ''}</div>`).join('')
    : '<div class="pusto cicho"><b>Brak szablonów</b><span>Szablon to prompt z polami w klamrach do szybkiego wypełniania.</span></div>';
}

async function dodajTeksty() {
  const pole = $('#teksty-pole');
  if (!pole.value.trim()) { toast('Wklej podpisy.', 'uwaga'); return; }
  const d = await api('/api/teksty', 'POST', { teksty: pole.value, zrodlo: $('#teksty-zrodlo').value.trim() });
  pole.value = '';
  toast(`Dodano ${d.dodano} ${odmiana(d.dodano, 'podpis', 'podpisy', 'podpisów')} (powtórki pominięte).`, 'ok');
  await ladujTeksty();
}

async function losujTekst() {
  const d = await api('/api/teksty/losuj', 'POST', {});
  const w = $('#wylosowany');
  if (d.tekst) {
    w.hidden = false; w.textContent = d.tekst;
    $('#teksty-info').textContent = `zostało ${d.nieuzyte} nieużytych z ${d.wszystkie}`;
    await kopiuj(d.tekst);
  } else {
    w.hidden = true;
    toast('Wszystkie podpisy już użyte – dodaj nowe do banku.', 'uwaga');
  }
}

async function dodajSzablon() {
  const nazwa = $('#szablon-nazwa').value.trim(), tresc = $('#szablon-tresc').value.trim();
  if (!nazwa || !tresc) { toast('Podaj nazwę i treść szablonu.', 'uwaga'); return; }
  await api('/api/szablony', 'POST', { nazwa, tresc });
  $('#szablon-nazwa').value = ''; $('#szablon-tresc').value = '';
  toast('Szablon zapisany.', 'ok');
  await ladujTeksty();
}

async function usunSzablon(nazwa) {
  const w = await potwierdz({ tytul: `Usunąć szablon „${nazwa}”?`, tresc: '', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api('/api/szablony/' + encodeURIComponent(nazwa), 'DELETE');
  toast('Szablon usunięty.', 'ok');
  await ladujTeksty();
}

// ---------- Historia ----------
async function ladujHistoria() {
  ladujStatystyki(!state.timery.dziennik).catch(() => {});   // karta „Ostatnie 14 dni” nad listą
  const q = new URLSearchParams({ ile: '200' });
  if (state.pelny) { const typ = $('#dz-typ').value; if (typ) q.set('typ', typ); }
  const d = await api('/api/dziennik?' + q.toString());
  state.dziennik = d.wpisy || [];
  renderHistoria();
  if (!state.timery.dziennik && state.strona === 'historia') {
    state.timery.dziennik = setInterval(() => { ladujHistoria().catch(() => {}); }, 10000);
  }
}

function daneDziennika(d) {
  if (!d || typeof d !== 'object') return '';
  return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`).join(', ');
}

function renderHistoria() {
  // tryb prosty: lista zdań + dwa filtry
  const problemy = state.historiaFiltr === 'problemy';
  const jestProblem = w => w.typ === 'blad' || w.typ === 'uwaga';
  $('#historia-filtry').innerHTML = [['wszystko', 'wszystko', state.dziennik.length], ['problemy', 'tylko problemy', state.dziennik.filter(jestProblem).length]]
    .map(([id, nazwa, n]) => `<button type="button" class="chip${state.historiaFiltr === id ? ' aktywny' : ''}" data-akcja="historia-filtr" data-filtr="${id}">${nazwa} <span class="n">${n}</span></button>`).join('');
  renderWpisy($('#historia-lista'), state.dziennik.filter(w => !problemy || jestProblem(w)).slice().reverse(), problemy ? 'Żadnych problemów.' : 'Jeszcze nic się nie wydarzyło.');
  // tryb pełny: tabela z filtrami typ / persona
  const sel = $('#dz-modelka');
  const biez = sel.value;
  const opcje = '<option value="">wszystkie persony</option>' + state.modelki.map(m => `<option value="${esc(m.slug)}">${esc(m.nazwa || m.slug)}</option>`).join('');
  if (sel.innerHTML !== opcje) { sel.innerHTML = opcje; sel.value = biez; }
  const modelka = sel.value;
  // filtr persony po stronie panelu (API przyjmuje tylko ile/typ); wpisy bez persony są wspólne, więc zostają
  const wpisy = state.dziennik.filter(w => !modelka || !w.modelka || w.modelka === modelka).slice().reverse();
  $('#historia-tabela').innerHTML = wpisy.length
    ? wpisy.map(w => `<tr><td class="czas" title="${esc(formatData(w.czas))}">${esc(formatCzas(w.czas))}</td><td class="typ"><span class="rzad" style="gap:6px;flex-wrap:nowrap"><span class="kropka ${esc(w.typ || 'info')}"></span>${esc(w.typ === 'blad' ? 'błąd' : (w.typ || ''))}</span></td><td class="nowrap">${esc(w.modelka || '')}</td><td>${esc(w.tekst)}${w.dane ? ` <small class="muted">${esc(daneDziennika(w.dane))}</small>` : ''}</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">Brak wpisów.</td></tr>';
}

// ============================================================ 8. DIALOGI, UPLOAD, ZADANIA, ŁAŃCUCH „ZRÓB ROLKI”
function otworzDialog(sel) {
  const d = $(sel);
  if (d && !d.open) d.showModal();
}

// Generyczne potwierdzenie. Zwraca null (anulowano) albo {zaznaczone: bool}.
function potwierdz({ tytul, tresc = '', ok = 'OK', klasa = 'btn-glowny', checkbox = null }) {
  return new Promise(resolve => {
    const dlg = $('#dlg-potwierdz');
    $('#potw-tytul').textContent = tytul;
    $('#potw-tresc').innerHTML = tresc; // treść budują wywołujący – dane użytkownika już przeszły przez esc()
    const wrap = $('#potw-checkbox-wrap');
    wrap.hidden = !checkbox;
    if (checkbox) { $('#potw-checkbox-label').textContent = checkbox; $('#potw-checkbox').checked = false; }
    const btn = $('#potw-ok');
    btn.textContent = ok;
    btn.className = 'btn ' + klasa;
    const naZamkniecie = () => {
      dlg.removeEventListener('close', naZamkniecie);
      resolve(dlg.returnValue === 'ok' ? { zaznaczone: $('#potw-checkbox').checked } : null);
    };
    dlg.addEventListener('close', naZamkniecie);
    dlg.returnValue = '';
    dlg.showModal();
    btn.focus();
  });
}

async function kopiuj(tekst) {
  if (!tekst) return;
  try {
    await navigator.clipboard.writeText(tekst);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = tekst; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e2) { /* nic */ }
    ta.remove();
  }
  toast('Skopiowane. Wklej tam, gdzie chcesz (Ctrl+V).', 'info');
}

// Uruchamia zadanie w tle (POST /api/akcja) i włącza śledzenie logu. `cicho` = bez toastu (kroki łańcucha).
async function akcja(dane, opis, cicho = false) {
  try {
    const d = await api('/api/akcja', 'POST', dane);
    state.konsola.start = null;    // następny odczyt logu zacznie od zera
    state.konsola.trwalo = true;   // zadanie wystartowało – nawet gdy skończy się przed pierwszym odczytem
    state.zadanie = Object.assign({ trwa: true, typ: dane.typ }, d.zadanie || {});
    if (!cicho) {
      toast(`Zaczynam: ${opis || CO_ROBIE[dane.typ] || dane.typ}.`, 'info');
      if (state.pelny) otworzKonsole(true);
    }
    startKonsoli();
    renderKonsolaStan();
    if (state.strona === 'start') renderKrok2();
    return true;
  } catch (e) {
    bladToast(e);
    return false;
  }
}

// Jak akcja(), ale czeka na koniec zadania i zwraca jego końcowy stan {typ, wynik, blad, …} (null, gdy nie wystartowało).
async function akcjaCzekaj(dane, opis, cicho = false) {
  const ok = await akcja(dane, opis, cicho);
  if (!ok) return null;
  return czekajNaZadanie();
}

// Krok 2 na Starcie: sprawdź filmiki -> policz koszt -> zapytaj -> zrób rolki. Jedno kliknięcie, jedno pytanie o kredyty.
async function zrobRolki() {
  if (state.zadanie && state.zadanie.trwa) { toast('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 'uwaga'); return; }
  const L = state.lancuch;
  if (L.trwa) return;
  L.trwa = true; L.stop = false; L.ids = null; L.etap = 'skanuj';
  ustawWynikKroku('', '');
  try {
    // 1. sprawdź nowe filmiki
    const sk = await akcjaCzekaj({ typ: 'skanuj' }, 'sprawdzam nowe filmiki', true);
    if (!sk) return;
    if (sk.blad) { ustawWynikKroku(`Nie wyszło: ${prostyBlad(sk.blad)}`, 'zle'); return; }
    if (L.stop) { ustawWynikKroku('Zatrzymano.', 'uwaga'); return; }
    const d = await api('/api/stan');
    const s = d.stan || {};
    const ids = (s.do_generacji || []).map(Number);
    if (!ids.length) {
      const bezP = (s.bez_promptu || []).length;
      ustawWynikKroku(bezP
        ? `${bezP} ${odmiana(bezP, 'filmik nie ma', 'filmiki nie mają', 'filmików nie ma')} promptu – wpisz go w Rolki (więcej → Wpisz prompt) albo włącz „Sam wpisuj prompt” w Ustawieniach.`
        : 'Nie ma nic do zrobienia. Wrzuć filmiki (krok 1) i kliknij jeszcze raz.', 'uwaga');
      return;
    }
    L.ids = ids; L.etap = 'koszt';
    // 2. policz koszt
    const k = await akcjaCzekaj({ typ: 'koszt', ids }, 'liczę koszt', true);
    if (!k) return;
    if (L.stop) { ustawWynikKroku('Zatrzymano.', 'uwaga'); return; }
    let razem = null, nieznane = ids.length;
    if (!k.blad && k.wynik && typeof k.wynik === 'object') {
      const poz = Array.isArray(k.wynik.pozycje) ? k.wynik.pozycje : [];
      nieznane = poz.length ? poz.filter(x => !x || x[1] === null || x[1] === undefined).length : ids.length;
      if (poz.length && nieznane < poz.length) razem = Number(k.wynik.razem) || 0;
    }
    // 3. zapytaj
    L.etap = 'pytanie';
    renderKrok2();
    const w = await potwierdz({
      tytul: `Robić ${ids.length === 1 ? 'rolkę' : 'rolki'}?`,
      tresc: trescKosztu(razem, ids.length, razem === null ? 0 : nieznane) + (k.blad ? `<p class="dialog-uwaga">${esc(prostyBlad(k.blad))}</p>` : ''),
      ok: ids.length === 1 ? 'Rób' : `Rób (${ids.length})`,
    });
    if (!w) { ustawWynikKroku('Nic nie zrobiłem – anulowano.', ''); return; }
    L.etap = 'generuj';
    // 4. zrób rolki
    const g = await akcjaCzekaj({ typ: 'generuj', ids }, 'robię rolki');
    if (!g) return;
    if (g.blad) ustawWynikKroku(`Nie wyszło: ${prostyBlad(g.blad)}`, 'zle');
    else {
      const zrob = Number(g.wynik && g.wynik.wygenerowane) || 0;
      ustawWynikKroku(`${zrob ? 'Gotowe' : 'Koniec'}: ${prostyWynik('generuj', g.wynik)}.${zrob ? ' Odbierz je w kroku 3.' : ''}`, zrob ? 'ok' : 'uwaga');
    }
  } catch (e) {
    ustawWynikKroku(`Nie wyszło: ${prostyBlad(e)}`, 'zle');
  } finally {
    L.trwa = false; L.etap = ''; L.ids = null;
    renderKrok2();
  }
}

async function wyslijPliki(typ, pliki) {
  pliki = Array.from(pliki || []);
  if (!pliki.length) return;
  const fd = new FormData();
  fd.append('typ', typ);
  pliki.forEach(f => fd.append('pliki', f, f.name));
  toast(`Wysyłam ${pliki.length} ${odmiana(pliki.length, 'plik', 'pliki', 'plików')}…`, 'info');
  try {
    const d = await api('/api/upload', 'POST', fd);
    const zapisane = d.zapisane || [], pominiete = d.pominiete || [];
    const n = zapisane.length;
    if (pominiete.length) toast(`Pominięte (zły rodzaj pliku): ${pominiete.join(', ')}`, 'uwaga');
    if (typ === 'zrodlo') {
      if (n) toast(`Zapisano ${n} ${odmiana(n, 'filmik', 'filmiki', 'filmików')}. Teraz kliknij „Zrób rolki”.`, 'ok', { akcja: 'Zrób rolki', cb: () => { if (state.strona !== 'start') location.hash = '#start'; zrobRolki(); } });
    } else if (n) {
      toast(`Zapisano: ${zapisane.join(', ')}`, 'ok');
    }
    if ((typ === 'referencja' || typ === 'stroj') && state.strona === 'ustawienia') ladujUstawienia().catch(bladToast);
    if (typ === 'audio') { state.ustawieniaPelne = null; if (state.strona === 'lipsync') ladujLipsync().catch(bladToast); }
    if (typ === 'referencja') odswiezDiagnoze();
    odswiez();
  } catch (e) {
    bladToast(e);
  }
}

function wybierzPliki(typ) {
  const inp = $('#plik-ukryty');
  state.uploadTyp = typ;
  inp.accept = AKCEPT[typ] || '';
  inp.value = '';
  inp.click();
}

async function nowaPersona() {
  const nazwa = $('#np-nazwa').value.trim();
  if (!nazwa) { toast('Wpisz nazwę persony.', 'uwaga'); return; }
  await api('/api/modelki', 'POST', { nazwa, instagram: $('#np-ig').value.trim() });
  $('#dlg-persona').close();
  toast(`Jest persona „${nazwa}”. Teraz dodaj jej zdjęcia i prompt.`, 'ok');
  wyczyscCachePersony();
  odswiezDiagnoze();
  await odswiez();
  if (location.hash === '#ustawienia/persona') { state.sekcja = 'persona'; ladujStrone('ustawienia'); otworzSekcje('persona'); }
  else location.hash = '#ustawienia/persona';
}

async function zmienPersone(slug) {
  if (!slug || slug === state.aktywna) return;
  await api('/api/modelki/aktywna', 'POST', { slug });
  wyczyscCachePersony();
  await odswiez();
  if (state.stan) ladujStrone(state.strona);
}

function zamknijMenu(poza) {
  $$('details.menu[open]').forEach(m => { if (!poza || !m.contains(poza)) m.open = false; });
}

// ============================================================ 9. ZDARZENIA
document.addEventListener('click', async e => {
  const wMenu = e.target.closest('details.menu');
  zamknijMenu(wMenu);   // klik poza menu „więcej” zamyka otwarte menu
  const el = e.target.closest('[data-akcja]');
  if (!el) return;
  const nazwa = el.dataset.akcja;
  const id = el.dataset.id !== undefined ? Number(el.dataset.id) : null;
  if (wMenu && el.closest('.menu-lista')) wMenu.open = false;
  try {
    switch (nazwa) {
      case 'nowa-persona': $('#np-nazwa').value = ''; $('#np-ig').value = ''; otworzDialog('#dlg-persona'); $('#np-nazwa').focus(); break;
      case 'zamknij-dialog': { const d = el.closest('dialog'); if (d) d.close(); break; }
      case 'odswiez-saldo': el.disabled = true; try { await odswiez(true); toast('Kredyty sprawdzone.', 'info'); } finally { el.disabled = false; } break;
      case 'konsola-przelacz': otworzKonsole(!state.konsola.otwarta); break;
      case 'stop': state.lancuch.stop = true; await api('/api/zadanie/stop', 'POST', {}); toast('Zatrzymuję – dokończę tylko to, co już się robi.', 'uwaga'); break;
      case 'kopiuj': await kopiuj(el.dataset.tekst !== undefined ? el.dataset.tekst : (el.dataset.cel ? $(el.dataset.cel).textContent : '')); break;
      // start
      case 'zrob-rolki': await zrobRolki(); break;
      case 'skanuj': await akcja({ typ: 'skanuj' }, 'sprawdzam nowe filmiki'); break;
      case 'koszt': await policzKosztWszystkich(); break;
      case 'autopilot-raz': await akcja({ typ: 'autopilot_raz' }, 'przebieg autopilota'); break;
      case 'autopilot-wznow': await wznowAutopilot(el); break;
      case 'telegram-wyslij': await wyslijNaTelefon(id); break;
      case 'fokus-wrzuc': wybierzPliki('zrodlo'); break;
      case 'otworz-folder': el.disabled = true; try { await otworzFolder(el.dataset.co, el.dataset.slug); } finally { el.disabled = false; } break;
      case 'zamknij-panel': await zamknijPanel(); break;
      case 'persona-wybierz': await zmienPersone(el.dataset.slug); break;
      case 'pk-persona': {
        // „Uzupełnij” przy personie z listy kontrolnej: przełącz na nią i otwórz właściwą sekcję Ustawień
        const slug = el.dataset.slug, hash = el.dataset.hash || '#ustawienia/persona';
        if (slug && slug !== state.aktywna) await zmienPersone(slug);
        if (location.hash === hash) zastosujHash(); else location.hash = hash;
        break;
      }
      case 'kroki-przelacz': state.pkOtwarte = $('#pk-lista').hidden; renderPierwszeKroki(); break;
      // rolki
      case 'filtr': state.filtr = el.dataset.filtr || 'wszystkie'; renderRolki(); break;
      case 'koszt-pomysl': await akcja({ typ: 'koszt', ids: [id] }, 'liczę koszt'); break;
      case 'generuj-pomysl': await generujPomysl(id); break;
      case 'ponow': await ponowPomysl(id); break;
      case 'odtworz': if (state.odtwarzane.has(id)) state.odtwarzane.delete(id); else state.odtwarzane.add(id); if (state.strona === 'start') renderOdbierz(); else renderRolki(); break;
      case 'podglad': await taniPodglad(id); break;
      case 'podglad-pokaz': if (state.podglady.has(id)) state.podglady.delete(id); else state.podglady.add(id); renderRolki(); break;
      case 'prompt-pokaz': if (state.otwartePrompty.has(id)) state.otwartePrompty.delete(id); else state.otwartePrompty.add(id); renderRolki(); { const ta = $(`textarea[data-prompt="${id}"]`); if (ta) ta.focus(); } break;
      case 'pierz': await akcja({ typ: 'pierz', id }, 'pranie w Media Tool'); break;
      case 'lipsync-pomysl': await otworzLipsyncDialog(id); break;
      case 'podpis': await akcja({ typ: 'podpis', id }, 'dobieram podpis'); break;
      case 'usun-pomysl': await usunPomysl(id); break;
      case 'przerwij-pomysl': await przerwijPomysl(id); break;
      case 'zapisz-prompt': await zapiszPrompt(id); break;
      // z promptu
      case 'zp-losuj': await zpLosuj(); break;
      case 'zp-pokaz': if (state.zp.ustalone && !$('#zp-prompt-wrap').hidden) { const d = $('#zp-prompt-wrap'); d.open = !d.open; } else await zpPytaj(false); break;
      case 'zp-losuj-szczegoly': zpZmiana(); await zpPytaj(true); break;
      case 'zp-cena': await zpPytaj(true); break;
      case 'zp-zrob': await zpZrob(); break;
      case 'zp-dobierz': await zpAsystent(true); break;
      case 'zp-przywroc': state.zp.reczne = {}; await zpAsystent(true); break;
      case 'ocena': await ocenRolke(id, el.dataset.ocena); break;
      case 'dograj-glos': await akcja({ typ: 'dograj_glos', id }, 'dogrywam komentarz'); break;
      // zdjęcia, lipsync
      case 'fokus-zdjecia': { const inp = $('#zd-prompt'); if (inp) { inp.scrollIntoView({ behavior: 'smooth', block: 'center' }); inp.focus(); } break; }
      case 'usun-zdjecie': await usunZdjecie(id); break;
      case 'usun-lipsync': await usunLipsync(id); break;
      case 'tts': await startTts(); break;
      // ustawienia
      case 'usun-plik': await usunPlik(el.dataset.typ, el.dataset.nazwa); break;
      case 'jakosc-preset': await ustawPresetJakosci(el.dataset.preset, el); break;
      case 'odswiez-listy': await odswiezListy(); break;
      case 'konto-test': await testujKonto(el.dataset.dostawca, el); break;
      case 'konto-usun': await usunKlucz(el.dataset.dostawca); break;
      case 'losuj-tekst': await losujTekst(); break;
      case 'usun-szablon': await usunSzablon(el.dataset.nazwa); break;
      // historia
      case 'historia-filtr': state.historiaFiltr = el.dataset.filtr || 'wszystko'; renderHistoria(); break;
      case 'odswiez-dziennik': await ladujHistoria(); toast('Historia odświeżona.', 'info'); break;
      default: break;
    }
  } catch (err) {
    bladToast(err);
  }
});

document.addEventListener('submit', async e => {
  const f = e.target;
  if (!(f instanceof HTMLFormElement)) return;
  if (f.closest('#dlg-potwierdz')) return; // natywne zamknięcie dialogu z returnValue
  e.preventDefault();
  try {
    if (f.id === 'form-nowa-persona') await nowaPersona();
    else if (f.id === 'form-pomysl-tekst') await dodajPomyslTekstowy(f);
    else if (f.id === 'form-zdjecia') await zrobZdjecia();
    else if (f.id === 'form-lipsync') await startLipsync();
    else if (f.id === 'form-lipsync-dialog') await startLipsyncZDialogu();
    else if (f.hasAttribute('data-ustawienia')) await zapiszUstawienia(f);
    else if (f.id === 'form-profil') await zapiszProfil(f);
    else if (f.id === 'form-teksty') await dodajTeksty();
    else if (f.id === 'form-szablon') await dodajSzablon();
    else if (f.dataset.kontoForm) { const inp = f.querySelector('input[name="klucz"]'); await zapiszKlucz(f.dataset.kontoForm, inp.value.trim()); inp.value = ''; }
  } catch (err) {
    bladToast(err);
  }
});

document.addEventListener('change', e => {
  const el = e.target;
  if (!(el instanceof Element)) return;
  if (el.id === 'wybor-modelki') zmienPersone(el.value).catch(err => { bladToast(err); renderPersonaSelect(); });
  else if (el.id === 'autopilot-przelacznik') przelaczAutopilot(el.checked);
  else if (el.id === 'tryb-przelacznik') ustawTryb(el.checked);
  else if (el.name === 'dostawca' && el.closest('#form-generowanie')) przelaczDostawce();
  else if (el.id === 'u-lipsync-dostawca') przelaczLipsyncDostawce();
  else if (el.id === 'ls-wideo') { $('#ls-wideo-sciezka-wrap').hidden = el.value !== '__inny'; if (el.value === '__inny') $('#ls-wideo-sciezka').focus(); }
  else if (el.id === 'ls-audio') { $('#ls-audio-sciezka-wrap').hidden = el.value !== '__inny'; if (el.value === '__inny') $('#ls-audio-sciezka').focus(); }
  else if (el.id === 'ls-dlg-audio') $('#ls-dlg-sciezka').hidden = !!el.value;
  else if (el.id === 'zd-stroj') renderStrojMini();
  else if (el.id === 'zp-persona') zmienPersone(el.value).catch(err => { bladToast(err); renderZpPersony(); });
  else if (el.id === 'zp-gotowe') {
    const g = ((state.zp.katalog || {}).pomysly || []).find(x => x.id === el.value);
    if (g) { $('#zp-pomysl').value = g.pl; delete state.zp.reczne.miejsce; }
    state.zp.pomyslId = g ? g.id : null;
    if (g) zpAsystent(true); else zpZmiana();
  }
  else if (el.id === 'zp-glos-id') zpZapiszGlosId().catch(bladToast);
  else if (el.closest && el.closest('#form-zp') && el.id !== 'zp-prompt') {
    if (el.id === 'zp-model') renderZpModel();
    if (el.id === 'zp-miejsce') { delete state.zp.reczne.obiekt; renderZpObiekt(); }
    if (el.id === 'zp-nazwy') renderZpObiekt($('#zp-obiekt').value);
    if (el.id === 'zp-stroj') $('#zp-stroj-tekst').hidden = el.value !== 'wlasny';
    if (el.id === 'zp-komentarz') $('#zp-komentarz-tekst').hidden = el.value !== 'wlasny';
    zpRecznie(el);
    zpZmiana();
  }
  else if (el.id === 'p-telegram') renderStanKontaTelegram(el.value);
  else if (el.id === 'dz-typ') ladujHistoria().catch(bladToast);
  else if (el.id === 'dz-modelka') renderHistoria();
  else if (el.id === 'plik-ukryty') { if (state.uploadTyp && el.files.length) wyslijPliki(state.uploadTyp, el.files); }
});

document.addEventListener('input', e => {
  const el = e.target;
  if (el instanceof Element && (el.id === 'u-prompt-a' || el.id === 'u-prompt-b')) renderPromptyInfo();
  if (el instanceof Element && el.id === 'zp-prompt') state.zp.edytowany = true;
  else if (el instanceof Element && ['zp-pomysl', 'zp-stroj-tekst', 'zp-komentarz-tekst'].includes(el.id)) {
    const id = state.zp.pomyslId;
    if (el.id === 'zp-komentarz-tekst') state.zp.reczne.komentarz = el.value;
    zpZmiana(); state.zp.pomyslId = el.id === 'zp-pomysl' && !el.value.trim() ? null : id;
    if (el.id === 'zp-pomysl') zpAsystentPozniej();      // asystent dobiera po chwili ciszy w pisaniu
  }
});

// strefy upload: klik / klawiatura / drag & drop
document.addEventListener('click', e => {
  const s = e.target.closest('.strefa[data-upload]');
  if (s && !e.target.closest('button')) wybierzPliki(s.dataset.upload);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    // Escape zamyka menu „więcej” i otwarte okienka (dialog modalny i tak reaguje na Escape – to dla pewności)
    zamknijMenu(null);
    $$('dialog[open]').forEach(d => d.close());
    return;
  }
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const s = e.target.closest && e.target.closest('.strefa[data-upload]');
  if (s) { e.preventDefault(); wybierzPliki(s.dataset.upload); }
});

// zdjęcie persony nie chce się wczytać (uszkodzony plik, zły format) -> w awatarze zostaje pierwsza litera nazwy
document.addEventListener('error', e => {
  const img = e.target;
  if (!(img instanceof Element) || img.tagName !== 'IMG' || img.dataset.litera === undefined) return;
  const wrap = img.closest('.avatar, #persona-avatar');
  if (!wrap) return;
  wrap.classList.add('litera');
  wrap.textContent = img.dataset.litera;
}, true);

// karta „Ostatnie 14 dni”: klik w nagłówek zapamiętuje, czy ma być rozwinięta (osobno Start / Historia); po rozwinięciu
// rysujemy wykres jeszcze raz, bo zwinięta karta nie zna swojej szerokości
document.addEventListener('click', e => {
  const sum = e.target.closest && e.target.closest('details[data-staty] > summary');
  if (!sum) return;
  const det = sum.parentElement;
  const bedzie = !det.open;
  try { localStorage.setItem(KLUCZ_STATY + det.dataset.staty, bedzie ? '1' : '0'); } catch (err) { /* prywatne okno */ }
  if (bedzie) setTimeout(() => { det.dataset.klucz = ''; renderStatystyki(); }, 0);
});

// zmiana szerokości okna -> wykres rysuje się od nowa (tylko gdy szerokość faktycznie się zmieniła)
let timerRozmiaru = null;
window.addEventListener('resize', () => { clearTimeout(timerRozmiaru); timerRozmiaru = setTimeout(() => renderStatystyki(), 200); });

// Pasek „Co się dzieje” jest przyklejony do dołu – mierzymy jego wysokość, żeby treść miała pod sobą tyle miejsca i nic nie zasłaniał.
function obserwujKonsole() {
  const k = $('#konsola');
  if (!k) return;
  const ustaw = () => document.documentElement.style.setProperty('--konsola-wys', `${k.offsetHeight}px`);
  if (window.ResizeObserver) new window.ResizeObserver(ustaw).observe(k);
  else window.addEventListener('resize', ustaw);
  ustaw();
}
document.addEventListener('dragover', e => {
  e.preventDefault(); // bez tego przeglądarka otwiera upuszczony plik
  const s = e.target.closest && e.target.closest('.strefa[data-upload]');
  if (s) s.classList.add('nad');
});
document.addEventListener('dragleave', e => {
  const s = e.target.closest && e.target.closest('.strefa[data-upload]');
  if (s) s.classList.remove('nad');
});
document.addEventListener('drop', e => {
  e.preventDefault();
  const s = e.target.closest && e.target.closest('.strefa[data-upload]');
  if (s) { s.classList.remove('nad'); wyslijPliki(s.dataset.upload, e.dataTransfer.files); }
});

window.addEventListener('hashchange', zastosujHash);

// ============================================================ START
async function start() {
  wstawIkony();
  wczytajTryb();
  obserwujKonsole();
  await odswiez();
  zastosujHash();
  setInterval(() => { odswiez(false); }, 5000);
  setInterval(() => {
    if (state.zadanie && state.zadanie.trwa) { renderKonsolaStan(); if (state.strona === 'start') renderKrok2(); }
  }, 1000);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
else start();
