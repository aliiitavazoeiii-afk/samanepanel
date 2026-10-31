(() => {
  const stripMoney = (value) => String(value ?? '').replace(/[٬٫,\s]/g, '').replace(/[^0-9.-]/g, '');
  const num = (value) => {
    const n = Number(stripMoney(value));
    return Number.isFinite(n) ? n : 0;
  };
  const fmt = (value) => {
    const rounded = Math.round(value || 0);
    const sign = rounded < 0 ? '-' : '';
    return sign + String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  };
  const SCROLL_KEY = 'darma-report-scroll-y';

  function recalc(row) {
    const qty = num(row.querySelector('.raw-quantity')?.value);
    const price = num(row.querySelector('.raw-unit-price')?.value);
    const total = qty * price;
    const output = row.querySelector('.raw-line-total');
    if (output) {
      output.textContent = fmt(total);
      output.dataset.value = String(Math.round(total));
    }
  }

  function bind(root = document) {
    root.querySelectorAll('.raw-calc-row').forEach((row) => {
      if (row.dataset.rawCalcBound === '1') return;
      row.dataset.rawCalcBound = '1';
      row.querySelectorAll('.raw-quantity,.raw-unit-price').forEach((input) => {
        input.addEventListener('input', () => recalc(row));
      });
      recalc(row);
    });
  }

  function bindScrollMemory() {
    document.querySelectorAll('form[action*="/report/manual/"]').forEach((form) => {
      if (form.dataset.scrollMemory === '1') return;
      form.dataset.scrollMemory = '1';
      form.addEventListener('submit', () => {
        try { sessionStorage.setItem(SCROLL_KEY, String(window.scrollY)); } catch (_) {}
      });
    });
  }

  function restoreScroll() {
    let saved = null;
    try {
      saved = sessionStorage.getItem(SCROLL_KEY);
      sessionStorage.removeItem(SCROLL_KEY);
    } catch (_) {}
    if (saved !== null && saved !== '') {
      requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({ top: Number(saved) || 0, behavior: 'instant' })));
    }
  }

  async function injectFinancialSummary() {
    if (document.querySelector('.financial-extra-row')) return;
    const bankLabel = [...document.querySelectorAll('.subheader')].find((el) =>
      (el.textContent || '').includes('حساب بانک و اشخاص')
    );
    const row = bankLabel?.closest('.row');
    if (!row) return;
    try {
      const response = await fetch('/report/financial-summary/', { credentials: 'same-origin' });
      if (!response.ok) return;
      const html = await response.text();
      row.insertAdjacentHTML('afterend', html);
    } catch (_) {}
  }

  document.addEventListener('DOMContentLoaded', async () => {
    bind();
    bindScrollMemory();
    await injectFinancialSummary();
    restoreScroll();
  });
  document.body?.addEventListener('htmx:afterSwap', (event) => {
    bind(event.target);
    bindScrollMemory();
  });
})();
