package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup

private val postalCodePattern = Regex("^[0-9]{5}$")

private fun marketPage(http: OkHttpClient, url: String): String =
    http.newCall(Request.Builder().url(url).header("Accept", "text/html,application/json")
        .header("User-Agent", "Korbuino/0.1.71 (+https://github.com/lesecuritae/Korbunio)").build()).execute().use { response ->
        check(response.isSuccessful) { "Marktsuche HTTP ${response.code}" }
        val source = response.body?.source() ?: error("Marktsuche lieferte keine Antwort")
        check(!source.request(4_000_001)) { "Marktsuche überschreitet das Größenlimit" }
        source.readUtf8()
    }

/** Both chains use verified first-party stores within 15 km of the postal area.
 * The public Süd widget identifier is published on aldi-sued.de/filialen; it is
 * not an account/API credential. Nominatim resolves only postal areas absent
 * from both store lists, matching the server's existing geographic approach.
 */
class AldiMarkets(
    private val http: OkHttpClient,
    private val northUrl: String = "https://www.aldi-nord.de/filialen-und-oeffnungszeiten.html",
    private val southUrl: String = "https://uberall.com/api/storefinders/gqNws2nRfBBlQJS9UrA8zV9txngvET/locations/all?v=20260101&language=de",
    private val geocodeUrl: String = "https://nominatim.openstreetmap.org/search",
    private val now: () -> Long = System::currentTimeMillis,
) {
    private data class Store(val region: String, val postalCode: String, val lat: Double, val lon: Double)
    private val mutex = kotlinx.coroutines.sync.Mutex()
    private data class Catalogue(val stores: List<Store>, val fetchedAt: Long)
    private val catalogues = mutableMapOf<String, Catalogue>()
    private val regions = linkedMapOf<Pair<String, String>, Set<String>>()
    private val origins = linkedMapOf<String, Pair<Double, Double>>()
    private var lastGeocodeAt: Long? = null

    suspend fun hasMarket(postalCode: String, region: String): Boolean = withContext(Dispatchers.IO) {
        require(postalCodePattern.matches(postalCode)) { "Ungültige PLZ" }
        require(region in setOf("nord", "sued"))
        mutex.lock()
        try {
            var catalogue = catalogues[region]
            if (catalogue == null || now() - catalogue.fetchedAt >= 3_600_000L) {
                // One chain's outage must not prevent the other chain's offers.
                // Failed lookups remain errors and are never cached as absence.
                val next = if (region == "nord") northStores() else southStores()
                if (catalogue != null) origins.clear()
                catalogue = Catalogue(next, now())
                catalogues[region] = catalogue
                regions.keys.removeAll { it.first == region }
            }
            val key = region to postalCode
            val selected = regions[key] ?: resolve(postalCode, catalogue.stores).also {
                if (regions.size >= 64) regions.remove(regions.keys.first())
                regions[key] = it
            }
            region in selected
        } finally { mutex.unlock() }
    }

    private fun northStores(): List<Store> {
        val doc = Jsoup.parse(marketPage(http, northUrl))
        val script = doc.selectFirst("script#__NEXT_DATA__")?.data().orEmpty()
        check(script.isNotBlank()) { "ALDI Nord Filialdaten fehlen" }
        val raw = Json.parseToJsonElement(script).jsonObject["props"]?.jsonObject
            ?.get("pageProps")?.jsonObject?.get("apiData") ?: error("ALDI Nord Filialformat unbekannt")
        val api = when (raw) {
            is JsonArray -> raw
            is JsonPrimitive -> Json.parseToJsonElement(raw.content).jsonArray
            else -> error("ALDI Nord Filialformat unbekannt")
        }
        val locations = api.firstNotNullOfOrNull { entry ->
            val pair = entry as? JsonArray ?: return@firstNotNullOfOrNull null
            if (pair.size != 2 || pair[0].jsonPrimitive.content != "STORE_UBERALL_LOCATIONS_GET") return@firstNotNullOfOrNull null
            val result = pair[1].jsonObject["res"]?.jsonObject ?: return@firstNotNullOfOrNull null
            check(result["status"]?.jsonPrimitive?.content == "SUCCESS") { "ALDI Nord Marktsuche fehlgeschlagen" }
            result["response"]?.jsonObject?.get("locations")?.jsonArray
        } ?: error("ALDI Nord Filialliste fehlt")
        return parseStores(locations, "nord", "ALDI Nord")
    }

    private fun southStores(): List<Store> {
        val root = Json.parseToJsonElement(marketPage(http, southUrl)).jsonObject
        check(root["status"]?.jsonPrimitive?.content == "SUCCESS") { "ALDI Süd Marktsuche fehlgeschlagen" }
        val locations = root["response"]?.jsonObject?.get("locations")?.jsonArray
            ?: error("ALDI Süd Filialliste fehlt")
        return parseStores(locations, "sued", "ALDI SÜD")
    }

    private fun parseStores(rows: JsonArray, region: String, name: String): List<Store> {
        val result = rows.mapNotNull { value ->
            val row = value.jsonObject
            if (row["country"]?.jsonPrimitive?.content != "DE" ||
                row["name"]?.jsonPrimitive?.content?.startsWith(name, ignoreCase = true) != true) return@mapNotNull null
            val code = row["zip"]?.jsonPrimitive?.content?.takeIf(postalCodePattern::matches) ?: return@mapNotNull null
            val lat = row["lat"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
            val lon = row["lng"]?.jsonPrimitive?.doubleOrNull ?: return@mapNotNull null
            if (!lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0) return@mapNotNull null
            Store(region, code, lat, lon)
        }
        check(result.isNotEmpty()) { "ALDI $region lieferte keine gültigen Filialdaten" }
        return result
    }

    private suspend fun resolve(code: String, stores: List<Store>): Set<String> {
        val exact = catalogues.values.flatMap { it.stores }.filter { it.postalCode == code }
        val point = origins[code] ?: (if (exact.isNotEmpty()) exact.map { it.lat }.average() to exact.map { it.lon }.average()
            else geocode(code)).also {
                if (origins.size >= 32) origins.remove(origins.keys.first())
                origins[code] = it
            }
        return stores.filter { distanceKm(point, it.lat to it.lon) <= 15.0 }.map { it.region }.toSet()
    }

    private suspend fun geocode(code: String): Pair<Double, Double> {
        lastGeocodeAt?.let { last ->
            val remaining = 1_100L - (now() - last)
            if (remaining > 0) kotlinx.coroutines.delay(remaining.coerceAtMost(1_100L))
        }
        lastGeocodeAt = now()
        val url = geocodeUrl.toHttpUrl().newBuilder().addQueryParameter("postalcode", code)
            .addQueryParameter("country", "Germany").addQueryParameter("countrycodes", "de")
            .addQueryParameter("format", "jsonv2").addQueryParameter("addressdetails", "1")
            .addQueryParameter("limit", "1").build()
        val rows = Json.parseToJsonElement(marketPage(http, url.toString())).jsonArray
        val row = rows.firstOrNull()?.jsonObject ?: error("PLZ für ALDI-Marktsuche nicht gefunden")
        val address = row["address"]?.jsonObject ?: error("PLZ-Nachweis fehlt")
        check(address["country_code"]?.jsonPrimitive?.content == "de" &&
            address["postcode"]?.jsonPrimitive?.content == code) { "ALDI-Marktsuche: PLZ nicht bestätigt" }
        val lat = row["lat"]?.jsonPrimitive?.doubleOrNull ?: error("PLZ-Koordinaten fehlen")
        val lon = row["lon"]?.jsonPrimitive?.doubleOrNull ?: error("PLZ-Koordinaten fehlen")
        check(lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0)
        return lat to lon
    }

    private fun distanceKm(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
        val lat = Math.toRadians(b.first - a.first)
        val lon = Math.toRadians(b.second - a.second)
        val h = kotlin.math.sin(lat / 2).let { it * it } + kotlin.math.cos(Math.toRadians(a.first)) *
            kotlin.math.cos(Math.toRadians(b.first)) * kotlin.math.sin(lon / 2).let { it * it }
        return 6371.0088 * 2 * kotlin.math.asin(kotlin.math.sqrt(h.coerceIn(0.0, 1.0)))
    }
}

/** The retailer's own autocomplete includes non-supermarket locations as well. */
class AktivIrmaMarkets(
    private val http: OkHttpClient,
    private val baseUrl: String = "https://www.aktiv-irma.de",
) {
    suspend fun hasMarket(postalCode: String): Boolean = withContext(Dispatchers.IO) {
        require(postalCodePattern.matches(postalCode)) { "Ungültige PLZ" }
        val url = baseUrl.toHttpUrl().newBuilder().addPathSegment("xhr").addPathSegment("")
            .addQueryParameter("xhr", "getStandorte").addQueryParameter("format", "autocomplete")
            .addQueryParameter("q", postalCode).build()
        val payload = Json.parseToJsonElement(marketPage(http, url.toString()))
        if (payload is JsonObject && payload.keys == setOf("error") &&
            (payload["error"] as? JsonPrimitive)?.let { it.isString && it.content == "Kein Eintrag gefunden" } == true) {
            return@withContext false
        }
        val rows = payload.jsonArray
        rows.forEach { value ->
            val row = value.jsonObject
            check((row["standort_art"] as? JsonPrimitive)?.isString == true &&
                (row["standort_plz"] as? JsonPrimitive)?.isString == true) {
                "aktiv & irma Marktsuche: unbekanntes Antwortformat"
            }
        }
        rows.any { value ->
            val row = value.jsonObject
            row["standort_art"]?.jsonPrimitive?.content == "aktivirma" &&
                row["standort_plz"]?.jsonPrimitive?.content == postalCode
        }
    }
}
