(() => {
  const stripMoney = (value) => String(value ?? '').replace(/[٬٫,\s]/g, '').replace(/[^0-9.-]/g, '');
  const num = (value) => {
    const n = Number(stripMoney(value));
    return Number.isFinite(n) ? n : 0;
  };
  const fmtMoney = (value) => {
    const rounded = Math.round(value || 0);
    const sign = rounded < 0 ? '-' : '';
    return sign + String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  };
  const SCROLL_KEY = 'darma-report-v4-scroll';
  const PICKER_KEY = 'darma-report-v4-material-picker';

  function recalc(row) {
    const qty = num(row.querySelector('.raw-quantity')?.value);
    const price = num(row.querySelector('.raw-unit-price')?.value);
    const out = row.querySelector('.raw-line-total');
    if (out) out.textContent = fmtMoney(qty * price);
  }

  function bindCalc(root = document) {
    root.querySelectorAll('.raw-calc-row').forEach((row) => {
      if (row.dataset.rawCalcBound === '1') return;
      row.dataset.rawCalcBound = '1';
      row.querySelectorAll('.raw-quantity,.raw-unit-price').forEach((input) => {
        input.addEventListener('input', () => recalc(row));
      });
      recalc(row);
    });
  }

  function bindPicker(root = document) {
    const panel = root.querySelector?.('#raw-materials') || document.querySelector('#raw-materials');
    if (!panel || panel.dataset.pickerBound === '1') return;
    panel.dataset.pickerBound = '1';

    const kindButtons = [...panel.querySelectorAll('[data-raw-kind]')];
    const locationButtons = [...panel.querySelectorAll('[data-raw-location]')];
    const locationPicker = panel.querySelector('#rawLocationPicker');
    const panes = [...panel.querySelectorAll('[data-pane]')];
    let kind = '';

    const hidePanes = () => panes.forEach((pane) => pane.classList.add('d-none'));
    const clearLocation = () => locationButtons.forEach((btn) => btn.classList.remove('active'));
    const storeState = (location = '') => {
      try { sessionStorage.setItem(PICKER_KEY, JSON.stringify({ kind, location })); } catch (_) {}
    };

    const chooseKind = (nextKind, shouldScroll = true) => {
      kind = nextKind;
      kindButtons.forEach((b) => b.classList.toggle('active', b.dataset.rawKind === kind));
      clearLocation();
      hidePanes();
      locationButtons.forEach((btn) => {
        const fabricOnly = btn.dataset.fabricOnly === '1';
        btn.classList.toggle('d-none', fabricOnly && kind !== 'fabric');
      });
      locationPicker?.classList.remove('d-none');
      storeState('');
      if (shouldScroll) locationPicker?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    const chooseLocation = (location, shouldScroll = true) => {
      if (!kind) return;
      const btn = locationButtons.find((b) => b.dataset.rawLocation === location && !b.classList.contains('d-none'));
      if (!btn) return;
      clearLocation();
      btn.classList.add('active');
      hidePanes();
      const pane = panel.querySelector(`[data-pane="${kind}-${location}"]`);
      pane?.classList.remove('d-none');
      storeState(location);
      if (shouldScroll) pane?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    kindButtons.forEach((btn) => btn.addEventListener('click', () => chooseKind(btn.dataset.rawKind, true)));
    locationButtons.forEach((btn) => btn.addEventListener('click', () => chooseLocation(btn.dataset.rawLocation, true)));

    try {
      const saved = JSON.parse(sessionStorage.getItem(PICKER_KEY) || 'null');
      if (saved?.kind) {
        chooseKind(saved.kind, false);
        if (saved.location) chooseLocation(saved.location, false);
      }
    } catch (_) {}
  }

  function bindEditRows(root = document) {
    root.querySelectorAll('.raw-edit-toggle,.raw-edit-cancel').forEach((button) => {
      if (button.dataset.editBound === '1') return;
      button.dataset.editBound = '1';
      button.addEventListener('click', () => {
        const target = document.getElementById(button.dataset.editTarget || '');
        if (!target) return;
        const willOpen = target.classList.contains('d-none');
        document.querySelectorAll('.raw-edit-row:not(.d-none)').forEach((row) => {
          if (row !== target) row.classList.add('d-none');
        });
        target.classList.toggle('d-none', !willOpen);
        if (willOpen) target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      });
    });
  }

  function bindReportScrollMemory() {
    if (window.location.pathname !== '/report/') return;
    document.querySelectorAll('main form[method="post"], main form[method="POST"]').forEach((form) => {
      if (form.dataset.reportScrollBound === '1') return;
      form.dataset.reportScrollBound = '1';
      form.addEventListener('submit', () => {
        try { sessionStorage.setItem(SCROLL_KEY, String(window.scrollY)); } catch (_) {}
      });
    });
  }

  function restoreReportScroll() {
    if (window.location.pathname !== '/report/') return;
    let saved = null;
    try {
      saved = sessionStorage.getItem(SCROLL_KEY);
      sessionStorage.removeItem(SCROLL_KEY);
    } catch (_) {}
    if (saved === null || saved === '') return;
    const y = Number(saved) || 0;
    const restore = () => window.scrollTo(0, y);
    requestAnimationFrame(() => requestAnimationFrame(restore));
    setTimeout(restore, 120);
    setTimeout(restore, 320);
  }

  async function injectFinancialSummary() {
    if (window.location.pathname !== '/report/' || document.querySelector('.financial-extra-row')) return;
    const label = [...document.querySelectorAll('.subheader')].find((el) =>
      (el.textContent || '').includes('حساب بانک و اشخاص')
    );
    const row = label?.closest('.row');
    if (!row) return;
    try {
      const response = await fetch('/report/financial-summary/', { credentials: 'same-origin' });
      if (!response.ok) return;
      row.insertAdjacentHTML('afterend', await response.text());
    } catch (_) {}
  }

  function patchCapitalLabels() {
    const formula = document.querySelector('.capital-formula');
    if (formula) formula.textContent = 'حساب‌ها + کالای آماده + مواد اولیه + کالای سرمایه‌ای + طلب دیجی‌کالا − بدهی تکوین';
    document.querySelectorAll('.card').forEach((card) => {
      const heading = card.querySelector('h3,.card-title');
      if ((heading?.textContent || '').trim() !== 'کالای سرمایه‌ای') return;
      const subtitle = card.querySelector('.text-secondary');
      if (subtitle) subtitle.textContent = 'ارزش این بخش داخل سرمایه کل محاسبه می‌شود.';
    });
  }

  function bind(root = document) {
    bindCalc(root);
    bindPicker(root);
    bindEditRows(root);
    bindReportScrollMemory();
  }

  if ('scrollRestoration' in history && window.location.pathname === '/report/') history.scrollRestoration = 'manual';
  document.addEventListener('DOMContentLoaded', async () => {
    bind();
    patchCapitalLabels();
    await injectFinancialSummary();
    restoreReportScroll();
  });
  document.body?.addEventListener('htmx:afterSwap', (event) => bind(event.target));
})();
