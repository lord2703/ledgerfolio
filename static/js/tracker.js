// Ledgerfolio Tracker: the slide-out menu, dropdowns, phone-friendly tables,
// the "/" search shortcut, the show-password button and copy-link buttons.
(() => {
  const body = document.body;
  const DROPDOWNS = 'details.lf-filter, details.lf-user';

  /* Slide-out navigation on tablets and phones */
  const menuButton = document.querySelector('[data-nav-open]');
  function setNav(open) {
    body.classList.toggle('lf-nav-open', open);
    menuButton?.setAttribute('aria-expanded', String(open));
    if (open) document.querySelector('#lf-sidebar a, #lf-sidebar input')?.focus({ preventScroll: true });
  }
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-nav-open]')) setNav(true);
    else if (event.target.closest('[data-nav-close]')) setNav(false);
  });
  matchMedia('(min-width: 1081px)').addEventListener('change', (query) => { if (query.matches) setNav(false); });

  /* Dropdowns (filters, account menu): one open at a time, close on outside click */
  function closeDropdowns(except) {
    document.querySelectorAll(DROPDOWNS).forEach((item) => { if (item !== except) item.open = false; });
  }
  document.addEventListener('toggle', (event) => {
    if (event.target.matches?.(DROPDOWNS) && event.target.open) closeDropdowns(event.target);
  }, true);
  document.addEventListener('click', (event) => {
    if (!event.target.closest(DROPDOWNS)) closeDropdowns();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const open = document.querySelector(`${DROPDOWNS.split(', ').map((s) => `${s}[open]`).join(', ')}`);
    if (open) { closeDropdowns(); open.querySelector('summary')?.focus(); return; }
    if (body.classList.contains('lf-nav-open')) { setNav(false); menuButton?.focus(); }
  });

  /* Phone-friendly tables: give every cell its column name, shown when rows become cards.
     Inline rows added later with "Add another" are copies of a labelled template row. */
  document.querySelectorAll('#result_list, .inline-group .tabular table').forEach((table) => {
    const labels = [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim());
    table.querySelectorAll('tbody tr:not(.add-row):not(.row-form-errors)').forEach((row) => {
      [...row.children].forEach((cell, index) => {
        if (labels[index]) cell.dataset.label = labels[index];
      });
    });
  });

  /* Say what a list's search box looks through, e.g. "Search projects…" */
  const searchbar = document.getElementById('searchbar');
  const heading = document.querySelector('.lf-page-head h1');
  if (searchbar && heading && !searchbar.placeholder) {
    searchbar.placeholder = `Search ${heading.textContent.trim().toLowerCase()}…`;
  }

  /* Press "/" to search, unless you are typing somewhere */
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    const search = [...document.querySelectorAll('.lf-search input')].find((input) => input.offsetParent);
    if (search) { event.preventDefault(); search.focus(); search.select(); }
  });

  /* Show or hide the password on the sign-in page */
  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-password-toggle]');
    if (!toggle) return;
    const input = toggle.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(show));
    toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    input.focus();
  });

  /* Copy a receipt's verify link */
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('.lf-copy');
    if (!button) return;
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = 'Copied';
    } catch {
      button.textContent = 'Select and copy the link';
    }
    setTimeout(() => { button.textContent = original; }, 1800);
  });
})();
