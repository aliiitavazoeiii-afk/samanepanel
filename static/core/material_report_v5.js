(() => {
  const config = document.getElementById('materialReportConfig');
  const DOZEN_RATE = Number(config?.dataset.wageRate || 110000);
  const clean = (v) => Number(String(v ?? '').replace(/[٬,\s]/g, '').replace(/[^0-9.-]/g, '')) || 0;
  const fmt = (v) => String(Math.round(v || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, '٬');
  const wageForPieces = (pieces) => (Math.max(0, pieces) * DOZEN_RATE) / 12;

  function recalcOutputRow(form, row) {
    let delivered = 0;
    row.querySelectorAll('input[name^="out_"]').forEach((input) => {
      delivered += Math.max(0, clean(input.value));
    });

    const totalCell = row.querySelector('.output-row-total');
    if (totalCell) totalCell.textContent = fmt(delivered);

    const cutSource = row.dataset.cutSource || row.dataset.modelKey || '';
    const cutInput = cutSource ? form.querySelector(`input[name="in_${cutSource}_cut"]`) : null;
    const cut = Math.max(0, clean(cutInput?.value));
    const cutCell = row.querySelector('.output-cut-total');
    if (cutCell) cutCell.textContent = fmt(cut);

    const diff = delivered - cut;
    const diffCell = row.querySelector('.output-row-diff');
    if (diffCell) {
      diffCell.dataset.diff = String(diff);
      diffCell.classList.remove('shortage', 'surplus', 'exact');
      if (diff < 0) {
        diffCell.classList.add('shortage');
        diffCell.textContent = `کسری ${fmt(Math.abs(diff))}`;
      } else if (diff > 0) {
        diffCell.classList.add('surplus');
        diffCell.textContent = `مازاد ${fmt(diff)}`;
      } else {
        diffCell.classList.add('exact');
        diffCell.textContent = '۰';
      }
    }

    return delivered;
  }

  function recalcForm(form) {
    form.querySelectorAll('input[name$="_cut"]').forEach((cut) => {
      const wageName = cut.name.replace(/_cut$/, '_wage');
      const wage = form.querySelector(`input[name="${wageName}"]`);
      if (wage) {
        wage.value = clean(cut.value) > 0 ? fmt(wageForPieces(clean(cut.value))) : '';
        wage.readOnly = true;
      }
    });

    let delivered = 0;
    form.querySelectorAll('.output-data-row').forEach((row) => {
      delivered += recalcOutputRow(form, row);
    });

    if (!form.querySelector('.output-data-row')) {
      form.querySelectorAll('input[name^="out_"]').forEach((input) => {
        delivered += Math.max(0, clean(input.value));
      });
    }

    const totalWage = form.querySelector('input[name="delivery_wage"]');
    if (totalWage) {
      totalWage.value = delivered > 0 ? fmt(wageForPieces(delivered)) : '';
      totalWage.readOnly = true;
    }

    const grand = form.querySelector('.output-grand-total');
    if (grand) grand.textContent = fmt(delivered);
  }

  function makeTwoWayUi() {
    const stockNote = document.querySelector('.material-stock-note small');
    if (stockNote) {
      stockNote.textContent = 'برای هر دو برند Darma و Novani جدول تحویل دوطرفه است: افزایش، موجودی و مزد را زیاد می‌کند؛ کاهش یا پاک‌کردن، پس از همگام‌سازی همان مقدار را از موجودی همان برند کم و مزدش را برمی‌گرداند. ستون برش و کسری/مازاد فقط مقایسه‌ای است.';
    }

    document.querySelectorAll('.material-card form').forEach((form) => {
      const outputGrid = form.querySelector('.output-grid');
      const scroll = outputGrid?.closest('.table-responsive');
      const note = scroll?.previousElementSibling;
      if (note?.classList.contains('mobile-scroll-note')) {
        note.textContent = 'عددهای این جدول تجمعی‌اند. برای Darma و Novani می‌توانی عدد اعمال‌شده را کم یا کاملاً پاک کنی؛ «فقط ذخیره» داده را نگه می‌دارد و دکمه همگام‌سازی اختلاف را روی موجودی همان برند و مزد اعمال می‌کند.';
      }
    });

    document.querySelectorAll('button[formaction*="/apply-output/"]').forEach((button) => {
      button.textContent = 'همگام‌سازی تحویل و موجودی';
      button.onclick = () => window.confirm('تحویل با موجودی و مزد همان برند همگام شود؟ افزایش اضافه می‌شود و کاهش/پاک‌کردن از موجودی و مزد برمی‌گردد.');
      const action = button.closest('.section-action');
      if (!action) return;
      const title = action.querySelector('strong');
      const help = action.querySelector('p');
      if (title) title.textContent = 'همگام‌سازی تحویل ↔ موجودی';
      if (help) help.textContent = 'برای Darma و Novani هم افزایش و هم کاهش را اعمال می‌کند. اگر برای کاهش موجودی همان رنگ/سایز کافی نباشد، کل عملیات بدون تغییر متوقف می‌شود.';
    });
  }

  function bind() {
    makeTwoWayUi();
    document.querySelectorAll('.material-card form').forEach((form) => {
      if (form.dataset.wageBound === '1') return;
      form.dataset.wageBound = '1';
      form.addEventListener('input', (e) => {
        if (e.target.matches('input[name$="_cut"],input[name^="out_"]')) recalcForm(form);
      });
      recalcForm(form);
    });
  }

  document.addEventListener('DOMContentLoaded', bind);
})();
