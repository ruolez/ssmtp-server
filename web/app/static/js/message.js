// Message detail: envelope metadata + vertical delivery lifecycle timeline.
(function () {
  const id = window.MESSAGE_ID;

  function dotClass(eventType, status) {
    if (eventType === "delivered" || status === "sent") return "ok";
    if (eventType === "bounce" || status === "bounced") return "bad";
    if (eventType === "deferred") return "warn";
    return "";
  }

  function eventTitle(t) {
    return { queued: "Queued for delivery", delivered: "Delivered",
             deferred: "Deferred — will retry", bounce: "Bounced" }[t] || t;
  }

  async function load() {
    const r = await api(`/api/messages/${id}`);
    if (!r.success) {
      document.getElementById("msgMeta").innerHTML =
        `<dt class="dim">Error</dt><dd>${escapeHtml(r.error)}</dd>`;
      return;
    }
    const m = r.data;
    document.getElementById("msgStatus").innerHTML =
      `<span class="pill ${escapeHtml(m.status)}">${escapeHtml(m.status)}</span>`;

    const rows = [
      ["To", m.to_addr],
      ["From", m.from_addr],
      ["Subject", m.subject || "—"],
      ["Application", m.app_name || "—"],
      ["Message-ID", m.message_id || "—"],
      ["Size", m.size_bytes ? `${m.size_bytes} bytes` : "—"],
      ["Queue ID", m.queue_id || "—"],
      ["Received", fmtTime(m.received_at)],
      ["Last update", fmtTime(m.updated_at)],
    ];
    document.getElementById("msgMeta").innerHTML = rows
      .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
      .join("");

    const steps = [
      {
        title: "Received & queued",
        time: m.received_at,
        detail: `Accepted from ${m.from_addr || "?"}`,
        cls: "",
      },
    ];
    (m.events || []).forEach((ev) => {
      const parts = [];
      if (ev.remote_mx) parts.push(`MX ${ev.remote_mx}`);
      if (ev.smtp_code) parts.push(`code ${ev.smtp_code}`);
      if (ev.smtp_response) parts.push(ev.smtp_response);
      if (ev.attempt_no) parts.push(`attempt ${ev.attempt_no}`);
      steps.push({
        title: eventTitle(ev.event_type),
        time: ev.occurred_at,
        detail: parts.join(" · "),
        cls: dotClass(ev.event_type, m.status),
      });
    });

    document.getElementById("timeline").innerHTML = steps
      .map(
        (s) => `<div class="tl-item">
          <div class="tl-dot ${s.cls}"></div>
          <div class="tl-head">${escapeHtml(s.title)}</div>
          <div class="tl-time">${escapeHtml(fmtTime(s.time))}</div>
          ${s.detail ? `<div class="tl-detail">${escapeHtml(s.detail)}</div>` : ""}
        </div>`
      )
      .join("");
  }

  load();
  setInterval(load, 12000);
})();
