(() => {
  const SEP = '٬';

  function raw(value) {
    const text = String(value ?? '').trim();
    const negative = text.startsWith('-');
    const digits = text.replace(/[٬٫,\s]/g, '').replace(/[^0-9]/g, '');
    return (negative ? '-' : '') + digits;
  }

  function grouped(value) {
    const cleaned = raw(value);
    if (!cleaned || cleaned === '-') return cleaned;
    const negative = cleaned.startsWith('-');
    const digits = negative ? cleaned.slice(1) : cleaned;
    const out = digits.replace(/\B(?=(\d{3})+(?!\d))/g, SEP);
    return (negative ? '-' : '') + out;
  }

  function bind(root = document) {
    root.querySelectorAll('input.money, input.money-input').forEach((input) => {
      if (input.dataset.groupBound === '1' || input.type === 'number') return;
      input.dataset.groupBound = '1';
      if (input.value) input.value = grouped(input.value);
      input.addEventListener('input', () => {
        const posFromEnd = input.value.length - (input.selectionStart || input.value.length);
        input.value = grouped(input.value);
        const next = Math.max(0, input.value.length - posFromEnd);
        try { input.setSelectionRange(next, next); } catch (_) {}
      });
    });
  }

  function injectPresentationPolish() {
    if (document.getElementById('darma-v98-presentation-polish')) return;
    const style = document.createElement('style');
    style.id = 'darma-v98-presentation-polish';
    style.textContent = `
      a,a:hover,a:focus,a:active{text-decoration:none!important}
      .rm97-kpi strong{font-size:1.35rem!important;line-height:1.35!important;font-weight:900!important}
    `;
    document.head.appendChild(style);
  }

  function normalizeFinanceNav() {
    const nav = document.querySelector('.erp-nav');
    if (!nav) return;

    // V103: base.html owns the Finance navigation. Never construct or relocate
    // the Finance entry in JavaScript; only clean up a stale legacy duplicate.
    const nativeFinance = nav.querySelector('[data-finance-root-nav="base-v103"]');
    if (!nativeFinance) return;

    [...nav.querySelectorAll('.erp-nav-group')].forEach((group) => {
      const title = (group.querySelector('.erp-nav-group-title')?.textContent || '').trim();
      if (title === 'مالی و ابزار') group.remove();
    });
    nav.querySelectorAll('[data-business-tools-nav],[data-finance-root-nav]').forEach((node) => {
      if (node !== nativeFinance) node.remove();
    });

    const path = window.location.pathname;
    const financeActive = path.startsWith('/finance/') || path.startsWith('/payments/') || path.startsWith('/calculator/');
    nativeFinance.classList.toggle('active', financeActive);
  }

  function injectV39Styles() {
    if (document.getElementById('darma-ui-v39')) return;
    const link = document.createElement('link');
    link.id = 'darma-ui-v39';
    link.rel = 'stylesheet';
    link.href = '/static/core/ui-v39.css?v=39';
    document.head.appendChild(link);
  }

  // V94: this file is already included by base.html on every ERP page.
  // Load the Jalali calendar once from here so all date inputs share one picker.
  function injectGlobalJalaliPicker() {
    if (window.__darmaJalaliPickerLoading || window.__darmaJalaliPickerLoaded) return;
    window.__darmaJalaliPickerLoading = true;
    const script = document.createElement('script');
    script.id = 'darma-global-jalali-picker-v94';
    script.src = '/static/core/jalali_picker.js?v=94';
    script.async = false;
    script.onload = () => { window.__darmaJalaliPickerLoading = false; };
    script.onerror = () => { window.__darmaJalaliPickerLoading = false; };
    document.head.appendChild(script);
  }

  // Presentation-only default. The inventory POST handlers and stock mutation
  // code remain untouched; this only selects Darma in the existing adjustment UI.
  function defaultInventoryAdjustmentToDarma() {
    if (window.location.pathname !== '/inventory/operations/') return;
    const select = document.getElementById('adjust-brand');
    if (!select || select.dataset.v94DefaultApplied === '1') return;
    const darma = [...select.options].find((option) => (option.textContent || '').trim() === 'دارما');
    if (!darma) return;
    select.dataset.v94DefaultApplied = '1';
    select.value = darma.value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  injectV39Styles();
  injectGlobalJalaliPicker();
  injectPresentationPolish();
  window.DarmaNumber = { raw, grouped, separator: SEP };
  document.addEventListener('DOMContentLoaded', () => {
    bind();
    injectPresentationPolish();
    normalizeFinanceNav();
    defaultInventoryAdjustmentToDarma();
  });
  document.body?.addEventListener('htmx:afterSwap', (event) => {
    bind(event.target);
    injectPresentationPolish();
    normalizeFinanceNav();
  });
})();
