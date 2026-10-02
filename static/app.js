'use strict';
/* rolki-ai – panel (static/app.js). Czysty JS (ES2020), bez bibliotek i zasobów z sieci.
   Układ pliku:
     1. narzędzia (esc, formatowanie, ikony)
     2. API (fetch + obsługa {"ok": false}) i toasty
     3. stan aplikacji
     4. nawigacja (#hash)
     5. pasek górny, bok (autopilot), konsola zadania
     6. strony: pulpit, kolejka, zdjęcia, lipsync, persona, konta, teksty, dziennik
     7. dialogi, upload (drag & drop), zadania w tle
     8. zdarzenia (delegacja) i start
   Zasada: każdy tekst z serwera lub od użytkownika przechodzi przez esc() zanim trafi do innerHTML. */

// ============================================================ 1. NARZĘDZIA
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const STRONY = ['pulpit', 'kolejka', 'zdjecia', 'lipsync', 'persona', 'konta', 'teksty', 'dziennik'];
const STATUSY = ['nowy', 'wygenerowany', 'postprodukcja', 'gotowe', 'blad'];
const ETYKIETY_STATUSU = { nowy: 'nowy', wygenerowany: 'wygenerowany', postprodukcja: 'postprodukcja', gotowe: 'gotowe', blad: 'błąd', pobieranie: 'pobieranie' };
const ETYKIETY_AKCJI = {
  skanuj: 'Skanowanie wrzutni', koszt: 'Liczenie kosztu', generuj: 'Generowanie rolek', pierz: 'Pranie (Media Tool)',
  lipsync: 'Lipsync', zdjecia: 'Zdjęcia persony', podpis: 'Podpis', tts: 'Głos z tekstu', autopilot_raz: 'Przebieg autopilota',
};
const MODELE_SYNC_ZAPAS = ['lipsync-2', 'lipsync-2-pro', 'sync-3'];
const AKCEPT = { zrodlo: 'video/*,.mp4,.mov,.m4v,.webm', referencja: 'image/*', stroj: 'image/*', audio: 'audio/*,.mp3,.wav,.m4a,.aac,.ogg' };
const STRONY_PO_ZADANIU = ['pulpit', 'kolejka', 'zdjecia', 'lipsync', 'dziennik', 'konta'];

