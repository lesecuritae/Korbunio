package de.lesecuritae.korbuino.providers

/**
 * The script the confirmation screen runs inside the user's WebView on
 * edeka.de. It asks EDEKA's own market search and offer service for the
 * postal code, exactly like the server adapter does, and passes the raw JSON
 * back through the `KorbuinoEdeka` bridge. Markets are tried exact postal code
 * first, then the nearest, until one lists offers with a price.
 */
object EdekaWebFetchScript {
    const val BRIDGE_NAME = "KorbuinoEdeka"
    const val MAX_MARKETS = 6

    fun build(postalCode: String): String {
        require(Regex("^\\d{5}$").matches(postalCode)) { "Ungültige PLZ" }
        return """
            (async function (plz) {
              const out = { postalCode: plz, market: null, offers: null, error: null };
              const get = async (path) => {
                const r = await fetch(path, { credentials: 'include', headers: { 'Accept': 'application/json' } });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
              };
              const id = (m) => String(m.id || m.marketId || m.marketID || m.wwIdent || '');
              const zip = (m) => {
                const c = ((m.contact || {}).address || {}).city || {};
                return String(c.zipCode || m.zipCode_keyword || m.zipCode || '');
              };
              try {
                const found = await get('/api/marketsearch/markets?size=100&searchstring=' + encodeURIComponent(plz));
                let list = Array.isArray(found) ? found
                  : (['markets', 'docs', 'results', 'items'].map((k) => found && found[k]).find(Array.isArray) || []);
                list = list.filter((m) => m && typeof m === 'object' && id(m));
                const ordered = list.filter((m) => zip(m) === plz)
                  .concat(list.filter((m) => zip(m) !== plz)).slice(0, $MAX_MARKETS);
                if (!ordered.length) out.error = 'Keine EDEKA-Märkte für PLZ ' + plz + ' gefunden';
                for (const m of ordered) {
                  try {
                    const offers = await get('/eh/service/eh/offers?marketId=' + encodeURIComponent(id(m)) + '&limit=99999');
                    const docs = Array.isArray(offers) ? offers : ((offers && offers.docs) || []);
                    if (docs.some((d) => parseFloat(String(d.preis).replace(',', '.')) > 0)) {
                      out.market = m;
                      out.offers = offers;
                      break;
                    }
                  } catch (ignored) { /* one market failing must not hide the others */ }
                }
                if (!out.offers && !out.error) {
                  out.error = 'Keiner der ' + ordered.length + ' Märkte in der Nähe von ' + plz + ' lieferte Angebote mit Preisen';
                }
              } catch (e) {
                out.error = 'EDEKA-Abruf im Browser fehlgeschlagen: ' + e;
              }
              $BRIDGE_NAME.deliver(JSON.stringify(out));
            })('$postalCode');
        """.trimIndent()
    }
}
