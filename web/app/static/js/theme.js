// Light/dark theme manager. Dark is the default for this console.
(function () {
  const KEY = "ssmtp-theme";
  const root = document.documentElement;

  function apply(theme) {
    root.setAttribute("data-theme", theme);
  }

  const saved = localStorage.getItem(KEY) || "dark";
  apply(saved);

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("themeToggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(next);
      localStorage.setItem(KEY, next);
    });
  });
})();
