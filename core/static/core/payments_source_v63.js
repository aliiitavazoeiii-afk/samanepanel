(function () {
  const dataNode = document.getElementById("payment-source-v63-data");
  let sourceMap = {};
  if (dataNode) {
    try { sourceMap = JSON.parse(dataNode.textContent || "{}"); } catch (_e) { sourceMap = {}; }
  }

  function actionOf(form) {
    return String(form.getAttribute("action") || "");
  }

  function paymentId(form) {
    const m = actionOf(form).match(/\/payments\/(\d+)\/edit\/?$/);
    return m ? m[1] : null;
  }

  function currentSource(form) {
    const id = paymentId(form);
    const value = id ? sourceMap[id] : "melat";
    return value === "mofid" ? "mofid" : "melat";
  }

  function makeSourceBox(form) {
    const payee = form.querySelector('select[name="payee"]');
    const amount = form.querySelector('input[name="amount"]');
    if (!payee || !amount || form.querySelector('[name="source_account"]')) return;

    const host = payee.closest('[class*="col-md-"]') || payee.parentElement;
    if (!host || !host.parentElement) return;

    const box = document.createElement("div");
    box.className = "col-md-2 payment-source-v63";
    box.innerHTML = '<label class="form-label">پرداخت از</label>' +
      '<select class="form-select" name="source_account" aria-label="حساب مبدا پرداخت">' +
      '<option value="melat">ملت</option>' +
      '<option value="mofid">مفید</option>' +
      '</select>';
    host.insertAdjacentElement("beforebegin", box);

    const select = box.querySelector('select[name="source_account"]');
    select.value = currentSource(form);

    if (/\/payments\/add\/?$/.test(actionOf(form))) {
      [amount, form.querySelector('input[name="note"]')].forEach(function (el) {
        if (!el) return;
        const col = el.closest('[class*="col-md-"]');
        if (!col) return;
        Array.from(col.classList).forEach(function (cls) {
          if (/^col-md-\d+$/.test(cls)) col.classList.remove(cls);
        });
        col.classList.add("col-md-2");
      });
    }
  }

  document.querySelectorAll("form").forEach(function (form) {
    if (form.querySelector('select[name="payee"]') && form.querySelector('input[name="amount"]')) {
      makeSourceBox(form);
    }
  });
})();
