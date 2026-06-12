// Dashboard: stats + searchable/filterable message log with auto-refresh.
(function () {
  let status = "all";
  let search = "";

  const body = document.getElementById("msgBody");

  async function loadStats() {
    const r = await api("/api/stats");
    if (!r.success) return;
    const s = r.data;
    const set = (k, v) => {
      const el = document.querySelector(`[data-stat="${k}"]`);
      if (el) el.textContent = v;
    };
    set("total", s.total);
    set("sent", s.sent);
    set("deferred_pending", (s.deferred || 0) + (s.pending || 0));
    set("bounced", s.bounced);
    set("last_24h_foot", `last 24h: ${s.last_24h}`);
  }

  function pill(status) {
    return `<span class="pill ${escapeHtml(status)}">${escapeHtml(status)}</span>`;
  }

  async function loadMessages() {
    const params = new URLSearchParams();
    if (status !== "all") params.set("status", status);
    if (search) params.set("q", search);
    const r = await api(`/api/messages?${params.toString()}`);
    if (!r.success) {
      body.innerHTML = `<tr><td colspan="6" class="empty">${escapeHtml(r.error || "Failed to load")}</td></tr>`;
      return;
    }
    if (!r.data.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7l9 6 9-6"/><rect x="3" y="5" width="18" height="14" rx="2"/></svg>
        <div>No messages yet. Point an app at this relay to see activity.</div></td></tr>`;
      return;
    }
    body.innerHTML = r.data
      .map(
        (m) => `<tr class="clickable" onclick="location.href='/messages/${m.id}'">
          <td>${pill(m.status)}</td>
          <td class="mono truncate" style="max-width:220px">${escapeHtml(m.to_addr)}</td>
          <td class="truncate" style="max-width:260px">${escapeHtml(m.subject) || '<span class="dim">(no subject)</span>'}</td>
          <td>${m.app_name ? escapeHtml(m.app_name) : '<span class="dim">—</span>'}</td>
          <td class="mono truncate dim" style="max-width:180px">${escapeHtml(m.from_addr)}</td>
          <td class="dim" title="${escapeHtml(m.received_at)}">${relTime(m.received_at)}</td>
        </tr>`
      )
      .join("");
  }

  function refresh() {
    loadStats();
    loadMessages();
  }

  document.getElementById("statusSeg").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    document.querySelectorAll("#statusSeg button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    status = btn.dataset.status;
    loadMessages();
  });

  document.getElementById("searchInput").addEventListener(
    "input",
    debounce((e) => {
      search = e.target.value.trim();
      loadMessages();
    }, 300)
  );

  document.getElementById("refreshBtn").addEventListener("click", refresh);

  refresh();
  setInterval(refresh, 15000);
})();