const ESC_MAPA = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ESC_MAPA[c]);
}
function liczba(n) {
  if (n === null || n === undefined || n === '' || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('pl-PL');
}
function kr(n) { return (n === null || n === undefined) ? '—' : `${liczba(n)} kr`; }
function nazwaPliku(s) { return s ? String(s).split(/[\\/]/).pop() : ''; }
function odmiana(n, poj, kilka, wiele) {
  n = Math.abs(Number(n) || 0);
  if (n === 1) return poj;
  const r10 = n % 10, r100 = n % 100;
  if (r10 >= 2 && r10 <= 4 && !(r100 >= 12 && r100 <= 14)) return kilka;
  return wiele;
}
function dwaZnaki(n) { return String(n).padStart(2, '0'); }
function data(iso) {
  if (iso === null || iso === undefined || iso === '') return null;
  // ISO string albo znacznik (sekundy / milisekundy)
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
function formatOdstep(sek) {
  sek = Math.max(0, Math.floor(sek));
  const h = Math.floor(sek / 3600), m = Math.floor((sek % 3600) / 60), s = sek % 60;
  return h ? `${h}:${dwaZnaki(m)}:${dwaZnaki(s)}` : `${m}:${dwaZnaki(s)}`;
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

// Ikony liniowe (24x24, stroke = currentColor).
const IKONY = {
  pulpit: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  kolejka: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  zdjecia: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 16-5-5-8 8"/>',
  lipsync: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>',
  persona: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  konta: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l2 2M14 9l2 2"/>',
  teksty: '<path d="M4 6h16M4 12h10M4 18h14"/>',
  dziennik: '<path d="M5 3h13a1 1 0 0 1 1 1v16H7a2 2 0 0 1-2-2V3z"/><path d="M5 18a2 2 0 0 1 2-2h12M9 7h6"/>',
  odswiez: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4h-4"/>',
  kopiuj: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  kosz: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  chevron: '<path d="m6 15 6-6 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  uwaga: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  zamknij: '<path d="M6 6l12 12M18 6 6 18"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
  ok: '<path d="m5 12 5 5L20 7"/>',
  folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6z"/>',
};
function ikona(nazwa) {
  const p = IKONY[nazwa];
  return p ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>` : '';
}
function wstawIkony(root = document) {
  $$('.ikona[data-ikona]', root).forEach(el => { if (!el.firstChild) el.innerHTML = ikona(el.dataset.ikona); });
}

// ============================================================ 2. API I TOASTY
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
  catch (e) { throw new BladApi('Brak połączenia z panelem – czy app.py działa?', 0); }
  let json = null;
  try { json = await odp.json(); } catch (e) { json = null; }
  if (odp.status === 409) throw new BladApi('Coś już trwa – poczekaj albo zatrzymaj w konsoli', 409);
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
  timer = setTimeout(usun, typ === 'blad' ? 9000 : (opcje.akcja ? 10000 : 4000));
}
function bladToast(e) { toast(e && e.message ? e.message : String(e), 'blad'); }

// ============================================================ 3. STAN
const state = {
  stan: null,            // /api/stan -> "stan" (null = brak aktywnej persony)
  modelki: [], aktywna: null, saldo: {}, autopilot: {}, zadanie: {}, konta: {}, dziennikOstatni: null, wersja: '',
  strona: 'pulpit',
  // kolejka
  pomysly: [], statusy: STATUSY.slice(), pomyslyJson: '', filtr: 'wszystkie',
  otwartePrompty: new Set(), odtwarzane: new Set(),
  // reszta stron
  zdjecia: [], lipsync: [], ustawieniaPelne: null, budzet: null, kontaPelne: null, testyKont: {},
  teksty: [], szablony: [], dziennik: [],
  listy: {},             // cache list modeli/głosów: zapytanie -> {czas, pozycje, blad}
  konsola: { otwarta: false, logOd: 0, start: null, trwalo: false, timer: null, sprawdzanie: false },
  timery: { dziennik: null },
  uploadTyp: null,
  odswiezanie: false,
};

function wyczyscCachePersony() {
  state.pomysly = []; state.pomyslyJson = ''; state.otwartePrompty.clear(); state.odtwarzane.clear();
  state.zdjecia = []; state.lipsync = []; state.ustawieniaPelne = null; state.teksty = []; state.szablony = [];
}

// ============================================================ 4. NAWIGACJA
function zastosujHash() {
  const h = (location.hash || '').replace(/^#/, '');
  const [strona, q] = h.split('?');
  if (q) {
    const p = new URLSearchParams(q);
    if (p.get('status')) state.filtr = p.get('status');
  }
  pokazStrone(STRONY.includes(strona) ? strona : 'pulpit');
}

function pokazStrone(nazwa) {
  state.strona = nazwa;
  $$('.strona').forEach(s => { s.hidden = s.id !== 'strona-' + nazwa; });
  $$('.nav a').forEach(a => a.classList.toggle('aktywny', a.dataset.strona === nazwa));
  if (state.timery.dziennik) { clearInterval(state.timery.dziennik); state.timery.dziennik = null; }
  window.scrollTo({ top: 0 });
  if (state.stan) ladujStrone(nazwa);
}

function ladujStrone(nazwa) {
  const mapa = {
    pulpit: ladujPulpit, kolejka: () => ladujKolejke(false), zdjecia: ladujZdjecia, lipsync: ladujLipsync,
    persona: ladujPersone, konta: ladujKonta, teksty: ladujTeksty, dziennik: ladujDziennik,
  };
  const f = mapa[nazwa];
  if (f) Promise.resolve().then(f).catch(bladToast);
}

// ============================================================ 5. PASEK GÓRNY, BOK, KONSOLA
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
    state.zadanie = d.zadanie || state.zadanie || {};
    state.konta = d.konta || {};
    state.dziennikOstatni = d.dziennik_ostatni || null;
    state.wersja = d.wersja || '';
    renderPersonaSelect(); renderKredyty(); renderAutopilot(); renderOdznaki(); renderKonsolaStan();
    $('#wersja').textContent = state.wersja ? `rolki-ai v${state.wersja}` : '';
    const jest = !!state.stan;
    $('#brak-persony').hidden = jest;
    $('#strony').hidden = !jest;
    if (jest) {
      $('#persona-tytul').textContent = 'Persona: ' + (nazwaPersony(state.aktywna) || state.stan.modelka || '');
      if (state.strona === 'pulpit') ladujPulpit().catch(() => {});
      if (state.strona === 'kolejka') ladujKolejke(true).catch(() => {});
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

function renderKredyty() {
  const s = state.stan;
  const u = (s && s.ustawienia) || {};
  const b = (s && s.budzet) || {};
  const hf = state.saldo.higgsfield || {};
  const yp = state.saldo.yapper || {};
  const wrap = $('#kredyty');
  $('#kredyty-hf-liczba').textContent = hf.kredyty === null || hf.kredyty === undefined ? '—' : liczba(hf.kredyty);
  $('#kredyty-hf-liczba').title = hf.blad || (hf.czas ? 'stan z ' + formatCzas(hf.czas) : '');
  const hfBlad = $('#kredyty-hf-blad'); hfBlad.hidden = !hf.blad; hfBlad.textContent = hf.blad || ''; hfBlad.title = hf.blad || '';
  const pokazYapper = u.dostawca === 'yapper';
  $('#kredyty-yapper').hidden = !pokazYapper;
  if (pokazYapper) {
    $('#kredyty-yapper-liczba').textContent = yp.kredyty === null || yp.kredyty === undefined ? '—' : liczba(yp.kredyty);
    const ypBlad = $('#kredyty-yapper-blad'); ypBlad.hidden = !yp.blad; ypBlad.textContent = yp.blad || ''; ypBlad.title = yp.blad || '';
  }
  const wydano = Number(b.wydano_dzis) || 0, limit = Number(b.limit_dzienny) || 0;
  $('#kredyty-dzis-etykieta').textContent = `dziś · ${b.dostawca || u.dostawca || 'higgsfield'}`;
  $('#kredyty-dzis').textContent = s ? (limit ? `${liczba(wydano)} / ${liczba(limit)} kr` : `${liczba(wydano)} kr (bez limitu)`) : '—';
  $('#kredyty-pasek').style.width = limit ? `${Math.min(100, wydano / limit * 100)}%` : '0%';
  wrap.classList.remove('uwaga', 'zle');
  const minKr = Number(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty) || 0;
  const saldoAkt = pokazYapper ? yp : hf;
  const brakSalda = s && saldoAkt.kredyty !== null && saldoAkt.kredyty !== undefined && saldoAkt.kredyty < minKr;
  if ((s && saldoAkt.blad) || brakSalda || (limit && wydano >= limit)) wrap.classList.add('zle');
  else if (limit && wydano >= limit * 0.8) wrap.classList.add('uwaga');
}

function renderAutopilot() {
  const a = state.autopilot || {};
  const chk = $('#autopilot-przelacznik');
  if (document.activeElement !== chk) chk.checked = !!a.wlaczony;
  let txt, klasa = '';
  if (a.trwa) {
    txt = `pracuje: ${a.modelka || ''}${a.etap ? ' – ' + a.etap : ''}`; klasa = 'aktywny';
  } else if (a.wlaczony) {
    const m = a.nastepny ? minutDo(a.nastepny) : null;
    txt = m === null ? 'włączony, czeka na pierwszy przebieg' : (m <= 0 ? 'zaraz rusza' : `następny przebieg za ${m} min`);
    klasa = 'aktywny';
    const u = state.stan && state.stan.ustawienia;
    if (state.stan && u && !u.autopilot) txt += ' · ta persona ma wyłączony autopilot (Persona → Autopilot)';
  } else {
    txt = 'wyłączony' + (a.przebiegi ? ` · przebiegów: ${a.przebiegi}` : '');
  }
  const el = $('#autopilot-status');
  el.textContent = txt;
  el.className = 'autopilot-tekst' + (klasa ? ' ' + klasa : '');
}

function renderOdznaki() {
  const st = (state.stan && state.stan.statystyki) || {};
  const nowe = $('#odznaka-nowe'), bledy = $('#odznaka-bledy');
  nowe.hidden = !st.nowy; nowe.textContent = st.nowy || '';
  bledy.hidden = !st.blad; bledy.textContent = st.blad || '';
}

// --- konsola zadania ---
function otworzKonsole(otwarta) {
  state.konsola.otwarta = otwarta;
  document.body.classList.toggle('konsola-otwarta', otwarta);
  $('.konsola-przelacz').setAttribute('aria-expanded', String(otwarta));
  if (otwarta) { const pre = $('#konsola-log'); pre.scrollTop = pre.scrollHeight; }
}

function renderKonsolaStan() {
  const z = state.zadanie || {};
  const a = state.autopilot || {};
  const kropka = $('#konsola-kropka'), tytul = $('#konsola-tytul'), czas = $('#konsola-czas');
  $('#konsola-stop').hidden = !z.trwa;
  const etykieta = ETYKIETY_AKCJI[z.typ] || z.typ || (a.trwa ? 'autopilot' : 'zadanie');
  if (z.trwa) {
    kropka.className = 'kropka kredyty pulsuje';
    tytul.textContent = `${etykieta}${z.modelka ? ' · ' + z.modelka : ''}${a.trwa && a.etap ? ' · ' + a.etap : ''}`;
    tytul.className = 'konsola-tytul trwa';
    czas.textContent = z.start ? formatOdstep(sekundOd(z.start)) : '';
  } else if (z.blad) {
    kropka.className = 'kropka blad';
    tytul.textContent = `${etykieta}: błąd – ${z.blad}`;
    tytul.className = 'konsola-tytul blad';
    czas.textContent = z.koniec ? formatCzas(z.koniec) : '';
  } else if (z.typ) {
    kropka.className = 'kropka ok';
    const w = tekstWyniku(z.wynik);
    tytul.textContent = `${etykieta}: zakończono${w ? ' – ' + w : ''}`;
    tytul.className = 'konsola-tytul ok';
    czas.textContent = z.koniec ? formatCzas(z.koniec) : '';
  } else {
    kropka.className = 'kropka';
    tytul.textContent = 'bezczynna – tu pojawi się log zadania';
    tytul.className = 'konsola-tytul';
    czas.textContent = '';
  }
}

function startKonsoli() {
  if (state.konsola.timer) return;
  state.konsola.timer = setInterval(sprawdzZadanie, 1500);
  sprawdzZadanie();
}
function stopKonsoli() {
  if (state.konsola.timer) { clearInterval(state.konsola.timer); state.konsola.timer = null; }
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
      $('#konsola-log').textContent = '';
      z = await api('/api/zadanie?od=0');
    }
    if (Array.isArray(z.log) && z.log.length) dopiszLog(z.log);
    state.konsola.logOd = typeof z.log_dlugosc === 'number' ? z.log_dlugosc : state.konsola.logOd + ((z.log || []).length);
    state.zadanie = z;
    renderKonsolaStan();
    if (z.trwa) {
      state.konsola.trwalo = true;
    } else {
      stopKonsoli();
      if (state.konsola.trwalo) {
        state.konsola.trwalo = false;
        const etykieta = ETYKIETY_AKCJI[z.typ] || z.typ || 'Zadanie';
        if (z.blad) toast(`${etykieta}: ${z.blad}`, 'blad');
        else { const w = tekstWyniku(z.wynik); toast(`${etykieta}: zakończono${w ? ' – ' + w : ''}`, 'ok'); }
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
  const pre = $('#konsola-log');
  const naDole = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 40;
  pre.appendChild(document.createTextNode(linie.join('\n') + '\n'));
  if (pre.childNodes.length > 60) pre.textContent = pre.textContent.split('\n').slice(-3000).join('\n');
  if (naDole) pre.scrollTop = pre.scrollHeight;
}

// ============================================================ 6. STRONY
// ---------- Pulpit ----------
async function ladujPulpit() {
  renderPulpit();
  try {
    const d = await api('/api/dziennik?ile=8');
    renderWpisy($('#pulpit-dziennik'), (d.wpisy || []).slice().reverse());
  } catch (e) { /* dziennik jest dodatkiem – nie przeszkadzaj */ }
}

function kafel(sel, n, klasa) {
  const el = $(sel);
  el.querySelector('.kafel-liczba').textContent = liczba(n);
  el.className = 'kafel' + (n > 0 ? ' ' + klasa : '');
}

function renderPulpit() {
  const s = state.stan;
  if (!s) return;
  const st = s.statystyki || {}, u = s.ustawienia || {}, b = s.budzet || {};
  const doGen = (s.do_generacji || []).length, bezP = (s.bez_promptu || []).length;
  kafel('#kafel-do-generacji', doGen, 'akcent');
  kafel('#kafel-bez-promptu', bezP, 'uwaga');
  kafel('#kafel-gotowe', st.gotowe || 0, 'ok');
  kafel('#kafel-bledy', st.blad || 0, 'zle');
  const nowe = st.nowy || 0;
  $('#pulpit-podtytul').textContent = `${nazwaPersony(state.aktywna) || s.modelka} · ${u.dostawca === 'yapper' ? 'yapper.so' : 'Higgsfield'} · ${nowe} ${odmiana(nowe, 'nowy', 'nowe', 'nowych')} · ${st.gotowe || 0} ${odmiana(st.gotowe || 0, 'gotowa', 'gotowe', 'gotowych')}`;

  const wyd = Number(b.wydano_dzis) || 0, lim = Number(b.limit_dzienny) || 0;
  $('#budzet-dostawca').textContent = `kredyty ${b.dostawca || u.dostawca || 'higgsfield'} wydane dziś`;
  $('#budzet-wydano').textContent = liczba(wyd);
  $('#budzet-limit').textContent = lim ? `/ ${liczba(lim)} kr` : 'kr (bez limitu)';
  const pasek = $('#budzet-pasek');
  const proc = lim ? Math.min(100, wyd / lim * 100) : 0;
  pasek.querySelector('i').style.width = proc + '%';
  pasek.className = 'pasek' + (lim && proc >= 100 ? ' zle' : (proc >= 80 ? ' uwaga' : ''));
  $('#budzet-rolki').textContent = `${b.rolki_dzis !== undefined ? b.rolki_dzis : 0}${b.max_rolek_dziennie ? ' / ' + b.max_rolek_dziennie : ''}`;
  $('#budzet-min').textContent = kr(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty);
  $('#budzet-max').textContent = kr(b.max_kredyty_na_rolke !== undefined ? b.max_kredyty_na_rolke : u.max_kredyty_na_rolke);
  $('#budzet-zdjecia').textContent = `${s.zdjecia_dzis !== undefined ? s.zdjecia_dzis : 0}${u.zdjecia_dziennie ? ' / ' + u.zdjecia_dziennie : ''}`;

  renderCoTeraz(s);
  $('#folder-wrzutnia').textContent = s.wrzutnia || '—';
  $('#folder-gotowe').textContent = s.gotowe_dir || '—';
}

function cta(hash, tekst) { return `<a class="btn" href="${esc(hash)}">${esc(tekst)} →</a>`; }

function renderCoTeraz(s) {
  const st = s.statystyki || {};
  const ref = (s.referencje || []).length;
  const niez = s.niezeskanowane || [], bezP = s.bez_promptu || [], doGen = s.do_generacji || [];
  let opis, html = '';
  if (!ref) {
    opis = 'Najpierw dodaj zdjęcia persony (referencje) – bez nich model nie wie, kogo generować.';
    html = cta('#persona', 'Przejdź do Persona → Referencje');
  } else if (!s.prompt_a) {
    opis = 'Brak promptu A (strój z filmu). Wklej swój prompt w Persona → Prompty.';
    html = cta('#persona', 'Przejdź do Persona → Prompty');
  } else if (niez.length) {
    opis = `We wrzutni ${niez.length === 1 ? 'czeka 1 nowy filmik' : `czeka ${niez.length} ${odmiana(niez.length, 'nowy filmik', 'nowe filmiki', 'nowych filmików')}`} – kliknij „Skanuj wrzutnię”.`;
    html = `<div class="callout info"><span class="ikona">${ikona('film')}</span><div><b>Niezeskanowane:</b> ${niez.map(n => `<span class="tag">${esc(n)}</span>`).join(' ')}</div></div>`;
  } else if (bezP.length) {
    opis = `${bezP.length} ${odmiana(bezP.length, 'pomysł nie ma', 'pomysły nie mają', 'pomysłów nie ma')} promptu (${bezP.map(i => '#' + i).join(', ')}) – uzupełnij w Kolejce albo włącz „prompt automatycznie” w Persona → Generowanie.`;
    html = cta('#kolejka?status=nowy', 'Otwórz kolejkę');
  } else if (doGen.length) {
    opis = `${doGen.length} ${odmiana(doGen.length, 'rolka czeka', 'rolki czekają', 'rolek czeka')} na generację (${doGen.map(i => '#' + i).join(', ')}). Policz koszt, potem „Generuj wszystko”.`;
  } else if (st.blad) {
    opis = `${st.blad} ${odmiana(st.blad, 'pomysł skończył się błędem', 'pomysły skończyły się błędem', 'pomysłów skończyło się błędem')} – sprawdź w Kolejce i kliknij „Ponów”.`;
    html = cta('#kolejka?status=blad', 'Pokaż błędy');
  } else {
    opis = 'Wszystko zrobione. Wrzuć nowe filmiki do wrzutni:';
    html = `<div class="rzad"><span class="sciezka">${esc(s.wrzutnia || '')}</span><button class="btn btn-maly" type="button" data-akcja="kopiuj" data-tekst="${esc(s.wrzutnia || '')}">${ikona('kopiuj')}kopiuj</button></div>`;
  }
  $('#co-teraz-opis').textContent = opis;
  $('#co-teraz-szczegoly').innerHTML = html;
}

function renderWpisy(ul, wpisy) {
  ul.innerHTML = wpisy.length
    ? wpisy.map(w => `<li class="wpis"><span class="kropka ${esc(w.typ || 'info')}"></span><span class="wpis-czas" title="${esc(formatData(w.czas))}">${esc(formatCzas(w.czas))}</span><span class="wpis-tekst">${esc(w.tekst)}${w.modelka && w.modelka !== state.aktywna ? ` <small>(${esc(w.modelka)})</small>` : ''}</span></li>`).join('')
    : '<li class="wpis"><span class="kropka"></span><span class="wpis-czas"></span><span class="wpis-tekst muted">Jeszcze nic się nie wydarzyło.</span></li>';
}

// ---------- Kolejka ----------
async function ladujKolejke(cicho) {
  let d;
  try { d = await api('/api/pomysly'); }
  catch (e) { if (!cicho) throw e; return; }
  const json = JSON.stringify(d.pomysly || []);
  state.statusy = (d.statusy && d.statusy.length) ? d.statusy : STATUSY.slice();
  if (cicho) {
    if (json === state.pomyslyJson) return;
    const akt = document.activeElement;
    if (akt && akt.tagName === 'TEXTAREA' && $('#kolejka-lista').contains(akt)) return; // nie przerywaj edycji promptu
  }
  state.pomysly = d.pomysly || [];
  state.pomyslyJson = json;
  renderKolejka();
}

function renderKolejka() {
  const u = (state.stan && state.stan.ustawienia) || {};
  $('#pomysl-tekst-hint').hidden = !!u.mode_bez_zrodla;
  const liczby = { wszystkie: state.pomysly.length };
  state.statusy.forEach(s => { liczby[s] = 0; });
  state.pomysly.forEach(p => { liczby[p.status] = (liczby[p.status] || 0) + 1; });
  if (state.filtr !== 'wszystkie' && !state.statusy.includes(state.filtr)) state.filtr = 'wszystkie';
  $('#kolejka-filtry').innerHTML = ['wszystkie', ...state.statusy].map(s =>
    `<button type="button" class="chip${state.filtr === s ? ' aktywny' : ''}" data-akcja="filtr" data-status="${esc(s)}">${esc(s === 'wszystkie' ? 'wszystkie' : (ETYKIETY_STATUSU[s] || s))} <span class="n">${liczby[s] || 0}</span></button>`
  ).join('');
  const lista = state.pomysly.filter(p => state.filtr === 'wszystkie' || p.status === state.filtr).slice().sort((a, b) => b.id - a.id);
  const kont = $('#kolejka-lista');
  if (!lista.length) {
    const s = state.stan || {};
    kont.innerHTML = state.pomysly.length
      ? `<div class="pusto"><b>Nic w tym filtrze</b><span>Kliknij „wszystkie”, żeby zobaczyć całą kolejkę.</span></div>`
      : `<div class="pusto"><span class="ikona">${ikona('film')}</span><b>Kolejka jest pusta</b><span>Wrzuć filmiki do: <span class="sciezka">${esc(s.wrzutnia || '')}</span></span><span>a potem kliknij „Skanuj wrzutnię” – każdy filmik stanie się pomysłem na rolkę.</span><button class="btn btn-glowny" type="button" data-akcja="skanuj">Skanuj wrzutnię</button></div>`;
    return;
  }
  kont.innerHTML = lista.map(kartaPomyslu).join('');
}

function kartaPomyslu(p) {
  const id = Number(p.id);
  const status = p.status || 'nowy';
  const info = p.info_zrodla || {};
  const meta = [];
  if (p.zrodlo) meta.push(`źródło: ${esc(nazwaPliku(p.zrodlo))}`);
  if (info.czas) meta.push(`${esc(Number(info.czas).toFixed(1).replace('.', ','))} s`);
  if (info.szer && info.wys) meta.push(`${esc(info.szer)}×${esc(info.wys)}`);
  if (p.plik_wynikowy) meta.push(`wynik: ${esc(nazwaPliku(p.plik_wynikowy))}`);
  if (p.lipsync_plik) meta.push(`lipsync: ${esc(nazwaPliku(p.lipsync_plik))}`);
  if (p.wygenerowano) meta.push(`wygenerowano ${esc(formatCzas(p.wygenerowano))}`);
  const tagi = [`<span class="tag" title="wariant">${esc(p.wariant === 'tekst' ? 'z tekstu' : 'wariant ' + (p.wariant || 'A'))}</span>`];
  if (p.koszt !== null && p.koszt !== undefined) tagi.push(`<span class="tag" title="koszt">${esc(kr(p.koszt))}</span>`);
  if (p.dostawca) tagi.push(`<span class="tag">${esc(p.dostawca)}</span>`);
  if (p.audio_nazwa || p.audio) tagi.push(`<span class="tag" title="głos do lipsyncu">${ikona('audio')}${esc(p.audio_nazwa || nazwaPliku(p.audio))}</span>`);
  if (status === 'nowy' && !p.prompt_higgsfield) tagi.push('<span class="tag uwaga">brak promptu</span>');
  const otwarty = state.otwartePrompty.has(id) || (status === 'nowy' && !p.prompt_higgsfield);
  const odtwarzane = state.odtwarzane.has(id) && p.wideo_url;
  return `<article class="pomysl" data-id="${id}">
    <div class="pomysl-miniatura">${p.miniatura_url ? `<img src="${esc(p.miniatura_url)}" alt="" loading="lazy">` : `<span class="ikona">${ikona('film')}</span>`}</div>
    <div class="pomysl-tresc">
      <div class="pomysl-gora"><span class="pomysl-id">#${id}</span><span class="badge ${esc(status)}">${esc(ETYKIETY_STATUSU[status] || status)}</span>${tagi.join('')}</div>
      <div class="pomysl-opis">${esc(p.opis || '(bez opisu)')}</div>
      ${meta.length ? `<div class="pomysl-meta">${meta.join(' · ')}</div>` : ''}
      <details class="prompt" data-id="${id}"${otwarty ? ' open' : ''}>
        <summary>${p.prompt_higgsfield ? 'pokaż prompt' : 'wpisz prompt'}</summary>
        <textarea data-prompt="${id}" spellcheck="false" placeholder="Prompt dla modelu…">${esc(p.prompt_higgsfield || '')}</textarea>
        <div class="rzad"><button class="btn btn-maly btn-glowny" type="button" data-akcja="zapisz-prompt" data-id="${id}">Zapisz prompt</button></div>
      </details>
      ${p.notatki ? `<div class="${status === 'blad' ? 'pomysl-notatki' : 'pomysl-meta'}">${esc(p.notatki)}</div>` : ''}
      ${p.podpis ? `<div class="pomysl-podpis"><span>${esc(p.podpis)}</span><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(p.podpis)}" title="kopiuj podpis">${ikona('kopiuj')}</button></div>` : ''}
      ${odtwarzane ? `<video controls preload="metadata" src="${esc(p.wideo_url)}"></video>` : ''}
      <div class="pomysl-akcje">${przyciskiPomyslu(p)}</div>
    </div>
  </article>`;
}

function przyciskiPomyslu(p) {
  const id = Number(p.id);
  const b = [];
  const przycisk = (akcja, tekst, klasa = '') => `<button class="btn btn-maly${klasa ? ' ' + klasa : ''}" type="button" data-akcja="${akcja}" data-id="${id}">${tekst}</button>`;
  if (p.status === 'nowy') { b.push(przycisk('koszt-pomysl', 'Policz koszt')); b.push(przycisk('generuj-pomysl', 'Generuj', 'btn-glowny')); }
  if (p.status === 'blad') b.push(przycisk('ponow', 'Ponów', 'btn-glowny'));
  if (['wygenerowany', 'postprodukcja', 'gotowe'].includes(p.status)) {
    if (p.wideo_url) b.push(przycisk('odtworz', state.odtwarzane.has(id) ? 'Ukryj wideo' : `${ikona('play')}Odtwórz`));
    b.push(przycisk('pierz', 'Pierz (Media Tool)'));
    b.push(przycisk('lipsync-pomysl', 'Lipsync'));
    b.push(przycisk('podpis', p.podpis ? 'Nowy podpis' : 'Podpis'));
  }
  b.push(przycisk('usun-pomysl', 'Usuń', 'btn-zly'));
  return b.join('');
}

function sumaKosztow(lista) {
  const w = { znane: 0, nieznane: 0, suma: 0 };
  (lista || []).forEach(p => {
    if (p && p.koszt !== null && p.koszt !== undefined && !Number.isNaN(Number(p.koszt))) { w.znane++; w.suma += Number(p.koszt); }
    else w.nieznane++;
  });
  return w;
}

function trescKosztu(k, n) {
  const s = state.stan || {};
  const u = s.ustawienia || {}, b = s.budzet || {};
  const dost = u.dostawca || 'higgsfield';
  const saldo = (state.saldo[dost] || {}).kredyty;
  let html = `<p><b>${n}</b> ${odmiana(n, 'pozycja', 'pozycje', 'pozycji')}. `;
  if (k.znane) html += `Znany koszt: <b>${esc(kr(k.suma))}</b>${k.nieznane ? ` (${k.nieznane} bez policzonego kosztu)` : ''}.`;
  else html += 'Koszt jeszcze niepoliczony – fabryka policzy go przed każdą pozycją i zatrzyma się, gdy przekroczy bezpiecznik.';
  html += '</p>';
  if (saldo !== null && saldo !== undefined && k.znane) {
    html += `<p>Saldo ${esc(dost)}: ${esc(liczba(saldo))} kr → po generacji ok. <b>${esc(liczba(saldo - k.suma))} kr</b> (minimum na koncie: ${esc(liczba(b.min_kredyty !== undefined ? b.min_kredyty : u.min_kredyty))}).</p>`;
  }
  if (b.limit_dzienny) html += `<p>Dziś wydano ${esc(liczba(b.wydano_dzis || 0))} / ${esc(liczba(b.limit_dzienny))} kr.</p>`;
  html += '<p class="dialog-uwaga">To wyda kredyty.</p>';
  return html;
}

async function generujWszystko() {
  const s = state.stan;
  if (!s) return;
  const ids = (s.do_generacji || []).map(Number);
  if (!ids.length) { toast('Nie ma nic do generacji – najpierw „Skanuj wrzutnię” i sprawdź prompty.', 'uwaga'); return; }
  let koszty = { znane: 0, nieznane: ids.length, suma: 0 };
  try { const d = await api('/api/pomysly'); koszty = sumaKosztow((d.pomysly || []).filter(p => ids.includes(Number(p.id)))); } catch (e) { /* bez kosztu */ }
  const w = await potwierdz({ tytul: `Generować ${ids.length} ${odmiana(ids.length, 'rolkę', 'rolki', 'rolek')}?`, tresc: trescKosztu(koszty, ids.length), ok: 'Generuj' });
  if (!w) return;
  await akcja({ typ: 'generuj', ids });
}

async function generujPomysl(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (p && !p.prompt_higgsfield) { toast('Ten pomysł nie ma promptu – wpisz go i zapisz.', 'uwaga'); return; }
  const w = await potwierdz({ tytul: `Generować rolkę #${id}?`, tresc: trescKosztu(sumaKosztow(p ? [p] : []), 1), ok: 'Generuj' });
  if (!w) return;
  await akcja({ typ: 'generuj', ids: [id] }, `Generowanie #${id}`);
}

async function policzKosztWszystkich() {
  const s = state.stan;
  if (s && !(s.do_generacji || []).length) { toast('Nie ma nowych pomysłów z promptem – nie ma czego liczyć.', 'uwaga'); return; }
  await akcja({ typ: 'koszt' });
}

async function zapiszPrompt(id) {
  const ta = $(`textarea[data-prompt="${id}"]`);
  if (!ta) return;
  const d = await api(`/api/pomysly/${id}`, 'PATCH', { prompt_higgsfield: ta.value });
  const i = state.pomysly.findIndex(x => Number(x.id) === id);
  if (i >= 0 && d.pomysl) state.pomysly[i] = d.pomysl;
  state.pomyslyJson = JSON.stringify(state.pomysly);
  toast(`Zapisano prompt #${id}`, 'ok');
  renderKolejka();
  odswiez();
}

async function usunPomysl(id) {
  const w = await potwierdz({ tytul: `Usunąć pomysł #${id}?`, tresc: '<p>Pomysł zniknie z kolejki. Filmik źródłowy we wrzutni zostaje.</p>', ok: 'Usuń', klasa: 'btn-zly', checkbox: 'Usuń też pliki wynikowe (gotowe wideo)' });
  if (!w) return;
  await api(`/api/pomysly/${id}${w.zaznaczone ? '?plik=1' : ''}`, 'DELETE');
  toast(`Usunięto #${id}`, 'ok');
  state.otwartePrompty.delete(id); state.odtwarzane.delete(id);
  await ladujKolejke(false);
  odswiez();
}

async function dodajPomyslTekstowy(f) {
  const opis = $('#pt-opis').value.trim();
  if (!opis) { toast('Wpisz opis pomysłu.', 'uwaga'); return; }
  const d = await api('/api/pomysly', 'POST', { opis, prompt: $('#pt-prompt').value.trim() });
  toast(`Dodano pomysł #${d.id}`, 'ok');
  f.reset();
  await ladujKolejke(false);
  odswiez();
}

// ---------- Zdjęcia ----------
async function ladujZdjecia() {
  const s = state.stan || {};
  const u = s.ustawienia || {};
  $('#zdjecia-brak-modelu').hidden = !!u.zdjecia_model;
  $('#zdjecia-opis-modelu').textContent = u.zdjecia_model ? `Model: ${u.zdjecia_model}. Każde zdjęcie kosztuje kredyty Higgsfield.` : 'Każde zdjęcie kosztuje kredyty Higgsfield.';
  $('#zdjecia-dzis').textContent = `dziś: ${s.zdjecia_dzis !== undefined ? s.zdjecia_dzis : 0}${u.zdjecia_dziennie ? ' / ' + u.zdjecia_dziennie + ' (autopilot)' : ''}`;
  const d = await api('/api/zdjecia');
  state.zdjecia = d.zdjecia || [];
  renderZdjecia();
}

function renderZdjecia() {
  const kont = $('#zdjecia-galeria');
  const lista = state.zdjecia.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    kont.innerHTML = `<div class="pusto" style="grid-column:1/-1"><span class="ikona">${ikona('zdjecia')}</span><b>Jeszcze nie ma zdjęć</b><span>Kliknij „Zrób zdjęcie” albo ustaw „Zdjęć dziennie” w Persona → Zdjęcia – autopilot zrobi je sam.</span></div>`;
    return;
  }
  kont.innerHTML = lista.map(z => `<figure class="zdjecie" data-id="${Number(z.id)}">
    ${z.url ? `<a href="${esc(z.url)}" target="_blank" rel="noopener"><img src="${esc(z.url)}" alt="" loading="lazy"></a>` : `<div class="brak-obrazu"><span class="ikona">${ikona('zdjecia')}</span></div>`}
    <figcaption class="zdjecie-tresc">
      <div class="zdjecie-stopka"><span><b>#${Number(z.id)}</b> <span class="badge ${esc(z.status || '')}">${esc(ETYKIETY_STATUSU[z.status] || z.status || '')}</span></span><span class="muted">${z.koszt !== null && z.koszt !== undefined ? esc(kr(z.koszt)) : ''}</span></div>
      <div class="zdjecie-prompt" title="${esc(z.prompt)}">${esc(z.prompt || '')}</div>
      ${z.notatki ? `<div class="muted">${esc(z.notatki)}</div>` : ''}
      <div class="zdjecie-stopka"><span class="muted">${esc(formatCzas(z.utworzono))}</span><span class="rzad" style="gap:4px">${z.prompt ? `<button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(z.prompt)}" title="kopiuj prompt">${ikona('kopiuj')}</button>` : ''}<button class="btn btn-maly btn-zly" type="button" data-akcja="usun-zdjecie" data-id="${Number(z.id)}">Usuń</button></span></div>
    </figcaption>
  </figure>`).join('');
}

async function zrobZdjecia() {
  const u = (state.stan && state.stan.ustawienia) || {};
  if (!u.zdjecia_model) { toast('Najpierw wybierz model zdjęć w Persona → Zdjęcia.', 'uwaga'); return; }
  const ile = Math.max(1, Math.min(20, Number($('#zd-ile').value) || 1));
  const prompt = $('#zd-prompt').value.trim();
  const w = await potwierdz({
    tytul: `Zrobić ${ile} ${odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}?`,
    tresc: `<p>Model <b>${esc(u.zdjecia_model)}</b>${prompt ? `, prompt: „${esc(prompt)}”` : ', prompty po kolei z listy persony'}.</p><p class="dialog-uwaga">To wyda kredyty Higgsfield.</p>`,
    ok: 'Zrób',
  });
  if (!w) return;
  const dane = { typ: 'zdjecia', ile };
  if (prompt) dane.prompt = prompt;
  await akcja(dane);
}

async function usunZdjecie(id) {
  const w = await potwierdz({ tytul: `Usunąć zdjęcie #${id}?`, tresc: '', ok: 'Usuń', klasa: 'btn-zly', checkbox: 'Usuń też plik z dysku' });
  if (!w) return;
  await api(`/api/zdjecia/${id}${w.zaznaczone ? '?plik=1' : ''}`, 'DELETE');
  toast(`Usunięto zdjęcie #${id}`, 'ok');
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
  $('#ls-model-info').textContent = lista.blad ? `Lista modeli niedostępna (${lista.blad}) – pokazuję domyślne.` : '';
  // głosy TTS
  const gsel = $('#tts-glos'), gid = $('#tts-glos-id');
  const biezacyGlos = (gsel.hidden ? gid.value : gsel.value) || ust.tts_glos || '';
  const glosy = await pobierzListe('glosy?dostawca=sync');
  if (glosy.pozycje.length) {
    gsel.innerHTML = '<option value="">— wybierz głos —</option>' + glosy.pozycje.map(g => `<option value="${esc(g.id)}">${esc(g.nazwa || g.id)}${g.opis ? ' – ' + esc(g.opis) : ''}</option>`).join('');
    ustawSelectWartosc(gsel, biezacyGlos);
    gsel.hidden = false; gid.hidden = true;
  } else {
    gsel.hidden = true; gid.hidden = false;
    if (!gid.value) gid.value = biezacyGlos;
  }
  $('#tts-glos-info').textContent = glosy.blad ? `Lista głosów niedostępna: ${glosy.blad}. Wpisz voice id ręcznie.` : '';
}

function renderLipsyncFormularz() {
  const selW = $('#ls-wideo');
  const biezW = selW.value;
  const gotowe = state.pomysly.filter(p => p.wideo_url).slice().sort((a, b) => b.id - a.id);
  selW.innerHTML = '<option value="">— wpisz ścieżkę poniżej —</option>' + gotowe.map(p =>
    `<option value="${Number(p.id)}">#${Number(p.id)} ${esc(p.opis || '')} (${esc(nazwaPliku(p.plik_wynikowy) || ETYKIETY_STATUSU[p.status] || '')})</option>`).join('');
  selW.value = Array.from(selW.options).some(o => o.value === biezW) ? biezW : (gotowe[0] ? String(gotowe[0].id) : '');
  $('#ls-wideo-sciezka').hidden = !!selW.value;

  const selA = $('#ls-audio');
  const biezA = selA.value;
  const audio = (state.ustawieniaPelne && state.ustawieniaPelne.audio) || [];
  selA.innerHTML = '<option value="">— wpisz ścieżkę poniżej —</option>' + audio.map(a => `<option value="${esc(a.sciezka)}">${esc(a.nazwa)}</option>`).join('');
  selA.value = Array.from(selA.options).some(o => o.value === biezA) ? biezA : (audio[0] ? audio[0].sciezka : '');
  $('#ls-audio-sciezka').hidden = !!selA.value;

  const ust = (state.stan && state.stan.ustawienia) || {};
  const tryb = $('#ls-tryb');
  if (!tryb.dataset.ustawiony) { ustawSelectWartosc(tryb, (ust.lipsync_parametry || {}).sync_mode || 'bounce'); tryb.dataset.ustawiony = '1'; }
}

function renderLipsyncHistoria() {
  const kont = $('#lipsync-historia');
  const lista = state.lipsync.slice().sort((a, b) => b.id - a.id);
  if (!lista.length) {
    kont.innerHTML = '<div class="pusto"><b>Jeszcze nie było lipsyncu</b><span>Wybierz wideo i głos powyżej, albo wrzuć plik <span class="mono">nazwa.audio.mp3</span> obok filmiku do wrzutni – autopilot zrobi lipsync sam.</span></div>';
    return;
  }
  kont.innerHTML = `<div class="tabela-wrap"><table class="tabela"><thead><tr><th>#</th><th>Czas</th><th>Wideo</th><th>Głos</th><th>Model</th><th>Status</th><th>Koszt</th><th></th></tr></thead><tbody>${lista.map(l => `<tr>
    <td class="nowrap">#${Number(l.id)}${l.pomysl_id ? ` <small>(rolka #${Number(l.pomysl_id)})</small>` : ''}</td>
    <td class="czas" title="${esc(formatData(l.utworzono))}">${esc(formatCzas(l.utworzono))}</td>
    <td title="${esc(l.wideo)}">${esc(nazwaPliku(l.wideo))}</td>
    <td title="${esc(l.audio)}">${esc(nazwaPliku(l.audio))}</td>
    <td class="nowrap">${esc(l.dostawca || '')} ${esc(l.model || '')}</td>
    <td><span class="badge ${esc(l.status)}">${esc(ETYKIETY_STATUSU[l.status] || l.status)}</span>${l.notatki ? `<div class="muted" style="font-size:12px">${esc(l.notatki)}</div>` : ''}</td>
    <td class="nowrap">${l.koszt !== null && l.koszt !== undefined ? esc(liczba(l.koszt)) + (l.dostawca === 'sync' ? ' c' : ' kr') : '—'}</td>
    <td class="akcje">${l.url ? `<a class="btn btn-maly" href="${esc(l.url)}" target="_blank" rel="noopener">${ikona('play')}Odtwórz</a> ` : ''}<button class="btn btn-maly btn-zly" type="button" data-akcja="usun-lipsync" data-id="${Number(l.id)}">Usuń</button></td>
  </tr>`).join('')}</tbody></table></div>`;
}

async function startLipsync() {
  const wideoId = $('#ls-wideo').value;
  const wideoSciezka = $('#ls-wideo-sciezka').value.trim();
  const audio = $('#ls-audio').value || $('#ls-audio-sciezka').value.trim();
  if (!wideoId && !wideoSciezka) { toast('Wybierz wideo albo wpisz ścieżkę.', 'uwaga'); return; }
  if (!audio) { toast('Wybierz plik z głosem albo wpisz ścieżkę.', 'uwaga'); return; }
  const model = $('#ls-model').value, syncMode = $('#ls-tryb').value;
  const w = await potwierdz({
    tytul: 'Uruchomić lipsync?',
    tresc: `<p>Wideo: <b>${esc(wideoId ? 'rolka #' + wideoId : nazwaPliku(wideoSciezka))}</b><br>Głos: <b>${esc(nazwaPliku(audio))}</b><br>Model: <b>${esc(model)}</b>, tryb ${esc(syncMode)}.</p><p class="dialog-uwaga">To wyda kredyty.</p>`,
    ok: 'Start',
  });
  if (!w) return;
  // `model` i `sync_mode` to pola dodatkowe (API.md ich nie wymienia) – backend może je pominąć,
  // wtedy obowiązują ustawienia persony (lipsync_model / lipsync_parametry).
  const dane = { typ: 'lipsync', audio, model, sync_mode: syncMode };
  if (wideoId) dane.id = Number(wideoId); else dane.wideo = wideoSciezka;
  await akcja(dane);
}

function nazwaGlosu(id) {
  const l = state.listy['glosy?dostawca=sync'];
  const g = l && l.pozycje.find(x => x.id === id);
  return g ? (g.nazwa || id) : id;
}

async function startTts() {
  const tekst = $('#tts-tekst').value.trim();
  if (!tekst) { toast('Wpisz tekst do przeczytania.', 'uwaga'); return; }
  const voice = ($('#tts-glos').hidden ? $('#tts-glos-id').value : $('#tts-glos').value).trim();
  if (!voice) { toast('Wybierz głos (albo wpisz voice id).', 'uwaga'); return; }
  const nazwa = $('#tts-nazwa').value.trim();
  const w = await potwierdz({
    tytul: 'Wygenerować głos z tekstu?',
    tresc: `<p>${tekst.length} ${odmiana(tekst.length, 'znak', 'znaki', 'znaków')}, głos <b>${esc(nazwaGlosu(voice))}</b>${nazwa ? `, plik <b>${esc(nazwa)}.mp3</b>` : ''}.</p><p class="dialog-uwaga">To wyda kredyty (sync.so / ElevenLabs).</p>`,
    ok: 'Zrób głos',
  });
  if (!w) return;
  const dane = { typ: 'tts', tekst, voice_id: voice };
  if (nazwa) dane.nazwa = nazwa;
  if (await akcja(dane)) $('#tts-tekst').value = '';
}

async function otworzLipsyncDialog(id) {
  const p = state.pomysly.find(x => Number(x.id) === id);
  if (!state.ustawieniaPelne) {
    try { state.ustawieniaPelne = await api('/api/ustawienia'); } catch (e) { state.ustawieniaPelne = { audio: [] }; }
  }
  const audio = state.ustawieniaPelne.audio || [];
  const sel = $('#ls-dlg-audio');
  let opcje = '<option value="">— wpisz ścieżkę poniżej —</option>';
  if (p && p.audio) opcje += `<option value="${esc(p.audio)}">sparowany z klipem: ${esc(p.audio_nazwa || nazwaPliku(p.audio))}</option>`;
  opcje += audio.map(a => `<option value="${esc(a.sciezka)}">${esc(a.nazwa)}</option>`).join('');
  sel.innerHTML = opcje;
  sel.value = p && p.audio ? p.audio : (audio[0] ? audio[0].sciezka : '');
  $('#ls-dlg-sciezka').hidden = !!sel.value;
  $('#ls-dlg-sciezka').value = '';
  $('#ls-dlg-id').value = String(id);
  $('#ls-dlg-tytul').textContent = `Lipsync dla #${id}${p && p.opis ? ' – ' + p.opis : ''}`;
  otworzDialog('#dlg-lipsync');
}

async function startLipsyncZDialogu() {
  const id = Number($('#ls-dlg-id').value);
  const audio = $('#ls-dlg-audio').value || $('#ls-dlg-sciezka').value.trim();
  if (!audio) { toast('Wybierz plik z głosem albo wpisz ścieżkę.', 'uwaga'); return; }
  $('#dlg-lipsync').close();
  await akcja({ typ: 'lipsync', id, audio }, `Lipsync #${id}`);
}

async function usunLipsync(id) {
  const w = await potwierdz({ tytul: `Usunąć wpis lipsync #${id}?`, tresc: '<p>Z historii zniknie tylko wpis – plik wynikowy zostaje.</p>', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api(`/api/lipsync/${id}`, 'DELETE');
  toast(`Usunięto lipsync #${id}`, 'ok');
  await ladujLipsync();
}

// ---------- Persona (ustawienia) ----------
function zbierzFormularz(form) {
  const dane = {};
  Array.from(form.elements).forEach(el => {
    if (!el.name || el.disabled || el.type === 'submit' || el.type === 'button') return;
    let v;
    if (el.type === 'checkbox') v = el.checked;
    else if (el.type === 'radio') { if (!el.checked) return; v = el.value; }
    else if (el.dataset.typ === 'tri') v = el.value === '' ? null : el.value === 'true';
    else if (el.type === 'number') {
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
    if (info) info.textContent = l.blad ? `Lista niedostępna: ${l.blad} – wpisz ręcznie.` : 'Lista pusta – wpisz ręcznie.';
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

async function ladujPersone() {
  const kont = $('#strona-persona');
  const d = await api('/api/ustawienia');
  state.ustawieniaPelne = d;
  const u = d.ustawienia || {};
  const pr = d.prompty || {};
  const dane = Object.assign({}, u, { prompt_a_tekst: pr.a || '', prompt_b_tekst: pr.b || '', zdjecia_prompty_tekst: pr.zdjecia || '' });
  $$('form[data-ustawienia]', kont).forEach(f => wypelnijFormularz(f, dane));
  przelaczDostawce();
  renderReferencje(d);
  renderFoldery(d);
  renderPromptyInfo();
  // profil: /api/stan może podawać stan.profil (założenie – API.md nie wymienia GET profilu); inaczej pola zostają puste
  const prof = (state.stan && state.stan.profil) || {};
  wypelnijFormularz($('#form-profil'), {
    instagram: prof.instagram || '', opis_stylu: prof.opis_stylu || '',
    cechy: Array.isArray(prof.cechy) ? prof.cechy.join(', ') : (prof.cechy || ''),
  });
  try {
    const b = await api('/api/budzet');
    state.budzet = b;
    const dzis = b.dzis || {};
    $('#limit-higgsfield').value = (dzis.higgsfield && dzis.higgsfield.limit !== undefined) ? dzis.higgsfield.limit : ((b.budzet || {}).max_kredyty_dziennie || 0);
    $('#limit-yapper').value = (dzis.yapper && dzis.yapper.limit !== undefined) ? dzis.yapper.limit : 0;
  } catch (e) { /* limity są dodatkiem */ }
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
    : 'brak – dodaj zdjęcia persony (twarz, sylwetka)';
  $('#referencje-lista').innerHTML = refs.map((r, i) => miniaturka(r, 'referencja', `@Image ${i + 1}`)).join('');
  $('#stroje-licznik').textContent = stroje.length ? `${stroje.length}` : 'brak';
  $('#stroje-lista').innerHTML = stroje.map(s => miniaturka(s, 'stroj', '')).join('');
  $('#lista-strojow').innerHTML = stroje.map(s => `<option value="stroje/${esc(s.nazwa)}">`).join('');
}

function renderFoldery(d) {
  const f = d.foldery || {};
  const wiersze = [['Modelka', f.modelka], ['Wrzutnia', f.wrzutnia], ['Gotowe', f.gotowe], ['Zdjęcia', f.zdjecia], ['Audio', f.audio]].filter(w => w[1]);
  $('#foldery-efektywne').innerHTML = wiersze.length
    ? `<div class="etykieta">Aktualnie używane:</div>` + wiersze.map(([n, s]) => `<div class="folder-wiersz"><span class="etykieta">${esc(n)}</span><span class="sciezka">${esc(s)}</span><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(s)}" title="kopiuj ścieżkę">${ikona('kopiuj')}</button></div>`).join('')
    : '';
}

function renderPromptyInfo() {
  const refs = ((state.ustawieniaPelne && state.ustawieniaPelne.referencje) || []).length;
  const licz = t => (t.match(/@\[Image\s*\d+\]/gi) || []).length;
  const a = licz($('#u-prompt-a').value), b = licz($('#u-prompt-b').value);
  const el = $('#prompty-info'), txt = $('#prompty-info-tekst');
  const czesci = [`Referencji: ${refs}.`, `Prompt A ma ${a} × @Image${a === refs ? ' ✓' : ` (powinno być ${refs})`}.`, `Prompt B ma ${b} × @Image${b === refs + 1 ? ' ✓' : ` (powinno być ${refs + 1}: referencje + strój)`}.`];
  txt.textContent = czesci.join(' ');
  el.className = 'callout ' + ((a === refs && (b === 0 || b === refs + 1)) ? 'info' : 'uwaga');
}

async function zapiszUstawienia(f) {
  const dane = zbierzFormularz(f);
  const btn = f.querySelector('button[type="submit"]');
  if (btn) btn.disabled = true;
  try {
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
    toast('Zapisano ustawienia', 'ok');
    odswiez();
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function zapiszProfil(f) {
  const dane = zbierzFormularz(f);
  const d = await api('/api/profil', 'POST', { instagram: dane.instagram || '', opis_stylu: dane.opis_stylu || '', cechy: dane.cechy || '' });
  if (state.stan && d.profil) state.stan.profil = d.profil;
  toast('Zapisano profil', 'ok');
}

async function zapiszBudzet() {
  await api('/api/budzet', 'POST', { dostawca: 'higgsfield', max_kredyty_dziennie: Math.max(0, Number($('#limit-higgsfield').value) || 0) });
  await api('/api/budzet', 'POST', { dostawca: 'yapper', max_kredyty_dziennie: Math.max(0, Number($('#limit-yapper').value) || 0) });
  toast('Zapisano limity dzienne', 'ok');
  odswiez();
}

async function usunPlik(typ, nazwa) {
  const etykiety = { referencja: 'zdjęcie referencyjne', stroj: 'zdjęcie stroju', audio: 'plik audio' };
  const w = await potwierdz({ tytul: `Usunąć ${etykiety[typ] || 'plik'} „${nazwa}”?`, tresc: typ === 'referencja' ? '<p>Numeracja @Image pozostałych zdjęć się nie zmieni – sprawdź prompty.</p>' : '', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api('/api/pliki/usun', 'POST', { typ, nazwa });
  toast(`Usunięto ${nazwa}`, 'ok');
  if (state.strona === 'persona') await ladujPersone();
  else if (state.strona === 'lipsync') { state.ustawieniaPelne = null; await ladujLipsync(); }
  odswiez();
}

async function odswiezListy() {
  state.listy = {};
  if (state.strona === 'persona') {
    podlaczListe($('#u-yapper-model'), 'modele?dostawca=yapper', true);
    podlaczListe($('#u-zdjecia-model'), 'modele?dostawca=higgsfield&typ=image', true);
    podlaczListe($('#u-tts-glos'), 'glosy?dostawca=sync', true);
    przelaczLipsyncDostawce(true);
  } else if (state.strona === 'lipsync') {
    await ladujLipsync();
  }
  toast('Odświeżam listy modeli i głosów…', 'info');
}

// ---------- Konta ----------
async function ladujKonta() {
  const d = await api('/api/konta');
  state.kontaPelne = d.konta || {};
  renderKonta();
}

function renderKonta() {
  const k = state.kontaPelne || {};
  const kolejnosc = ['higgsfield', 'yapper', 'sync', 'elevenlabs'];
  const ids = kolejnosc.filter(x => k[x]).concat(Object.keys(k).filter(x => !kolejnosc.includes(x)));
  $('#konta-lista').innerHTML = ids.length ? ids.map(id => kartaKonta(id, k[id])).join('') : '<div class="pusto"><b>Brak danych o kontach</b></div>';
}

function kartaKonta(id, k) {
  k = k || {};
  const nazwa = k.nazwa || id;
  let kropka, stan;
  if (k.typ === 'oauth') {
    kropka = k.ok ? 'ok' : 'blad';
    stan = k.komunikat || (k.ok ? 'zalogowany' : 'niezalogowany');
  } else {
    kropka = k.ok === true ? 'ok' : (k.ok === false ? 'blad' : (k.jest ? 'uwaga' : 'info'));
    stan = k.jest ? `klucz zapisany${k.z_env ? ' (ze zmiennej środowiskowej)' : ''}` : 'brak klucza';
    if (k.komunikat) stan += ` · ${k.komunikat}`;
  }
  const wynik = state.testyKont[id];
  const wynikHtml = `<span class="konto-wynik ${wynik ? (wynik.dziala ? 'ok' : 'blad') : ''}" data-test-wynik="${esc(id)}">${wynik ? esc(wynik.komunikat) : ''}</span>`;
  let srodek;
  if (k.typ === 'oauth') {
    srodek = `<div class="konto-jak">${esc(k.jak || '')}</div>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="${esc(id)}">Sprawdź logowanie</button>${wynikHtml}</div>`;
  } else {
    srodek = `${k.jest ? `<div class="konto-maska">klucz: ${esc(k.maska || '••••')}</div>` : ''}
      <form class="rzad" data-konto-form="${esc(id)}"><input type="password" name="klucz" placeholder="${k.jest ? 'wklej nowy klucz, żeby podmienić' : 'wklej klucz API'}" autocomplete="off" aria-label="Klucz API ${esc(nazwa)}"><button class="btn btn-glowny btn-maly" type="submit">Zapisz</button></form>
      <div class="konto-jak">${esc(k.jak || '')}</div>
      <div class="rzad"><button class="btn btn-maly" type="button" data-akcja="konto-test" data-dostawca="${esc(id)}"${k.jest ? '' : ' disabled'}>Testuj</button>${k.jest && !k.z_env ? `<button class="btn btn-maly btn-zly" type="button" data-akcja="konto-usun" data-dostawca="${esc(id)}">Usuń klucz</button>` : ''}${wynikHtml}</div>`;
  }
  return `<div class="karta" data-konto="${esc(id)}">
    <div class="karta-naglowek"><div><h2>${esc(nazwa)}</h2>${k.opis ? `<p>${esc(k.opis)}</p>` : ''}</div><span class="konto-stan"><span class="kropka ${kropka}"></span>${esc(stan)}</span></div>
    ${srodek}
  </div>`;
}

async function zapiszKlucz(dostawca, klucz) {
  if (!klucz) { toast('Wklej klucz.', 'uwaga'); return; }
  const d = await api('/api/konta', 'POST', { dostawca, klucz });
  state.kontaPelne = d.konta || state.kontaPelne;
  delete state.testyKont[dostawca];
  toast('Zapisano klucz', 'ok');
  renderKonta();
  odswiez();
}

async function usunKlucz(dostawca) {
  const w = await potwierdz({ tytul: `Usunąć klucz ${dostawca}?`, tresc: '<p>Dostawca przestanie działać, dopóki nie wkleisz nowego klucza.</p>', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  const d = await api('/api/konta', 'POST', { dostawca, klucz: '' });
  state.kontaPelne = d.konta || state.kontaPelne;
  delete state.testyKont[dostawca];
  toast('Usunięto klucz', 'ok');
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
    toast(`${dostawca}: ${state.testyKont[dostawca].komunikat}`, d.dziala ? 'ok' : 'uwaga');
  } catch (e) {
    state.testyKont[dostawca] = { dziala: false, komunikat: e.message };
    toast(`${dostawca}: ${e.message}`, 'blad');
  } finally {
    if (btn) btn.disabled = false;
    renderKonta();
  }
}

// ---------- Teksty ----------
async function ladujTeksty() {
  const [t, s] = await Promise.all([api('/api/teksty'), api('/api/szablony')]);
  state.teksty = t.teksty || [];
  state.szablony = s.szablony || [];
  renderTeksty();
}

function renderTeksty() {
  const lista = state.teksty.slice().reverse();
  $('#teksty-info').textContent = `${state.teksty.length} ${odmiana(state.teksty.length, 'tekst', 'teksty', 'tekstów')} w banku`;
  $('#teksty-lista').innerHTML = lista.length
    ? lista.map(t => `<div class="tekst-wiersz"><span>${esc(t.tekst)}</span>${t.zrodlo ? `<small>${esc(t.zrodlo)}</small>` : ''}<button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(t.tekst)}" title="kopiuj">${ikona('kopiuj')}</button></div>`).join('')
    : '<div class="pusto"><b>Bank jest pusty</b><span>Wklej podpisy powyżej – fabryka dobierze je do gotowych rolek.</span></div>';
  $('#szablony-lista').innerHTML = state.szablony.length
    ? state.szablony.map(s => `<div class="szablon"><div class="gora"><b>${esc(s.nazwa)}</b><span class="rzad" style="gap:4px"><button class="btn btn-maly btn-tekst" type="button" data-akcja="kopiuj" data-tekst="${esc(s.tresc)}" title="kopiuj">${ikona('kopiuj')}</button><button class="btn btn-maly btn-zly" type="button" data-akcja="usun-szablon" data-nazwa="${esc(s.nazwa)}">Usuń</button></span></div><div class="tresc">${esc(s.tresc)}</div>${(s.placeholdery || []).length ? `<div class="muted" style="font-size:12px">pola: ${s.placeholdery.map(p => `<span class="mono">{${esc(p)}}</span>`).join(', ')}</div>` : ''}</div>`).join('')
    : '<div class="pusto"><b>Brak szablonów</b><span>Szablon to prompt z polami w klamrach do szybkiego wypełniania.</span></div>';
}

async function dodajTeksty() {
  const pole = $('#teksty-pole');
  if (!pole.value.trim()) { toast('Wklej teksty.', 'uwaga'); return; }
  const d = await api('/api/teksty', 'POST', { teksty: pole.value, zrodlo: $('#teksty-zrodlo').value.trim() });
  pole.value = '';
  toast(`Dodano ${d.dodano} ${odmiana(d.dodano, 'tekst', 'teksty', 'tekstów')} (duplikaty pominięte)`, 'ok');
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
    toast('Brak nieużytych tekstów – dodaj nowe do banku.', 'uwaga');
  }
}

async function dodajSzablon() {
  const nazwa = $('#szablon-nazwa').value.trim(), tresc = $('#szablon-tresc').value.trim();
  if (!nazwa || !tresc) { toast('Podaj nazwę i treść szablonu.', 'uwaga'); return; }
  await api('/api/szablony', 'POST', { nazwa, tresc });
  $('#szablon-nazwa').value = ''; $('#szablon-tresc').value = '';
  toast('Zapisano szablon', 'ok');
  await ladujTeksty();
}

async function usunSzablon(nazwa) {
  const w = await potwierdz({ tytul: `Usunąć szablon „${nazwa}”?`, tresc: '', ok: 'Usuń', klasa: 'btn-zly' });
  if (!w) return;
  await api('/api/szablony/' + encodeURIComponent(nazwa), 'DELETE');
  toast('Usunięto szablon', 'ok');
  await ladujTeksty();
}

// ---------- Dziennik ----------
async function ladujDziennik() {
  const typ = $('#dz-typ').value;
  const q = new URLSearchParams({ ile: '200' });
  if (typ) q.set('typ', typ);
  const d = await api('/api/dziennik?' + q.toString());
  state.dziennik = d.wpisy || [];
  renderDziennik();
  if (!state.timery.dziennik && state.strona === 'dziennik') {
    state.timery.dziennik = setInterval(() => { ladujDziennik().catch(() => {}); }, 10000);
  }
}

function daneDziennika(d) {
  if (!d || typeof d !== 'object') return '';
  return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === 'object' && v !== null ? JSON.stringify(v) : v}`).join(', ');
}

function renderDziennik() {
  const sel = $('#dz-modelka');
  const biez = sel.value;
  const opcje = '<option value="">wszystkie persony</option>' + state.modelki.map(m => `<option value="${esc(m.slug)}">${esc(m.nazwa || m.slug)}</option>`).join('');
  if (sel.innerHTML !== opcje) { sel.innerHTML = opcje; sel.value = biez; }
  const modelka = sel.value;
  // filtr persony po stronie panelu (API przyjmuje tylko ile/typ); wpisy bez persony są wspólne, więc zostają
  const wpisy = state.dziennik.filter(w => !modelka || !w.modelka || w.modelka === modelka).slice().reverse();
  $('#dziennik-tabela').innerHTML = wpisy.length
    ? wpisy.map(w => `<tr><td class="czas" title="${esc(formatData(w.czas))}">${esc(formatCzas(w.czas))}</td><td><span class="rzad" style="gap:6px;flex-wrap:nowrap"><span class="kropka ${esc(w.typ || 'info')}"></span>${esc(w.typ === 'blad' ? 'błąd' : (w.typ || ''))}</span></td><td class="nowrap">${esc(w.modelka || '')}</td><td>${esc(w.tekst)}${w.dane ? ` <small class="muted">${esc(daneDziennika(w.dane))}</small>` : ''}</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">Brak wpisów.</td></tr>';
}

// ============================================================ 7. DIALOGI, UPLOAD, ZADANIA
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
  toast('Skopiowano do schowka', 'info');
}

async function akcja(dane, opis) {
  try {
    await api('/api/akcja', 'POST', dane);
    toast(`Uruchomiono: ${opis || ETYKIETY_AKCJI[dane.typ] || dane.typ}`, 'info');
    state.konsola.start = null; // następny odczyt logu zacznie od zera
    otworzKonsole(true);
    startKonsoli();
    odswiez();
    return true;
  } catch (e) {
    bladToast(e);
    return false;
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
    const zapisane = d.zapisane || [];
    const n = zapisane.length;
    if (typ === 'zrodlo') {
      toast(`Zapisano ${n} ${odmiana(n, 'filmik', 'filmiki', 'filmików')} we wrzutni. Teraz: Skanuj wrzutnię.`, 'ok', { akcja: 'Skanuj', cb: () => akcja({ typ: 'skanuj' }) });
    } else {
      toast(`Zapisano: ${zapisane.join(', ') || n}`, 'ok');
    }
    if ((typ === 'referencja' || typ === 'stroj') && state.strona === 'persona') ladujPersone().catch(bladToast);
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
  if (!nazwa) { toast('Podaj nazwę persony.', 'uwaga'); return; }
  await api('/api/modelki', 'POST', { nazwa, instagram: $('#np-ig').value.trim() });
  $('#dlg-persona').close();
  toast(`Utworzono personę „${nazwa}”. Teraz dodaj zdjęcia referencyjne i prompty.`, 'ok');
  wyczyscCachePersony();
  await odswiez();
  if (location.hash.replace(/^#/, '').split('?')[0] === 'persona') ladujStrone('persona');
  else location.hash = '#persona';
}

async function zmienPersone(slug) {
  if (!slug || slug === state.aktywna) return;
  await api('/api/modelki/aktywna', 'POST', { slug });
  wyczyscCachePersony();
  await odswiez();
  if (state.stan) ladujStrone(state.strona);
}

async function przelaczAutopilot(wlacz) {
  try {
    const d = await api('/api/autopilot', 'POST', { wlacz });
    state.autopilot = d.autopilot || state.autopilot;
    toast(wlacz ? 'Autopilot włączony – pętla działa w tle.' : 'Autopilot wyłączony.', wlacz ? 'ok' : 'info');
  } catch (e) {
    bladToast(e);
  }
  renderAutopilot();
}

// ============================================================ 8. ZDARZENIA
document.addEventListener('click', async e => {
  const el = e.target.closest('[data-akcja]');
  if (!el) return;
  const nazwa = el.dataset.akcja;
  const id = el.dataset.id !== undefined ? Number(el.dataset.id) : null;
  try {
    switch (nazwa) {
      case 'nowa-persona': $('#np-nazwa').value = ''; $('#np-ig').value = ''; otworzDialog('#dlg-persona'); $('#np-nazwa').focus(); break;
      case 'zamknij-dialog': { const d = el.closest('dialog'); if (d) d.close(); break; }
      case 'odswiez-saldo': el.disabled = true; try { await odswiez(true); toast('Saldo odświeżone', 'info'); } finally { el.disabled = false; } break;
      case 'konsola-przelacz': otworzKonsole(!state.konsola.otwarta); break;
      case 'stop': await api('/api/zadanie/stop', 'POST', {}); toast('Zatrzymuję po bieżącej pozycji…', 'uwaga'); break;
      case 'kopiuj': await kopiuj(el.dataset.tekst !== undefined ? el.dataset.tekst : (el.dataset.cel ? $(el.dataset.cel).textContent : '')); break;
      // pulpit
      case 'skanuj': await akcja({ typ: 'skanuj' }); break;
      case 'koszt': await policzKosztWszystkich(); break;
      case 'generuj-wszystko': await generujWszystko(); break;
      case 'autopilot-raz': await akcja({ typ: 'autopilot_raz' }); break;
      // kolejka
      case 'filtr': state.filtr = el.dataset.status || 'wszystkie'; renderKolejka(); break;
      case 'koszt-pomysl': await akcja({ typ: 'koszt', ids: [id] }, `Liczenie kosztu #${id}`); break;
      case 'generuj-pomysl': await generujPomysl(id); break;
      case 'ponow': await api(`/api/pomysly/${id}/ponow`, 'POST', {}); toast(`#${id} wraca do kolejki jako nowy`, 'ok'); await ladujKolejke(false); odswiez(); break;
      case 'odtworz': if (state.odtwarzane.has(id)) state.odtwarzane.delete(id); else state.odtwarzane.add(id); renderKolejka(); break;
      case 'pierz': await akcja({ typ: 'pierz', id }, `Pranie #${id} (Media Tool)`); break;
      case 'lipsync-pomysl': await otworzLipsyncDialog(id); break;
      case 'podpis': await akcja({ typ: 'podpis', id }, `Podpis #${id}`); break;
      case 'usun-pomysl': await usunPomysl(id); break;
      case 'zapisz-prompt': await zapiszPrompt(id); break;
      // zdjęcia, lipsync
      case 'usun-zdjecie': await usunZdjecie(id); break;
      case 'usun-lipsync': await usunLipsync(id); break;
      // persona
      case 'usun-plik': await usunPlik(el.dataset.typ, el.dataset.nazwa); break;
      case 'odswiez-listy': await odswiezListy(); break;
      // konta
      case 'konto-test': await testujKonto(el.dataset.dostawca, el); break;
      case 'konto-usun': await usunKlucz(el.dataset.dostawca); break;
      // teksty
      case 'losuj-tekst': await losujTekst(); break;
      case 'usun-szablon': await usunSzablon(el.dataset.nazwa); break;
      // dziennik
      case 'odswiez-dziennik': await ladujDziennik(); toast('Dziennik odświeżony', 'info'); break;
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
    else if (f.id === 'form-tts') await startTts();
    else if (f.id === 'form-lipsync-dialog') await startLipsyncZDialogu();
    else if (f.hasAttribute('data-ustawienia')) await zapiszUstawienia(f);
    else if (f.id === 'form-profil') await zapiszProfil(f);
    else if (f.id === 'form-budzet') await zapiszBudzet();
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
  else if (el.name === 'dostawca' && el.closest('#form-generowanie')) przelaczDostawce();
  else if (el.id === 'u-lipsync-dostawca') przelaczLipsyncDostawce();
  else if (el.id === 'ls-wideo') $('#ls-wideo-sciezka').hidden = !!el.value;
  else if (el.id === 'ls-audio') $('#ls-audio-sciezka').hidden = !!el.value;
  else if (el.id === 'ls-dlg-audio') $('#ls-dlg-sciezka').hidden = !!el.value;
  else if (el.id === 'dz-typ') ladujDziennik().catch(bladToast);
  else if (el.id === 'dz-modelka') renderDziennik();
  else if (el.id === 'plik-ukryty') { if (state.uploadTyp && el.files.length) wyslijPliki(state.uploadTyp, el.files); }
});

document.addEventListener('input', e => {
  const el = e.target;
  if (el instanceof Element && (el.id === 'u-prompt-a' || el.id === 'u-prompt-b')) renderPromptyInfo();
});

// rozwijanie promptów w kolejce (toggle nie bąbelkuje – faza przechwytywania)
document.addEventListener('toggle', e => {
  const d = e.target;
  if (!(d instanceof Element) || !d.matches('details.prompt')) return;
  const id = Number(d.dataset.id);
  if (d.open) state.otwartePrompty.add(id); else state.otwartePrompty.delete(id);
}, true);

// strefy upload: klik / klawiatura / drag & drop
document.addEventListener('click', e => {
  const s = e.target.closest('.strefa[data-upload]');
  if (s && !e.target.closest('button')) wybierzPliki(s.dataset.upload);
});
document.addEventListener('keydown', e => {
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
  await odswiez();
  zastosujHash();
  setInterval(() => { odswiez(false); }, 5000);
  setInterval(() => { if (state.zadanie && state.zadanie.trwa) renderKonsolaStan(); }, 1000);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
else start();
