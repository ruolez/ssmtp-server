// Settings: identity (read-only), delivery tunables, domain/DKIM status.
(function () {
  async function load() {
    const r = await api("/api/settings");
    if (!r.success) {
      toast(r.error || "Failed to load", "error");
      return;
    }
    const s = r.data;
    document.getElementById("setHostname").textContent = s.mail_hostname;
    document.getElementById("setDomain").textContent = s.mail_domain;
    document.getElementById("setIp").textContent = s.server_ip;
    document.getElementById("maxRetries").value = s.max_retries;
    document.getElementById("defaultRate").value = s.default_rate_limit;

    const body = document.getElementById("domainsBody");
    if (!s.domains.length) {
      body.innerHTML = `<tr><td colspan="3" class="empty">No domains.</td></tr>`;
      return;
    }
    body.innerHTML = s.domains
      .map(
        (d) => `<tr>
          <td class="mono">${escapeHtml(d.domain)}</td>
          <td class="mono">${escapeHtml(d.dkim_selector) || '<span class="dim">—</span>'}</td>
          <td>${
            d.dns_verified_at
              ? `<span class="pill pass">verified ${escapeHtml(fmtTime(d.dns_verified_at))}</span>`
              : `<span class="pill off">not verified</span>`
          }</td>
        </tr>`
      )
      .join("");
  }

  document.getElementById("saveBtn").addEventListener("click", async () => {
    const r = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        max_retries: parseInt(document.getElementById("maxRetries").value || "5", 10),
        default_rate_limit: parseInt(document.getElementById("defaultRate").value || "0", 10),
      }),
    });
    toast(r.message || (r.success ? "Saved" : "Failed"), r.success ? "success" : "error");
  });

  load();
})();
