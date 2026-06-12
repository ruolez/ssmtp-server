// DNS & DKIM: render the records to publish and live-verify resolution.
(function () {
  const list = document.getElementById("dnsList");

  function recordCard(rec, check) {
    const checkPill = check
      ? `<span class="pill ${check.status}">${check.status}</span>`
      : "";
    const foundLine =
      check && check.found
        ? `<div class="hint">Found: <span class="mono">${escapeHtml(check.found)}</span></div>`
        : check && check.detail
        ? `<div class="hint">${escapeHtml(check.detail)}</div>`
        : "";
    return `<div class="field" style="margin-bottom:22px">
      <label style="display:flex; align-items:center; gap:10px">
        <span class="pill info" style="background:var(--accent-soft); color:var(--accent)">${escapeHtml(rec.type)}</span>
        <span class="mono">${escapeHtml(rec.fqdn)}</span>
        ${checkPill}
      </label>
      <div class="code">
        <span>${escapeHtml(rec.value)}</span>
        <button class="copy" data-copy="${escapeHtml(rec.value)}">${ICON_COPY}</button>
      </div>
      <div class="hint">${escapeHtml(rec.purpose)}</div>
      ${foundLine}
    </div>`;
  }

  async function load() {
    const r = await api("/api/dns");
    if (!r.success) {
      list.innerHTML = `<div class="empty">${escapeHtml(r.error)}</div>`;
      return;
    }
    list.innerHTML = r.data.records.map((rec) => recordCard(rec, null)).join("");
  }

  async function verify() {
    list.innerHTML = `<div class="empty">Resolving records…</div>`;
    const r = await api("/api/dns/verify", { method: "POST", body: "{}" });
    if (!r.success) {
      list.innerHTML = `<div class="empty">${escapeHtml(r.error)}</div>`;
      return;
    }
    list.innerHTML = r.data.records.map((rec) => recordCard(rec, rec.check)).join("");
    const pass = r.data.records.filter((x) => ["pass", "info"].includes(x.check.status)).length;
    toast(`${pass}/${r.data.records.length} records OK`, pass === r.data.records.length ? "success" : "error");
  }

  document.getElementById("verifyBtn").addEventListener("click", verify);
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]");
    if (c) copyText(c.dataset.copy, "Record copied");
  });

  load();
})();
