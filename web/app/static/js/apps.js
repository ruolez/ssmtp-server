// Applications: list, create (reveal credentials once), reset password,
// enable/disable, delete.
(function () {
  const body = document.getElementById("appsBody");

  function paintCopyIcons() {
    document.querySelectorAll(".copy").forEach((b) => {
      if (!b.innerHTML.trim()) b.innerHTML = ICON_COPY;
    });
  }

  async function load() {
    const r = await api("/api/apps");
    if (!r.success) {
      body.innerHTML = `<tr><td colspan="7" class="empty">${escapeHtml(r.error)}</td></tr>`;
      return;
    }
    if (!r.data.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/></svg>
        <div>No applications yet. Create one to start relaying mail.</div></td></tr>`;
      return;
    }
    body.innerHTML = r.data
      .map(
        (a) => `<tr>
          <td><strong>${escapeHtml(a.name)}</strong></td>
          <td class="mono">${escapeHtml(a.smtp_username)}</td>
          <td><span class="pill ${a.enabled ? "on" : "off"}">${a.enabled ? "enabled" : "disabled"}</span></td>
          <td class="mono">${a.sent}</td>
          <td class="mono">${a.bounced}</td>
          <td class="dim">${escapeHtml(fmtTime(a.created_at))}</td>
          <td style="text-align:right; white-space:nowrap">
            <button class="btn btn-ghost btn-sm" data-act="toggle" data-id="${a.id}" data-enabled="${a.enabled}">${a.enabled ? "Disable" : "Enable"}</button>
            <button class="btn btn-ghost btn-sm" data-act="reset" data-id="${a.id}">Reset password</button>
            <button class="btn btn-danger btn-sm" data-act="delete" data-id="${a.id}" data-name="${escapeHtml(a.name)}">Delete</button>
          </td>
        </tr>`
      )
      .join("");
  }

  function showCreds({ smtp_username, password, api_key }) {
    document.getElementById("credUser").textContent = smtp_username;
    document.getElementById("credPass").textContent = password;
    document.getElementById("credKey").textContent = api_key;
    document.getElementById("copyUser").dataset.copy = smtp_username;
    document.getElementById("copyPass").dataset.copy = password;
    document.getElementById("copyKey").dataset.copy = api_key;
    paintCopyIcons();
    openModal("credsModal");
  }

  // --- create ---
  document.getElementById("newAppBtn").addEventListener("click", () => {
    document.getElementById("appName").value = "";
    document.getElementById("appUser").value = "";
    document.getElementById("appRate").value = "0";
    openModal("createModal");
  });

  document.getElementById("createAppBtn").addEventListener("click", async () => {
    const name = document.getElementById("appName").value.trim();
    const smtp_username = document.getElementById("appUser").value.trim();
    const rate = parseInt(document.getElementById("appRate").value || "0", 10);
    if (!name || !smtp_username) {
      toast("Name and username are required", "error");
      return;
    }
    const r = await api("/api/apps", {
      method: "POST",
      body: JSON.stringify({ name, smtp_username, rate_limit_per_hour: rate }),
    });
    if (!r.success) {
      toast(r.error || "Failed to create", "error");
      return;
    }
    closeModal("createModal");
    showCreds(r.data);
    load();
  });

  // --- row actions ---
  body.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.act === "toggle") {
      const r = await api(`/api/apps/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: btn.dataset.enabled !== "true" }),
      });
      toast(r.message || "Updated", r.success ? "success" : "error");
      load();
    } else if (btn.dataset.act === "reset") {
      const pwd = prompt("Enter a new SMTP password for this app:");
      if (!pwd) return;
      const r = await api(`/api/apps/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ password: pwd }),
      });
      toast(r.message || "Updated", r.success ? "success" : "error");
    } else if (btn.dataset.act === "delete") {
      if (!confirm(`Delete application "${btn.dataset.name}"? This cannot be undone.`)) return;
      const r = await api(`/api/apps/${id}`, { method: "DELETE" });
      toast(r.message || "Deleted", r.success ? "success" : "error");
      load();
    }
  });

  // --- modal plumbing ---
  document.querySelectorAll("[data-close]").forEach((b) =>
    b.addEventListener("click", () => closeModal(b.dataset.close))
  );
  document.querySelectorAll(".modal-overlay").forEach((o) =>
    o.addEventListener("click", (e) => {
      if (e.target === o) o.classList.remove("open");
    })
  );
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]");
    if (c) copyText(c.dataset.copy, "Copied to clipboard");
  });

  load();
})();
