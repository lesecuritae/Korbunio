"use strict";
const form = document.getElementById("stock-form"), status = document.getElementById("status"), results = document.getElementById("results"), button = document.getElementById("check");
function line(parent, tag, text) { const e = document.createElement(tag); e.textContent = text; parent.append(e); }
form.addEventListener("submit", async event => {
  event.preventDefault(); results.replaceChildren(); button.disabled = true;
  status.textContent = "Bestände werden geprüft …";
  try {
    const dans = [...new Set(document.getElementById("dans").value.trim().split(/[\s,;]+/))];
    if (!dans.length || dans.length > 5 || dans.some(d => !/^[0-9]{6}$/.test(d))) throw new Error("Bitte eine bis fünf sechsstellige Artikelnummern eingeben.");
    const headers = {"Content-Type": "application/json"};
    const token = sessionStorage.getItem("korbuinoAdmin"); if (token) headers.Authorization = "Bearer " + token;
    const response = await fetch("/api/v1/availability", {method: "POST", headers, signal: AbortSignal.timeout(90000), body: JSON.stringify({postal_code: document.getElementById("postal").value, dans})});
    const data = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? "Bitte zuerst in den Einstellungen am Korbuino-Server anmelden." : "Bestandsabfrage wurde abgewiesen.");
    status.textContent = data.status === "busy" ? "Eine Bestandsabfrage läuft bereits. Bitte in wenigen Sekunden erneut versuchen." : data.error || data.notice;
    for (const item of data.results || []) {
      const card = document.createElement("article"); results.append(card); line(card, "h2", "Artikel " + item.dan);
      if (item.status !== "ok") { line(card, "p", item.error || "Bestand unbekannt"); continue; }
      line(card, "p", "Abgerufen: " + new Date(item.checked_at).toLocaleString("de-DE") + (item.from_cache ? " · zwischengespeichert" : ""));
      if (!item.stores.length) line(card, "p", "Keine passenden Filialdaten erhalten. Das bedeutet nicht ausverkauft.");
      for (const store of item.stores) line(card, "p", `${store.postal_code} ${store.city}, ${store.street}: ${store.in_stock === null ? "Bestand unbekannt" : store.in_stock ? (store.stock_is_exact ? store.stock_minimum : "mindestens " + store.stock_minimum) + " Stück gemeldet" : "0 Stück gemeldet"}`);
    }
  } catch (error) { status.textContent = error.message || "Bestandsabfrage fehlgeschlagen."; }
  finally { button.disabled = false; }
});
