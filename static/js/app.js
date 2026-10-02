/* Ledgerfolio Showcase behaviour: display preferences, navigation, motion and
   the Portfolio Assistant chat widget. */

const root = document.documentElement;
const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];

/* ---------- Display preferences ---------------------------------------------
   Saved in this browser only. The same values are applied by a tiny inline
   script in <head> before first paint, so there is no flash of the wrong theme. */

const PREFS_KEY = 'lf:prefs';
const DEFAULTS = { theme: 'auto', vision: 'standard', contrast: 'normal', text: 'md', motion: 'auto' };
const systemLight = matchMedia('(prefers-color-scheme: light)');

function loadPrefs() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}

let prefs = loadPrefs();

function setAttribute(name, value, fallback) {
  if (value === fallback) delete root.dataset[name];
  else root.dataset[name] = value;
}

function applyPrefs() {
  root.dataset.theme = prefs.theme === 'auto' ? (systemLight.matches ? 'light' : 'dark') : prefs.theme;
  setAttribute('vision', prefs.vision, 'standard');
  setAttribute('contrast', prefs.contrast, 'normal');
  setAttribute('text', prefs.text, 'md');
  setAttribute('motion', prefs.motion, 'auto');
  $$('#a11y-panel input[type="radio"]').forEach((input) => {
    input.checked = prefs[input.name] === input.value;
  });
  const themeColor = $('meta[name="theme-color"]');
  if (themeColor) themeColor.content = getComputedStyle(root).getPropertyValue('--bg').trim();
  window.dispatchEvent(new CustomEvent('lf:appearance'));
}

function setPref(name, value) {
  prefs = { ...prefs, [name]: value };
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch { /* private mode */ }
  applyPrefs();
}

function motionReduced() {
  if (prefs.motion === 'reduce') return true;
  return matchMedia('(prefers-reduced-motion: reduce)').matches;
}

systemLight.addEventListener('change', () => { if (prefs.theme === 'auto') applyPrefs(); });

function initPreferences() {
  applyPrefs();

  $('#theme-toggle')?.addEventListener('click', () => {
    setPref('theme', root.dataset.theme === 'light' ? 'dark' : 'light');
  });

  const panel = $('#a11y-panel');
  const button = $('#a11y-toggle');
  if (!panel || !button) return;

  const open = (state) => {
    panel.classList.toggle('is-open', state);
    panel.inert = !state;
    button.setAttribute('aria-expanded', String(state));
    if (state) $('input:checked', panel)?.focus();
  };
  open(false);
  button.addEventListener('click', () => open(!panel.classList.contains('is-open')));
  panel.addEventListener('change', (event) => {
    if (event.target.matches('input[type="radio"]')) setPref(event.target.name, event.target.value);
  });
  $('#a11y-reset')?.addEventListener('click', () => {
    prefs = { ...DEFAULTS };
    try { localStorage.removeItem(PREFS_KEY); } catch { /* private mode */ }
    applyPrefs();
  });
  $('#a11y-close')?.addEventListener('click', () => { open(false); button.focus(); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && panel.classList.contains('is-open')) { open(false); button.focus(); }
  });
  document.addEventListener('pointerdown', (event) => {
    if (panel.classList.contains('is-open') && !panel.contains(event.target) && !button.contains(event.target)) {
      open(false);
    }
  });
}

/* ---------- Navigation -------------------------------------------------------- */

function initNav() {
  const menuButton = $('#menu-toggle');
  const links = $('#nav-links');
  menuButton?.addEventListener('click', () => {
    const state = !links.classList.contains('is-open');
    links.classList.toggle('is-open', state);
    menuButton.setAttribute('aria-expanded', String(state));
  });

  // Browsers without cross-document view transitions get a quick fade instead.
  if (!('CSSViewTransitionRule' in window)) {
    root.classList.add('no-vt');
    document.addEventListener('click', (event) => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || link.target || link.hasAttribute('download')) return;
      const url = new URL(link.href);
      if (url.origin !== location.origin || url.pathname === location.pathname || motionReduced()) return;
      event.preventDefault();
      root.classList.add('is-leaving');
      setTimeout(() => { location.href = link.href; }, 180);
    });
    window.addEventListener('pageshow', () => root.classList.remove('is-leaving'));
  }
}

