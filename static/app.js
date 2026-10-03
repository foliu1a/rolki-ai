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

const STRONY = ['start', 'rolki', 'zdjecia', 'lipsync', 'ustawienia', 'historia'];
const STARE_STRONY = { pulpit: 'start', kolejka: 'rolki', persona: 'ustawienia/persona', konta: 'ustawienia/konta', teksty: 'ustawienia/teksty', dziennik: 'historia' };
const STATUSY = ['nowy', 'wygenerowany', 'postprodukcja', 'gotowe', 'blad'];
const FILTRY_ROLEK = [
  { id: 'wszystkie', nazwa: 'wszystkie', statusy: null },
  { id: 'nowy', nazwa: 'czekają', statusy: ['nowy'] },
  { id: 'w_trakcie', nazwa: 'w trakcie', statusy: ['wygenerowany', 'postprodukcja'] },
  { id: 'gotowe', nazwa: 'gotowe', statusy: ['gotowe'] },
  { id: 'blad', nazwa: 'nie wyszły', statusy: ['blad'] },
];
const STATUS_NA_FILTR = { nowy: 'nowy', wygenerowany: 'w_trakcie', postprodukcja: 'w_trakcie', gotowe: 'gotowe', blad: 'blad' };
const AKCEPT = { zrodlo: 'video/*,.mp4,.mov,.m4v,.webm', referencja: 'image/*', stroj: 'image/*', audio: 'audio/*,.mp3,.wav,.m4a,.aac,.ogg' };
const STRONY_PO_ZADANIU = ['start', 'rolki', 'zdjecia', 'lipsync', 'historia', 'ustawienia'];
const MODELE_SYNC_ZAPAS = ['lipsync-2', 'lipsync-2-pro', 'sync-3'];
const KLUCZ_TRYBU = 'rolki.tryb';

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
function nazwaPliku(s) { return s ? String(s).split(/[\\/]/).pop() : ''; }
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
  rolka: { nowy: 'czeka', wygenerowany: 'zrobiona (jeszcze nie wyprana)', postprodukcja: 'w obróbce', gotowe: 'gotowa', blad: 'nie wyszło', pobieranie: 'pobieram' },
  zdjecie: { nowy: 'czeka', wygenerowany: 'zrobione', postprodukcja: 'w obróbce', gotowe: 'gotowe', blad: 'nie wyszło' },
  lipsync: { nowy: 'w trakcie', wygenerowany: 'zrobiony', postprodukcja: 'w obróbce', gotowe: 'gotowy', blad: 'nie wyszło' },
};
function slowoStatusu(status, rodzaj = 'rolka') {
  const m = SLOWA_STATUSU[rodzaj] || SLOWA_STATUSU.rolka;
  return m[status] || SLOWA_STATUSU.rolka[status] || status || '';
}
function kolorStatusu(status) {
  return { nowy: 'akcent', wygenerowany: 'uwaga', postprodukcja: 'uwaga', gotowe: 'ok', blad: 'zle', pobieranie: 'uwaga' }[status] || '';
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
  [/min_kredyty/i, 'Za mało kredytów na koncie, żeby bezpiecznik pozwolił.'],
  [/limit dzienny/i, 'Dzisiejszy limit kredytów wyczerpany.'],
  [/max\/rolka/i, 'Ta rolka kosztowałaby więcej niż dozwolone na jedną rolkę.'],
  [/nsfw/i, 'Higgsfield odrzucił ten filmik (zasady treści).'],
  [/ip_detected/i, 'Higgsfield odrzucił (znak towarowy / prawa autorskie).'],
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
const CO_ROBIE = { skanuj: 'sprawdzam nowe filmiki', koszt: 'liczę koszt', generuj: 'rolki', pierz: 'pranie w Media Tool', lipsync: 'dopasowuję usta', zdjecia: 'zdjęcia', podpis: 'podpis', tts: 'głos z tekstu', autopilot_raz: 'przebieg autopilota', autopilot: 'autopilot', telegram_wyslij: 'wysyłam na telefon' };
const NAZWY_AKCJI = { skanuj: 'Sprawdzenie filmików', koszt: 'Liczenie kosztu', generuj: 'Robienie rolek', pierz: 'Pranie w Media Tool', lipsync: 'Dopasowanie ust', zdjecia: 'Zdjęcia', podpis: 'Podpis', tts: 'Głos z tekstu', autopilot_raz: 'Przebieg autopilota', autopilot: 'Autopilot', telegram_wyslij: 'Wysłanie na telefon' };
const ETAPY_AUTOPILOTA = { skanuj: 'sprawdza filmiki', generuj: 'robi rolki', podpisy: 'dobiera podpisy', zdjecia: 'robi zdjęcia' };

function prostyWynik(typ, w) {
  const n = x => (Array.isArray(x) ? x.length : (Number(x) || 0));
  if (w === null || w === undefined || w === '') return '';
  if (typeof w === 'string') {
    if (typ === 'pierz') return `wyprane: ${nazwaPliku(w)}`;
    if (typ === 'lipsync') return `usta dopasowane: ${nazwaPliku(w)}`;
    if (typ === 'tts') return `nagranie gotowe: ${nazwaPliku(w)}`;
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
      return `około ${kredytow(w.razem)} za ${poz.length} ${odmiana(poz.length, 'rolkę', 'rolki', 'rolek')}` + (nieznane ? ` (${nieznane} bez policzonego kosztu)` : '');
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
  }[typ] || 'Pracuję…';
}

// Wpis dziennika -> proste zdanie (tryb prosty).
function prostyTekstWpisu(w) {
  const t = String((w && w.tekst) || '');
  let m;
  if ((m = t.match(/^#(\d+): GOTOWE -> (.+)$/))) return `Rolka #${m[1]} gotowa: ${nazwaPliku(m[2])}`;
  if ((m = t.match(/^#(\d+): WYGENEROWANE \((\d+) kr/))) return `Rolka #${m[1]} zrobiona (${kredytow(m[2])})`;
  if ((m = t.match(/^#(\d+): start \(/))) return `Zaczynam rolkę #${m[1]}`;
  if ((m = t.match(/^#(\d+): BLAD po/i))) return `Rolka #${m[1]} nie wyszła`;
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
  if (odp.status === 409) throw new BladApi('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 409);
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
  telegram: {},          // bot Telegram: {skonfigurowany, sparowany, czat}
  dzis: null,            // podsumowanie dnia: {rolki, zdjecia, bledy, kredyty{...}}
  strona: 'start', sekcja: null,
  // rolki
  pomysly: [], statusy: STATUSY.slice(), pomyslyJson: '', filtr: 'wszystkie',
  odbierzTelefon: false, rolkiTelefon: false,   // czy listy były rysowane z podłączonym telefonem (przycisk „Wyślij na telefon”)
  otwartePrompty: new Set(), odtwarzane: new Set(),
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
  state.pomysly = []; state.pomyslyJson = ''; state.otwartePrompty.clear(); state.odtwarzane.clear();
  state.zdjecia = []; state.lipsync = []; state.ustawieniaPelne = null; state.teksty = []; state.szablony = [];
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
  if (state.stan) {
    if (state.strona === 'rolki') renderRolki();
    else if (state.strona === 'historia') { renderHistoria(); if (zapisz) ladujHistoria().catch(() => {}); }
    else if (state.strona === 'start') renderStart();
    else if (state.strona === 'lipsync') renderLipsyncHistoria();
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
  if (q) {
    const p = new URLSearchParams(q);
    const st = p.get('status');
    if (st) state.filtr = STATUS_NA_FILTR[st] || st;
  }
  state.sekcja = sekcja || null;
  pokazStrone(STRONY.includes(strona) ? strona : 'start');
}

function pokazStrone(nazwa) {
  state.strona = nazwa;
  $$('.strona').forEach(s => { s.hidden = s.id !== 'strona-' + nazwa; });
  $$('.nav a').forEach(a => a.classList.toggle('aktywny', a.dataset.strona === nazwa));
  if (state.timery.dziennik) { clearInterval(state.timery.dziennik); state.timery.dziennik = null; }
  window.scrollTo({ top: 0 });
  if (state.stan) ladujStrone(nazwa);
  if (nazwa === 'ustawienia' && state.sekcja) otworzSekcje(state.sekcja);
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
    start: () => ladujStart(false), rolki: () => ladujRolki(false), zdjecia: ladujZdjecia, lipsync: ladujLipsync,
    ustawienia: ladujUstawienia, historia: ladujHistoria,
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
    state.dziennikOstatni = d.dziennik_ostatni || null;
    state.wersja = d.wersja || '';
    renderPersonaSelect(); renderKredyty(); renderOdznaki(); renderKonsolaStan(); renderHamulecRolek();
    $('#wersja').textContent = state.wersja ? `rolki-ai v${state.wersja}` : '';
    const jest = !!state.stan;
    $('#brak-persony').hidden = jest;
    $('#strony').hidden = !jest;
    if (jest) {
      $('#ustawienia-tytul').textContent = 'Ustawienia: ' + (nazwaPersony(state.aktywna) || state.stan.modelka || '');
      if (state.strona === 'start') ladujStart(true).catch(() => {});
      else if (state.strona === 'rolki') ladujRolki(true).catch(() => {});
    }
    if (state.zadanie && state.zadanie.trwa) startKonsoli();
  } catch (e) {
    if (e.status === 0) polaczenie(false); else bladToast(e);
  } finally {
    state.odswiezanie = false;
  }
}
function polaczenie(ok) { $('#offline').hidden = ok; }
function nazwaPersony(slug) { const m = state.modelki.find(x => x.slug === slug); return m ? (m.nazwa || m.slug) : slug; }

function renderPersonaSelect() {
  const sel = $('#wybor-modelki');
  const html = state.modelki.length
    ? state.modelki.map(m => `<option value="${esc(m.slug)}">${esc(m.nazwa || m.slug)}${m.autopilot ? ' · autopilot' : ''}</option>`).join('')
    : '<option value="">— brak persony —</option>';
  if (sel.innerHTML !== html) sel.innerHTML = html;
  sel.value = state.aktywna || '';
  sel.disabled = !state.modelki.length;
}

// „Masz 1 234 kredytów · dziś wydałeś 90 z 300” – czerwone poniżej minimum, pomarańczowe przy 80 % limitu.
function renderKredyty() {
  const s = state.stan;
  const u = (s && s.ustawienia) || {};
  const b = (s && s.budzet) || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const saldo = state.saldo[dost] || {};
  const wrap = $('#kredyty'), el = $('#kredyty-tekst');
  const minKr = Number(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty) || 0;
  const wydano = Number(b.wydano_dzis) || 0, limit = Number(b.limit_dzienny) || 0;
  const gdzie = dost === 'yapper' ? ' yapper.so' : '';
  let html, klasa = '';
  const tytul = [];
  if (saldo.kredyty !== null && saldo.kredyty !== undefined) {
    html = `Masz <b>${esc(liczba(saldo.kredyty))}</b> ${odmiana(saldo.kredyty, 'kredyt', 'kredyty', 'kredytów')}${gdzie}`;
    tytul.push(`Kredyty to waluta ${dost === 'yapper' ? 'yapper.so' : 'Higgsfield'} – każda rolka kosztuje ich kilkadziesiąt.`);
    if (saldo.kredyty < minKr) { klasa = 'zle'; tytul.push(`To mniej niż ${liczba(minKr)} – tyle bezpiecznik każe zostawić na koncie, więc rolki się nie zrobią.`); }
    else if (minKr) tytul.push(`Bezpiecznik zostawia na koncie co najmniej ${liczba(minKr)}.`);
    if (saldo.czas) tytul.push(`Stan z ${formatCzas(saldo.czas)}.`);
  } else if (saldo.blad) {
    html = `<b>Nie widzę kredytów</b>${gdzie}`; klasa = 'zle'; tytul.push(prostyBlad(saldo.blad));
  } else {
    html = 'Sprawdzam kredyty…';
  }
  if (s) {
    html += ` <span class="kredyty-dzis">· dziś ${wydano ? 'wydałeś ' + esc(liczba(wydano)) : 'nic nie wydałeś'}${limit ? ' z ' + esc(liczba(limit)) : ''}</span>`;
    if (limit && wydano >= limit) { klasa = klasa || 'zle'; tytul.push('Dzisiejszy limit kredytów jest wykorzystany – jutro liczy się od nowa.'); }
    else if (limit && wydano >= limit * 0.8) { klasa = klasa || 'uwaga'; tytul.push(`Zbliżasz się do dziennego limitu ${liczba(limit)}.`); }
    else if (limit) tytul.push(`Dzienny limit: ${liczba(limit)} (Ustawienia → Limity).`);
  }
  el.innerHTML = html;
  wrap.className = 'kredyty' + (klasa ? ' ' + klasa : '');
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
        const czekajacy = state.konsola.oczekujacy.splice(0);
        // kroki pośrednie łańcucha „Zrób rolki” (skanuj, koszt) pokazuje karta kroku 2, bez toastów
        const cicho = state.lancuch.trwa && z.typ !== 'generuj';
        if (!cicho) {
          if (z.blad) toast(`Nie wyszło: ${prostyBlad(z.blad)}`, 'blad');
          else { const w = prostyWynik(z.typ, z.wynik); toast(`Gotowe: ${NAZWY_AKCJI[z.typ] || z.typ}${w ? ' – ' + w : ''}`, 'ok'); }
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
  $('#start-podtytul').textContent = `${nazwaPersony(state.aktywna) || s.modelka} · rolki robi ${u.dostawca === 'yapper' ? 'yapper.so (Wan 3.0)' : 'Higgsfield (Seedance 2.5)'}`;
  renderBanner();
  const niez = (s.niezeskanowane || []).length;
  $('#krok1-info').textContent = niez
    ? `${niez} ${odmiana(niez, 'nowy filmik czeka', 'nowe filmiki czekają', 'nowych filmików czeka')} na sprawdzenie.`
    : 'Nic nowego nie czeka. Wrzuć filmiki, a potem kliknij „Zrób rolki”.';
  $('#folder-wrzutnia').textContent = s.wrzutnia || '—';
  $('#folder-gotowe').textContent = s.gotowe_dir || '—';
  renderKrok2();
  renderAutopilot();
  renderDzis();
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
    return { kolor: 'zle', tekst: `yapper.so nie odpowiada: ${esc(prostyBlad(saldo.blad))}`, przycisk: { tekst: 'Zobacz konta', hash: '#ustawienia/konta' } };
  }
  // 1b. hamulec: autopilot zatrzymał się (np. kilka nieudanych rolek z rzędu) – stoi, dopóki user nie kliknie Wznów
  const pauza = (state.autopilotStan || {}).pauza;
  if (pauza) return { kolor: 'zle', tekst: tekstHamulca(pauza), przycisk: { tekst: 'Wznów', akcja: 'autopilot-wznow' } };
  // 2. za mało kredytów / limit dzienny
  const minKr = Number(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty) || 0;
  if (saldo.kredyty !== null && saldo.kredyty !== undefined && saldo.kredyty < minKr) {
    return { kolor: 'zle', tekst: `Za mało kredytów na koncie (${esc(liczba(saldo.kredyty))}). Doładuj albo zaloguj się na inne konto.` };
  }
  const wyd = Number(b.wydano_dzis) || 0, lim = Number(b.limit_dzienny) || 0;
  if (lim && wyd >= lim) return { kolor: 'zle', tekst: 'Dzisiejszy limit kredytów wykorzystany. Jutro zacznie od nowa.' };
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

// Karta „Dziś” na Starcie: rolki, zdjęcia, kredyty i problemy z dzisiejszego dnia (wszystkie persony razem).
function renderDzis() {
  const d = state.dzis, karta = $('#karta-dzis');
  if (!karta) return;
  if (!d) { karta.hidden = true; return; }
  karta.hidden = false;
  const kr = d.kredyty || {};
  const rolki = Number(d.rolki) || 0, zdjecia = Number(d.zdjecia) || 0, bledy = Number(d.bledy) || 0;
  const hf = Number(kr.higgsfield) || 0, yapper = Number(kr.yapper) || 0;
  const poz = [
    { id: 'rolki', n: rolki, e: odmiana(rolki, 'rolka', 'rolki', 'rolek') },
    { id: 'zdjecia', n: zdjecia, e: odmiana(zdjecia, 'zdjęcie', 'zdjęcia', 'zdjęć') },
    { id: 'kredyty', n: hf, e: odmiana(hf, 'kredyt', 'kredyty', 'kredytów'), dop: yapper > 0 ? `+ ${liczba(yapper)} yapper` : '' },
    { id: 'problemy', n: bledy, e: odmiana(bledy, 'problem', 'problemy', 'problemów'), klasa: bledy ? 'zle' : '' },
  ];
  $('#dzis-liczby').innerHTML = poz.map(p => `<div class="dzis-poz${p.klasa ? ' ' + p.klasa : ''}" id="dzis-${p.id}"><b>${esc(liczba(p.n))}</b><span>${esc(p.e)}</span>${p.dop ? `<small>${esc(p.dop)}</small>` : ''}</div>`).join('');
  $('#dzis-podtytul').textContent = state.modelki.length > 1 ? 'wszystkie persony razem' : '';
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
  const n = nazwaPliku(p.plik_wynikowy || p.zrodlo || '');
  return (n ? bezRozszerzenia(n).replace(/\.raw$/, '') : '') || p.opis || `rolka #${p.id}`;
}

function renderOdbierz() {
  const lista = state.pomysly.filter(p => ['gotowe', 'wygenerowany', 'postprodukcja'].includes(p.status) && p.wideo_url)
    .slice().sort((a, b) => b.id - a.id).slice(0, 6);
  const kont = $('#odbierz-lista');
  if (!lista.length) {
    kont.innerHTML = '<div class="pusto cicho"><b>Jeszcze nie ma gotowych rolek</b><span>Pojawią się tutaj, gdy klikniesz „Zrób rolki”.</span></div>';
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
  $('#autopilot-opis').textContent = `Co ${u.autopilot_co_minut || 15} min sprawdzi folder, zrobi rolki, wypierze je w Media Tool, dopasuje usta, jeśli jest głos, i zrobi zdjęcia. Pilnuje limitów kredytów.`;
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
    tel.innerHTML = u.telegram_wysylaj === false
      ? `${ikona('telefon')}<span>Telefon podłączony — wysyłanie gotowych rolek jest wyłączone (<a href="#ustawienia/autopilot">Ustawienia → Autopilot</a>)</span>`
      : `${ikona('telefon')}<span>Telefon podłączony — gotowe rolki lecą na Telegram</span>`;
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

// ---------- Rolki ----------
async function ladujRolki(cicho) {
  let d;
  try { d = await api('/api/pomysly'); }
  catch (e) { if (!cicho) throw e; return; }
  const json = JSON.stringify(d.pomysly || []);
  state.statusy = (d.statusy && d.statusy.length) ? d.statusy : STATUSY.slice();
  const telefon = telefonGotowy();
  if (cicho) {
    if (json === state.pomyslyJson && telefon === state.rolkiTelefon) return;
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
  const u = (state.stan && state.stan.ustawienia) || {};
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

function przyciskRolki(akcja, id, tekst, klasa = '') {
  return `<button class="btn btn-maly${klasa ? ' ' + klasa : ''}" type="button" data-akcja="${akcja}" data-id="${id}">${tekst}</button>`;
}

function kartaRolki(p) {
  const id = Number(p.id);
  const status = p.status || 'nowy';
  const info = p.info_zrodla || {};
  const nazwa = tytulRolki(p);
  const fakty = [];
  fakty.push(p.wariant === 'tekst' ? 'z tekstu' : (p.wariant === 'B' ? 'strój ze zdjęcia' : 'strój z filmu'));
  if (p.koszt !== null && p.koszt !== undefined) fakty.push(esc(kredytow(p.koszt)));
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
  const mini = miniaturaRolki(p);
  const obraz = mini ? `<img src="${esc(mini)}" alt="" loading="lazy">` : ikona('film');
  // miniatura gotowej rolki = przycisk „Odtwórz” (klik otwiera film na karcie)
  const miniatura = p.wideo_url
    ? `<button class="rolka-miniatura klik" type="button" data-akcja="odtworz" data-id="${id}" title="${gra ? 'Ukryj film' : 'Odtwórz'}" aria-label="${gra ? 'Ukryj film' : 'Odtwórz'} ${esc(nazwa)}">${obraz}<span class="rolka-play">${ikona(gra ? 'stop' : 'play')}</span></button>`
    : `<div class="rolka-miniatura">${obraz}</div>`;
  let glowny = '', drugi = '';
  if (status === 'nowy') glowny = przyciskRolki('generuj-pomysl', id, 'Zrób tę rolkę', 'btn-glowny');
  else if (status === 'blad') glowny = przyciskRolki('ponow', id, 'Spróbuj jeszcze raz', 'btn-glowny');
  else if (p.wideo_url) glowny = przyciskRolki('odtworz', id, gra ? 'Ukryj film' : `${ikona('play')}Odtwórz`, 'btn-glowny');
  if (telefon && !p.telegram_wyslano) drugi = przyciskRolki('telegram-wyslij', id, `${ikona('telefon')}Wyślij na telefon`);
  const menu = [przyciskRolki('prompt-pokaz', id, p.prompt_higgsfield ? 'Pokaż / zmień prompt' : 'Wpisz prompt')];
  if (status === 'nowy') menu.push(przyciskRolki('koszt-pomysl', id, 'Ile kosztuje?'));
  if (['wygenerowany', 'postprodukcja', 'gotowe'].includes(status)) {
    menu.push(przyciskRolki('pierz', id, 'Wypierz w Media Tool'));
    menu.push(przyciskRolki('lipsync-pomysl', id, 'Dopasuj usta (lipsync)'));
    menu.push(przyciskRolki('podpis', id, p.podpis ? 'Daj nowy podpis' : 'Daj podpis'));
  }
  if (p.lipsync_url) menu.push(`<a class="btn btn-maly" href="${esc(p.lipsync_url)}" target="_blank" rel="noopener">Otwórz wersję z dopasowanymi ustami</a>`);
  if (telefon && p.telegram_wyslano) menu.push(przyciskRolki('telegram-wyslij', id, `${ikona('telefon')}Wyślij na telefon jeszcze raz`));
  menu.push(przyciskRolki('usun-pomysl', id, 'Usuń', 'btn-zly'));
  let powod = '';
  if (status === 'blad' && p.notatki) powod = `<div class="rolka-powod"><b>Dlaczego:</b> ${esc(prostyBlad(p.notatki))}${state.pelny ? `<small>${esc(p.notatki)}</small>` : ''}</div>`;
  else if (p.notatki && state.pelny) powod = `<div class="rolka-meta">${esc(p.notatki)}</div>`;
  return `<article class="rolka" data-id="${id}">
    ${miniatura}
    <div class="rolka-tresc">
      <div class="rolka-gora"><h3 class="rolka-nazwa">${esc(nazwa)}</h3><span class="status ${kolorStatusu(status)}"><span class="kropka ${kolorStatusu(status)}"></span>${esc(slowoStatusu(status))}</span></div>
      ${meta.length ? `<div class="rolka-meta">${meta.join(' · ')}</div>` : ''}
      ${p.opis && p.opis !== nazwa && p.wariant === 'tekst' ? `<div class="rolka-meta">${esc(p.opis)}</div>` : ''}
      <div class="rolka-fakty">${fakty.map(f => `<span class="fakt">${f}</span>`).join('')}</div>
      ${powod}
      ${p.podpis ? `<div class="rolka-podpis"><span>${esc(p.podpis)}</span><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(p.podpis)}" title="kopiuj podpis">${ikona('kopiuj')}kopiuj</button></div>` : ''}
      ${promptOtwarty ? `<div class="rolka-prompt"><label for="prompt-${id}">Prompt – opis dla AI, co zrobić z tym filmikiem</label><textarea id="prompt-${id}" data-prompt="${id}" spellcheck="false" placeholder="Wklej prompt persony albo własny…">${esc(p.prompt_higgsfield || '')}</textarea><div class="rzad"><button class="btn btn-maly btn-glowny" type="button" data-akcja="zapisz-prompt" data-id="${id}">Zapisz prompt</button>${bezPromptu ? '' : `<button class="btn btn-maly" type="button" data-akcja="prompt-pokaz" data-id="${id}">Zwiń</button>`}</div></div>` : ''}
      ${gra ? `<video controls autoplay preload="metadata" src="${esc(p.wideo_url)}"></video>` : ''}
      <div class="rolka-akcje">${glowny}${drugi}<details class="menu"><summary class="btn btn-maly">więcej ${ikona('chevron-dol')}</summary><div class="menu-lista">${menu.join('')}</div></details></div>
    </div>
  </article>`;
}

// Treść pytania „Robić?” z kosztem w kredytach.
function trescKosztu(razem, n, nieznane = 0) {
  const s = state.stan || {};
  const u = s.ustawienia || {}, b = s.budzet || {};
  const dost = b.dostawca || u.dostawca || 'higgsfield';
  const saldo = (state.saldo[dost] || {}).kredyty;
  let html = '';
  if (razem !== null && razem !== undefined) {
    html += `<p>To będzie kosztować około <b>${esc(kredytow(razem))}</b> (${n} ${odmiana(n, 'rolka', 'rolki', 'rolek')}).`;
    if (nieznane) html += ` Dla ${nieznane} ${odmiana(nieznane, 'rolki', 'rolek', 'rolek')} nie udało się policzyć kosztu – fabryka policzy go tuż przed zrobieniem.`;
    html += '</p>';
    if (saldo !== null && saldo !== undefined) html += `<p>Na koncie masz ${esc(liczba(saldo))}, po zrobieniu zostanie około <b>${esc(liczba(saldo - razem))}</b>.</p>`;
  } else {
    html += `<p><b>Nie udało się policzyć kosztu.</b> Fabryka policzy go tuż przed zrobieniem każdej rolki i zatrzyma się, gdyby przekroczył bezpiecznik.</p>`;
  }
  if (b.limit_dzienny) html += `<p>Dziś wydano ${esc(liczba(b.wydano_dzis || 0))} z ${esc(liczba(b.limit_dzienny))} dozwolonych.</p>`;
  html += '<p class="dialog-uwaga">To wyda kredyty.</p>';
  return html;
}

function kosztZWyniku(z, id) {
  const poz = (z && z.wynik && Array.isArray(z.wynik.pozycje)) ? z.wynik.pozycje : [];
  const w = poz.find(x => Array.isArray(x) && Number(x[0]) === id);
  return w && w[1] !== null && w[1] !== undefined ? Number(w[1]) : null;
}

async function generujPomysl(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (p && !p.prompt_higgsfield) { toast('Ta rolka nie ma promptu – wpisz go (więcej → Wpisz prompt) i zapisz.', 'uwaga'); return; }
  if (state.zadanie && state.zadanie.trwa) { toast('Coś już się dzieje — poczekaj, aż skończy, albo kliknij STOP.', 'uwaga'); return; }
  let koszt = p && p.koszt !== null && p.koszt !== undefined ? Number(p.koszt) : null;
  if (koszt === null) {
    const z = await akcjaCzekaj({ typ: 'koszt', ids: [id] }, 'liczę koszt', true);
    if (!z) return;
    koszt = z.blad ? null : kosztZWyniku(z, id);
  }
  const w = await potwierdz({ tytul: 'Zrobić tę rolkę?', tresc: trescKosztu(koszt, 1, koszt === null ? 0 : 0), ok: 'Zrób' });
  if (!w) return;
  await akcja({ typ: 'generuj', ids: [id] }, 'robię rolkę');
}

async function ponowPomysl(id) {
  await api(`/api/pomysly/${id}/ponow`, 'POST', {});
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

// ---------- Zdjęcia ----------
async function ladujZdjecia() {
  const s = state.stan || {};
  const u = s.ustawienia || {};
  $('#zdjecia-brak-modelu').hidden = !!u.zdjecia_model;
  $('#form-zdjecia').hidden = !u.zdjecia_model;
  $('#zdjecia-opis-modelu').textContent = u.zdjecia_model ? `Każde zdjęcie kosztuje kredyty Higgsfield (model: ${u.zdjecia_model}).` : 'Każde zdjęcie kosztuje kredyty Higgsfield.';
  $('#zdjecia-dzis').textContent = `dziś zrobione: ${s.zdjecia_dzis !== undefined ? s.zdjecia_dzis : 0}${u.zdjecia_dziennie ? ` z ${u.zdjecia_dziennie} (autopilot)` : ''}`;
  const d = await api('/api/zdjecia');
  state.zdjecia = d.zdjecia || [];
  renderZdjecia();
}

function renderZdjecia() {
  const kont = $('#zdjecia-galeria');
  const lista = state.zdjecia.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    kont.innerHTML = `<div class="pusto" style="grid-column:1/-1"><span class="ikona">${ikona('zdjecia')}</span><b>Jeszcze nie ma zdjęć</b><span>Kliknij „Zrób zdjęcie”. Autopilot też może robić zdjęcia sam – ustaw „Ile zdjęć dziennie” w Ustawienia → Zdjęcia.</span></div>`;
    return;
  }
  kont.innerHTML = lista.map(z => `<figure class="zdjecie" data-id="${Number(z.id)}">
    ${z.url ? `<a href="${esc(z.url)}" target="_blank" rel="noopener"><img src="${esc(z.url)}" alt="" loading="lazy"></a>` : `<div class="brak-obrazu"><span class="ikona">${ikona('zdjecia')}</span></div>`}
    <figcaption class="zdjecie-tresc">
      <div class="zdjecie-stopka"><span class="status ${kolorStatusu(z.status)}"><span class="kropka ${kolorStatusu(z.status)}"></span>${esc(slowoStatusu(z.status, 'zdjecie'))}</span><span class="muted">${z.koszt !== null && z.koszt !== undefined ? esc(kredytow(z.koszt)) : ''}</span></div>
      <div class="zdjecie-prompt" title="${esc(z.prompt)}">${esc(z.prompt || '')}</div>
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
  const w = await potwierdz({
    tytul: `Zrobić ${ile} ${odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}?`,
    tresc: `<p>${prompt ? `Opis: „${esc(prompt)}”.` : 'Opis weźmie się po kolei z listy w Ustawienia → Zdjęcia.'}${state.pelny ? ` Model: <b>${esc(u.zdjecia_model)}</b>.` : ''}</p><p class="dialog-uwaga">To kosztuje kredyty.</p>`,
    ok: 'Zrób',
  });
  if (!w) return;
  const dane = { typ: 'zdjecia', ile };
  if (prompt) dane.prompt = prompt;
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
}

function renderLipsyncHistoria() {
  const kont = $('#lipsync-historia');
  const lista = state.lipsync.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    kont.innerHTML = '<div class="pusto cicho"><b>Jeszcze nic nie dopasowywałem</b><span>Wybierz rolkę i głos powyżej. Autopilot zrobi to sam, gdy obok filmiku w folderze położysz <span class="mono">nazwa.audio.mp3</span>.</span></div>';
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
  let szczegoly = '';
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
  otworzDialog('#dlg-lipsync');
}

async function startLipsyncZDialogu() {
  const id = Number($('#ls-dlg-id').value);
  const audio = $('#ls-dlg-audio').value || $('#ls-dlg-sciezka').value.trim();
  if (!audio) { toast('Wybierz nagranie głosu albo wpisz ścieżkę do pliku.', 'uwaga'); return; }
  $('#dlg-lipsync').close();
  await akcja({ typ: 'lipsync', id, audio }, 'dopasowuję usta');
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
    else if (el.dataset.typ === 'json') {
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

function wypelnijFormularz(form, dane) {
  Array.from(form.elements).forEach(el => {
    if (!el.name || el.type === 'submit' || el.type === 'button') return;
    const v = wartoscZ(dane, el.name);
    if (el.type === 'checkbox') el.checked = !!v;
    else if (el.type === 'radio') el.checked = String(el.value) === String(v === null || v === undefined ? '' : v);
    else if (el.dataset.typ === 'tri') el.value = v === null || v === undefined ? '' : String(v);
    else if (el.dataset.typ === 'json') el.value = v && typeof v === 'object' && Object.keys(v).length ? JSON.stringify(v) : '';
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
  const dane = Object.assign({}, u, { prompt_a_tekst: pr.a || '', prompt_b_tekst: pr.b || '', zdjecia_prompty_tekst: pr.zdjecia || '', jakosc: u.resolution || '' });
  renderStrojDomyslny(d);
  $$('#strona-ustawienia form[data-ustawienia]').forEach(f => wypelnijFormularz(f, dane));
  przelaczDostawce();
  renderReferencje(d);
  renderFoldery(d);
  renderPromptyInfo();
  // profil: API nie ma GET profilu – nazwa z listy person, reszta pól (instagram, cechy, styl) tylko do zapisu
  const prof = (state.stan && state.stan.profil) || {};
  wypelnijFormularz($('#form-profil'), {
    nazwa: prof.nazwa || nazwaPersony(state.aktywna) || '', instagram: prof.instagram || '', opis_stylu: prof.opis_stylu || '',
    cechy: Array.isArray(prof.cechy) ? prof.cechy.join(', ') : (prof.cechy || ''),
  });
  try {
    const b = await api('/api/budzet');
    state.budzet = b;
    const dzis = b.dzis || {};
    $('#limit-higgsfield').value = (dzis.higgsfield && dzis.higgsfield.limit !== undefined) ? dzis.higgsfield.limit : ((b.budzet || {}).max_kredyty_dziennie || 0);
    $('#limit-yapper').value = (dzis.yapper && dzis.yapper.limit !== undefined) ? dzis.yapper.limit : 0;
  } catch (e) { /* limity są dodatkiem */ }
  ladujKonta().catch(bladToast);
  ladujTeksty().catch(bladToast);
  // listy modeli/głosów dociągamy w tle
  podlaczListe($('#u-yapper-model'), 'modele?dostawca=yapper');
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

function renderFoldery(d) {
  const f = d.foldery || {};
  const wiersze = [['Filmiki (wrzutnia)', f.wrzutnia], ['Gotowe rolki', f.gotowe], ['Zdjęcia', f.zdjecia], ['Nagrania głosu', f.audio], ['Folder persony w programie', f.modelka]].filter(w => w[1]);
  $('#foldery-efektywne').innerHTML = wiersze.length
    ? '<div class="etykieta">Teraz używane:</div>' + wiersze.map(([n, s]) => `<div class="folder-wiersz"><span class="etykieta">${esc(n)}</span><span class="sciezka">${esc(s)}</span><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(s)}" title="kopiuj ścieżkę">${ikona('kopiuj')}</button></div>`).join('')
    : '';
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
      // kafelki „Jakość” -> resolution (Higgsfield) i yapper.resolution (ta sama jakość u obu dostawców)
      if (dane.jakosc) { dane.resolution = dane.jakosc; ustawW(dane, 'yapper.resolution', dane.jakosc); }
      delete dane.jakosc;
    }
    if (dane.budzet) {
      // limity dzienne to osobny plik (budzet.json), wspólny dla wszystkich person
      for (const [dost, v] of Object.entries(dane.budzet)) {
        await api('/api/budzet', 'POST', { dostawca: dost, max_kredyty_dziennie: Math.max(0, Number(v) || 0) });
      }
      delete dane.budzet;
    }
    const d = await api('/api/ustawienia', 'POST', dane);
    if (d.ustawienia) {
      if (state.ustawieniaPelne) state.ustawieniaPelne.ustawienia = d.ustawienia;
      if (state.stan) state.stan.ustawienia = d.ustawienia;
    }
    if (f.id === 'form-prompty' && state.ustawieniaPelne) {
      state.ustawieniaPelne.prompty = Object.assign({}, state.ustawieniaPelne.prompty, { a: dane.prompt_a_tekst, b: dane.prompt_b_tekst });
      renderPromptyInfo();
    }
    if (f.id === 'form-zdjecia-ust' && state.ustawieniaPelne) {
      state.ustawieniaPelne.prompty = Object.assign({}, state.ustawieniaPelne.prompty, { zdjecia: dane.zdjecia_prompty_tekst });
    }
    toast('Zapisane.', 'ok');
    odswiez();
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function zapiszProfil(f) {
  const dane = zbierzFormularz(f);
  const d = await api('/api/profil', 'POST', { nazwa: dane.nazwa || '', instagram: dane.instagram || '', opis_stylu: dane.opis_stylu || '', cechy: dane.cechy || '' });
  if (state.stan && d.profil) state.stan.profil = d.profil;
  toast('Zapisane.', 'ok');
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
  odswiez();
}

async function odswiezListy() {
  state.listy = {};
  if (state.strona === 'ustawienia') {
    podlaczListe($('#u-yapper-model'), 'modele?dostawca=yapper', true);
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
  const kolejnosc = ['higgsfield', 'telegram', 'yapper', 'sync', 'elevenlabs'];
  const ids = kolejnosc.filter(x => k[x]).concat(Object.keys(k).filter(x => !kolejnosc.includes(x)));
  $('#konta-lista').innerHTML = ids.length ? ids.map(id => kartaKonta(id, k[id])).join('') : '<div class="pusto"><b>Brak danych o kontach</b></div>';
}

const OPISY_KONT = {
  higgsfield: 'Robi rolki i zdjęcia. Logowanie przez przeglądarkę, bez klucza.',
  yapper: 'Zapasowy sposób robienia rolek (Wan 3.0). Potrzebne tylko, jeśli wybierzesz go w „Jak robić rolki”.',
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
  const m = String(w.komunikat || '').match(/(\d+)\s*kr/);
  return 'Działa.' + (m ? ` Masz ${kredytow(m[1])}.` : '');
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
    srodek = `${k.ok === false && k.komunikat ? `<div class="konto-powod">${esc(prostyBlad(k.komunikat))}</div>` : ''}
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
      ${k.jest ? `<div class="konto-maska" data-zaawansowane>klucz: ${esc(k.maska || '••••')}${k.z_env ? ' (ze zmiennej środowiskowej)' : ''}</div>` : ''}
      <form class="rzad" data-konto-form="${esc(id)}"><input type="password" name="klucz" placeholder="${k.jest ? 'wklej nowy klucz, żeby podmienić' : 'wklej klucz API'}" autocomplete="off" aria-label="Klucz API ${esc(nazwa)}"><button class="btn btn-glowny" type="submit">Zapisz</button></form>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="${esc(id)}"${k.jest ? '' : ' disabled'}>Sprawdź</button>${k.jest && !k.z_env ? `<button class="btn btn-maly btn-zly" type="button" data-akcja="konto-usun" data-dostawca="${esc(id)}">Usuń klucz</button>` : ''}${wynikHtml}</div>`;
  }
  const opis = OPISY_KONT[id] || k.opis || '';
  return `<div class="karta konto" data-konto="${esc(id)}"${id === 'elevenlabs' ? ' data-zaawansowane' : ''}>
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
    ? wpisy.map(w => `<tr><td class="czas" title="${esc(formatData(w.czas))}">${esc(formatCzas(w.czas))}</td><td><span class="rzad" style="gap:6px;flex-wrap:nowrap"><span class="kropka ${esc(w.typ || 'info')}"></span>${esc(w.typ === 'blad' ? 'błąd' : (w.typ || ''))}</span></td><td class="nowrap">${esc(w.modelka || '')}</td><td>${esc(w.tekst)}${w.dane ? ` <small class="muted">${esc(daneDziennika(w.dane))}</small>` : ''}</td></tr>`).join('')
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
      // rolki
      case 'filtr': state.filtr = el.dataset.filtr || 'wszystkie'; renderRolki(); break;
      case 'koszt-pomysl': await akcja({ typ: 'koszt', ids: [id] }, 'liczę koszt'); break;
      case 'generuj-pomysl': await generujPomysl(id); break;
      case 'ponow': await ponowPomysl(id); break;
      case 'odtworz': if (state.odtwarzane.has(id)) state.odtwarzane.delete(id); else state.odtwarzane.add(id); if (state.strona === 'start') renderOdbierz(); else renderRolki(); break;
      case 'prompt-pokaz': if (state.otwartePrompty.has(id)) state.otwartePrompty.delete(id); else state.otwartePrompty.add(id); renderRolki(); { const ta = $(`textarea[data-prompt="${id}"]`); if (ta) ta.focus(); } break;
      case 'pierz': await akcja({ typ: 'pierz', id }, 'pranie w Media Tool'); break;
      case 'lipsync-pomysl': await otworzLipsyncDialog(id); break;
      case 'podpis': await akcja({ typ: 'podpis', id }, 'dobieram podpis'); break;
      case 'usun-pomysl': await usunPomysl(id); break;
      case 'zapisz-prompt': await zapiszPrompt(id); break;
      // zdjęcia, lipsync
      case 'usun-zdjecie': await usunZdjecie(id); break;
      case 'usun-lipsync': await usunLipsync(id); break;
      case 'tts': await startTts(); break;
      // ustawienia
      case 'usun-plik': await usunPlik(el.dataset.typ, el.dataset.nazwa); break;
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
  else if (el.id === 'dz-typ') ladujHistoria().catch(bladToast);
  else if (el.id === 'dz-modelka') renderHistoria();
  else if (el.id === 'plik-ukryty') { if (state.uploadTyp && el.files.length) wyslijPliki(state.uploadTyp, el.files); }
});

document.addEventListener('input', e => {
  const el = e.target;
  if (el instanceof Element && (el.id === 'u-prompt-a' || el.id === 'u-prompt-b')) renderPromptyInfo();
});

// strefy upload: klik / klawiatura / drag & drop
document.addEventListener('click', e => {
  const s = e.target.closest('.strefa[data-upload]');
  if (s && !e.target.closest('button')) wybierzPliki(s.dataset.upload);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { zamknijMenu(null); return; }
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const s = e.target.closest && e.target.closest('.strefa[data-upload]');
  if (s) { e.preventDefault(); wybierzPliki(s.dataset.upload); }
});
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
  await odswiez();
  zastosujHash();
  setInterval(() => { odswiez(false); }, 5000);
  setInterval(() => {
    if (state.zadanie && state.zadanie.trwa) { renderKonsolaStan(); if (state.strona === 'start') renderKrok2(); }
  }, 1000);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
else start();
