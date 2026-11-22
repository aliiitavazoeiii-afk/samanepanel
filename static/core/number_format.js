(() => {
  // Three-digit money grouping is a presentation layer, never a database change.
  // Keep quantities, dates, percents, identifiers and phone numbers unmodified.
  const SEP = '٬';
  const monetaryName = /(?:^|_)(?:amount|price|purchase|sale|cost|opening|fee|gross|net|total|balance|credit|debt|paid|received|deposit|advance|budget|wage|salary|income|expense|toman|rial)(?:_|$)/i;
  const excludedName = /(?:^|_)(?:qty|quantity|pack|packs|stock|count|number|percent|percentage|ratio|rate|tax_rate|id|code|phone|mobile|size|day|date|month|year|discount_percent|from|to)(?:_|$)/i;
  const excludeDate = /^(?:receipt|payment)_(?:from|to)$|(?:^|_)(?:date|day|time)(?:_|$)/i;
  const isTextNumber = (input) => input && (input.type === 'number' ||
    input.type === 'text' || input.type === 'tel' || input.type === 'search');
  const latin = (value) => String(value ?? '')
    .replace(/[۰-۹]/g, digit => String(digit.charCodeAt(0) - 1776))
    .replace(/[٠-٩]/g, digit => String(digit.charCodeAt(0) - 1632));
  function raw(value) {
    const text = latin(value).trim();
    return text.replace(/[٬,\s\u00a0]/g, '');
  }
  function grouped(value) {
    const cleaned = raw(value);
    if (!/^-?\d+$/.test(cleaned)) return cleaned;
    const negative = cleaned.startsWith('-');
    const digits = negative ? cleaned.slice(1) : cleaned;
    return (negative ? '-' : '') + digits.replace(/\B(?=(\d{3})+(?!\d))/g, SEP);
  }
  function parse(value) {
    const cleaned = raw(value);
    return /^-?\d+$/.test(cleaned) ? Number(cleaned) : NaN;
  }

  function labelFor(input) {
    if (input.labels && input.labels.length) {
      return [...input.labels].map(label => label.textContent || '').join(' ');
    }
    const group = input.closest('div');
    return (group?.querySelector('label')?.textContent || '');
  }
  function isMoneyField(input) {
    if (!isTextNumber(input) || input.disabled || input.dataset.moneySkip === '1') return false;
    if (input.closest('[data-money-skip="1"]') || input.hasAttribute('data-qty') ||
        input.hasAttribute('data-size-qty') || input.matches('.material-qty')) return false;
    const name = (input.name || '').trim();
    if (excludeDate.test(name) || excludedName.test(name)) return false;
    if (input.type === 'number') {
      const step = input.getAttribute('step');
      if (step && step !== '1') return false; // Preserve fractional/percentage inputs.
    }
    if (input.matches('.money, .money-input, .material-price, [data-color-price], [data-money-input]')) return true;
    if (monetaryName.test(name)) return true;
    // Only the immediate field label may opt an otherwise generic name in.
    return !name.match(/^(?:name|q|search|query|title|note|reference|code|id|value)$/i) &&
      /(?:تومان|ریال|مبلغ|قیمت|بهای\s*خرید|هزینه\s*هر)/.test(labelFor(input));
  }

  function validate(input) {
    const value = raw(input.value);
    if (value === '') { input.setCustomValidity(''); return true; }
    if (!/^-?\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
      input.setCustomValidity('فقط عدد صحیح وارد کن؛ اعشار یا حروف مجاز نیست.');
      return false;
    }
    const number = Number(value);
    const min = input.getAttribute('min');
    const max = input.getAttribute('max');
    if (min !== null && number < Number(min)) {
      input.setCustomValidity('مبلغ باید حداقل ' + grouped(min) + ' باشد.');
      return false;
    }
    if (max !== null && number > Number(max)) {
      input.setCustomValidity('مبلغ نباید از ' + grouped(max) + ' بیشتر شود.');
      return false;
    }
    input.setCustomValidity('');
    return true;
  }

  function updateView(input) {
    if (!validate(input)) return;
    const before = input.value;
    const start = input.selectionStart == null ? before.length : input.selectionStart;
    const digitsBefore = latin(before.slice(0, start)).replace(/\D/g, '').length;
    const newValue = grouped(before);
    if (newValue === before) return;
    input.value = newValue;
    // Preserve caret position when a separator is inserted or deleted.
    let caret = 0, count = 0;
    while (caret < newValue.length && count < digitsBefore) {
      if (/\d/.test(newValue.charAt(caret))) count++;
      caret++;
    }
    if (digitsBefore > 0 && caret < newValue.length && /[٬,]/.test(newValue.charAt(caret))) caret++;
    try { input.setSelectionRange(caret, caret); } catch (_) {}
  }

  function prepare(input) {
    if (!isMoneyField(input) || input.dataset.moneyGroupBound === '1') return;
    if (input.type === 'number') {
      input.dataset.moneyOriginalType = 'number';
      input.type = 'text'; // HTML number inputs cannot visually show 1,000,000.
    }
    input.dataset.moneyGroupBound = '1';
    input.classList.add('money-formatted');
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('dir', 'ltr');
    input.setAttribute('autocomplete', 'off');
    updateView(input);
  }
  function bind(root = document) {
    if (root.matches?.('input')) prepare(root);
    root.querySelectorAll?.('input').forEach(prepare);
  }
  function moneyInputs(form) {
    return [...form.querySelectorAll('input[data-money-group-bound="1"]')];
  }
  // Capture before a page's own submit handler. Inline calculations thus receive
  // raw numeric strings, and the browser never posts grouped textual amounts.
  function normalizeForm(form) {
    const inputs = moneyInputs(form);
    for (const input of inputs) {
      if (!validate(input)) {
        input.reportValidity();
        return false;
      }
    }
    for (const input of inputs) input.value = raw(input.value);
    // If a custom handler prevents submit, restore the grouped presentation.
    setTimeout(() => inputs.filter(input => input.isConnected).forEach(updateView), 0);
    return true;
  }

  document.addEventListener('input', (event) => {
    const input = event.target;
    if (!input?.matches?.('input')) return;
    if (input.dataset.moneyGroupBound !== '1') prepare(input);
    if (input.dataset.moneyGroupBound === '1') updateView(input);
  }, true);
  document.addEventListener('focusin', (event) => {
    if (event.target?.matches?.('input')) prepare(event.target);
  }, true);
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!form?.matches?.('form')) return;
    bind(form);
    if (!normalizeForm(form)) event.preventDefault();
  }, true);
  // Also correct FormData created by JavaScript (including asynchronous forms).
  document.addEventListener('formdata', (event) => {
    const form = event.target;
    if (!form?.matches?.('form')) return;
    for (const input of moneyInputs(form)) {
      if (input.name && !input.disabled) event.formData.set(input.name, raw(input.value));
    }
  });

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
  window.DarmaNumber = { raw, grouped, parse, separator: SEP, isMoneyField, bind };
  document.addEventListener('DOMContentLoaded', () => {
    bind();
    injectPresentationPolish();
    normalizeFinanceNav();
    defaultInventoryAdjustmentToDarma();
    // Dynamic rows may be appended by product, purchasing and finance screens.
    const observer = new MutationObserver((records) => {
      for (const record of records) for (const node of record.addedNodes) {
        if (node.nodeType === 1) bind(node);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
  document.body?.addEventListener('htmx:afterSwap', (event) => {
    bind(event.target);
    injectPresentationPolish();
    normalizeFinanceNav();
  });
})();