/* ---------- Motion: reveal on scroll, count-up, card tilt ----------------------- */

function initMotion() {
  const revealables = $$('.reveal');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    revealables.forEach((element) => observer.observe(element));
  } else {
    revealables.forEach((element) => element.classList.add('is-in'));
  }

  $$('[data-count]').forEach((element) => {
    const target = Number(element.dataset.count);
    if (!Number.isFinite(target) || motionReduced() || !('IntersectionObserver' in window)) return;
    element.textContent = '0';
    new IntersectionObserver(([entry], observer) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const started = performance.now();
      const duration = 1400;
      const tick = (now) => {
        const progress = Math.min(1, (now - started) / duration);
        const eased = 1 - Math.pow(1 - progress, 4);
        element.textContent = Math.round(target * eased).toLocaleString();
        if (progress < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, { threshold: 0.6 }).observe(element);
  });

  if (matchMedia('(hover: hover) and (pointer: fine)').matches) {
    $$('.card').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const box = card.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width;
        const y = (event.clientY - box.top) / box.height;
        card.style.setProperty('--mx', `${x * 100}%`);
        card.style.setProperty('--my', `${y * 100}%`);
        if (motionReduced()) return;
        card.classList.add('is-tilting');
        card.style.setProperty('--ry', `${(x - 0.5) * 7}deg`);
        card.style.setProperty('--rx', `${(0.5 - y) * 6}deg`);
      });
      card.addEventListener('pointerleave', () => {
        card.classList.remove('is-tilting');
        card.style.setProperty('--rx', '0deg');
        card.style.setProperty('--ry', '0deg');
      });
    });
  }
}

/* ---------- Small helpers: copy buttons, screenshot lightbox --------------------- */

function initHelpers() {
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      const label = button.querySelector('[data-copy-label]') || button;
      const original = label.textContent;
      label.textContent = 'Copied';
      setTimeout(() => { label.textContent = original; }, 1600);
    } catch { /* clipboard blocked: the text is still selectable on the page */ }
  });

  const lightbox = $('#lightbox');
  if (lightbox) {
    const image = $('img', lightbox);
    $$('.shot').forEach((shot) => shot.addEventListener('click', () => {
      image.src = shot.dataset.full;
      image.alt = shot.dataset.caption || '';
      lightbox.showModal();
    }));
    lightbox.addEventListener('click', (event) => {
      if (event.target === lightbox || event.target.closest('[data-close]')) lightbox.close();
    });
  }
}

/* ---------- 3D ------------------------------------------------------------------ */

function initScenes() {
  if (!$('canvas[data-scene]')) return;
  const probe = document.createElement('canvas');
  if (!(probe.getContext('webgl2') || probe.getContext('webgl'))) return;
  // Loaded after first paint so the page is readable before the 3D arrives.
  const start = () => import('./scene.js').then((scene) => scene.init()).catch(() => {});
  if ('requestIdleCallback' in window) requestIdleCallback(start, { timeout: 1200 });
  else setTimeout(start, 200);
}

/* ---------- Portfolio Assistant --------------------------------------------------- */

const CHAT_KEY = 'lf:chat';
const GREETING = {
  role: 'bot',
  text: "Hello! I'm the Portfolio Assistant. Ask me about the systems here, how a project goes, "
    + "how receipts are verified, or tell me if you'd like a system built.",
};
const STARTERS = ['What systems have you built?', 'How does working with you go?',
  'How do I verify a receipt?', 'I want a system built'];

