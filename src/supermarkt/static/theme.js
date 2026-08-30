(function () {
  "use strict";

  const storageKey = "korbklar.theme.v1";
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function storedTheme() {
    try {
      const value = localStorage.getItem(storageKey);
      return value === "light" || value === "dark" ? value : "";
    } catch (_error) {
      return "";
    }
  }

  function effectiveTheme() {
    return document.documentElement.dataset.theme || (systemDark.matches ? "dark" : "light");
  }

  function updateControls() {
    const theme = effectiveTheme();
    document.querySelectorAll(".themeToggle").forEach(button => {
      const next = theme === "dark" ? "light" : "dark";
      button.textContent = next === "dark" ? "☾ Dunkel" : "☀ Hell";
      button.setAttribute("aria-label", `Zum ${next === "dark" ? "dunklen" : "hellen"} Design wechseln`);
      button.setAttribute("aria-pressed", String(theme === "dark"));
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#111318" : "#116149";
  }

  function apply(theme, persist) {
    document.documentElement.dataset.theme = theme;
    if (persist) {
      try { localStorage.setItem(storageKey, theme); } catch (_error) {}
    }
    updateControls();
  }

  const initial = storedTheme();
  if (initial) document.documentElement.dataset.theme = initial;

  document.addEventListener("DOMContentLoaded", () => {
    updateControls();
    document.querySelectorAll(".themeToggle").forEach(button => {
      button.addEventListener("click", () => apply(effectiveTheme() === "dark" ? "light" : "dark", true));
    });
  });

  systemDark.addEventListener("change", () => {
    if (!storedTheme()) updateControls();
  });
})();