function initChat() {
  const chat = $('#chat');
  const fab = $('#chat-fab');
  if (!chat || !fab) return;
  const log = $('#chat-log');
  const form = $('#chat-form');
  const input = $('#chat-input');
  const send = $('#chat-send');
  const suggest = $('#chat-suggest');
  const endpoint = chat.dataset.endpoint;

  let state = { open: false, messages: [], suggestions: STARTERS };
  try { state = { ...state, ...JSON.parse(sessionStorage.getItem(CHAT_KEY) || '{}') }; } catch { /* fresh start */ }
  const save = () => {
    state.messages = state.messages.slice(-40);
    try { sessionStorage.setItem(CHAT_KEY, JSON.stringify(state)); } catch { /* private mode */ }
  };

  const csrfToken = () => document.cookie.split('; ').find((c) => c.startsWith('csrftoken='))?.split('=')[1]
    || $('meta[name="csrf-token"]')?.content || '';

  function bubble(message, animate = true) {
    const element = document.createElement('div');
    element.className = `msg msg--${message.role}`;
    if (!animate) element.style.animation = 'none';
    element.textContent = message.text;   // textContent: replies are never treated as HTML
    if (message.links?.length) {
      const links = document.createElement('div');
      links.className = 'msg__links';
      message.links.forEach((link) => {
        // Only same-site paths are ever turned into links.
        if (typeof link.url !== 'string' || !link.url.startsWith('/') || link.url.startsWith('//')) return;
        const anchor = document.createElement('a');
        anchor.href = link.url;
        anchor.textContent = link.label;
        links.append(anchor);
      });
      element.append(links);
    }
    log.append(element);
    log.scrollTop = log.scrollHeight;
    return element;
  }

  function renderSuggestions() {
    suggest.replaceChildren(...(state.suggestions || []).map((text) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = text;
      button.addEventListener('click', () => ask(text));
      return button;
    }));
    suggest.hidden = !state.suggestions?.length;
  }

  function open(next) {
    state.open = next;
    chat.classList.toggle('is-open', next);
    chat.inert = !next;
    fab.classList.toggle('is-hidden', next);
    fab.setAttribute('aria-expanded', String(next));
    if (next) {
      if (!state.messages.length) { state.messages.push(GREETING); bubble(GREETING); }
      log.scrollTop = log.scrollHeight;
      setTimeout(() => input.focus(), 250);
    }
    save();
  }

  async function ask(text) {
    text = text.trim();
    if (!text || send.disabled) return;
    const mine = { role: 'user', text };
    state.messages.push(mine);
    bubble(mine);
    input.value = '';
    state.suggestions = [];
    renderSuggestions();
    send.disabled = true;

    const typing = document.createElement('div');
    typing.className = 'msg msg--bot';
    typing.innerHTML = '<span class="typing" aria-label="Assistant is typing"><i></i><i></i><i></i></span>';
    log.append(typing);
    log.scrollTop = log.scrollHeight;

    let answer;
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
        credentials: 'same-origin',
        body: JSON.stringify({ message: text }),
      });
      const data = await response.json();
      answer = response.ok
        ? { role: 'bot', text: data.reply, links: data.links }
        : { role: 'bot', text: data.detail || 'Something went wrong. Please try again.' };
      state.suggestions = response.ok ? data.suggestions : [];
    } catch {
      answer = { role: 'bot', text: "I couldn't reach the server. Please check your connection and try again." };
    }
    // A short pause reads more naturally than an instant reply.
    await new Promise((resolve) => setTimeout(resolve, motionReduced() ? 0 : 350));
    typing.remove();
    state.messages.push(answer);
    bubble(answer);
    renderSuggestions();
    send.disabled = false;
    save();
    input.focus();
  }

  state.messages.forEach((message) => bubble(message, false));
  renderSuggestions();
  open(Boolean(state.open));

  fab.addEventListener('click', () => open(true));
  $('#chat-close').addEventListener('click', () => { open(false); fab.focus(); });
  form.addEventListener('submit', (event) => { event.preventDefault(); ask(input.value); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.open && chat.contains(document.activeElement)) { open(false); fab.focus(); }
  });
  $$('[data-chat-open]').forEach((trigger) => trigger.addEventListener('click', (event) => {
    event.preventDefault();
    open(true);
    if (trigger.dataset.chatSay) ask(trigger.dataset.chatSay);
  }));
}

initPreferences();
initNav();
initMotion();
initHelpers();
initChat();
initScenes();
