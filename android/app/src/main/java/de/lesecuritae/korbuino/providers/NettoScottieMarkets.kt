package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup

/** Read the official initialStores catalogue as JSON; never execute its scripts. */
class NettoScottieMarkets(
    private val http: OkHttpClient,
    private val storesUrl: String = "https://netto.de/marktsuche/",
    private val geocodeUrl: String = "https://nominatim.openstreetmap.org/search",
    private val now: () -> Long = System::currentTimeMillis,
) {
    private data class Store(val id: String, val postal: String, val lat: Double, val lon: Double)
    private val mutex = Mutex()
    private var stores: List<Store> = emptyList()
    private var fetchedAt = 0L
    private var lastGeocodeAt: Long? = null
    private val regions = linkedMapOf<String, Boolean>()

    suspend fun hasMarket(postalCode: String): Boolean = withContext(Dispatchers.IO) {
        require(Regex("\\d{5}").matches(postalCode)) { "Ungültige PLZ" }
        mutex.lock()
        try {
            if (stores.isEmpty() || now() - fetchedAt >= 3_600_000L) {
                val next = catalogue(read(storesUrl))
                stores = next
                fetchedAt = now()
                regions.clear()
            }
            regions[postalCode] ?: (if (stores.any { it.postal == postalCode }) true else {
                val point = coordinates(postalCode)
                stores.any { distance(point, it.lat to it.lon) <= 15.0 }
            }).also {
                if (regions.size >= 64) regions.remove(regions.keys.first())
                regions[postalCode] = it
            }
        } finally { mutex.unlock() }
    }

    private fun read(url: String): String = http.newCall(Request.Builder().url(url)
        .header("Accept", "text/html,application/json")
        .header("User-Agent", "Korbuino (+https://github.com/lesecuritae/Korbunio)").build()).execute().use { response ->
        check(response.isSuccessful) { "Netto schwarz Marktsuche HTTP ${response.code}" }
        val source = response.body?.source() ?: error("Netto schwarz Marktsuche ohne Antwort")
        check(!source.request(4_000_001)) { "Netto schwarz Marktsuche überschreitet das Größenlimit" }
        source.readUtf8()
    }

    private fun catalogue(html: String): List<Store> {
        val chunks = Jsoup.parse(html).select("script").flatMap { script ->
            val match = Regex("self\\.__next_f\\.push\\((.*)\\)", RegexOption.DOT_MATCHES_ALL)
                .matchEntire(script.data().trim().removeSuffix(";")) ?: return@flatMap emptyList()
            val packet = runCatching { Json.parseToJsonElement(match.groupValues[1]) as? JsonArray }.getOrNull()
            packet.orEmpty().mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
        }.joinToString("")
        val found = linkedMapOf<String, Store>()
        var visited = 0
        fun walk(value: JsonElement, depth: Int) {
            check(depth <= 64 && ++visited <= 100_000) { "Netto schwarz Filialformat zu komplex" }
            when (value) {
                is JsonObject -> {
                    value["initialStores"]?.let { raw ->
                        val rows = raw as? JsonArray ?: error("Netto schwarz Filialformat unbekannt")
                        rows.forEach { element ->
                            val row = element.jsonObject
                            val address = row["address"]?.jsonObject ?: error("Netto schwarz Filialadresse fehlt")
                            val brand = row.text("brand") ?: error("Netto schwarz Filialzuordnung fehlt")
                            val country = address.text("country") ?: error("Netto schwarz Filialland fehlt")
                            if (brand != "netto" || country != "DE") return@forEach
                            val id = row.text("id") ?: error("Netto schwarz Filial-ID fehlt")
                            val zip = address.text("zip")?.takeIf { Regex("\\d{5}").matches(it) } ?: error("Netto schwarz Filial-PLZ fehlt")
                            val point = row["coordinates"]?.jsonArray ?: error("Netto schwarz Filialkoordinaten fehlen")
                            check(point.size == 2)
                            val lon = point[0].jsonPrimitive.doubleOrNull ?: error("Filial-Längengrad fehlt")
                            val lat = point[1].jsonPrimitive.doubleOrNull ?: error("Filial-Breitengrad fehlt")
                            check(lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0)
                            val store = Store(id, zip, lat, lon)
                            check(found[id] == null || found[id] == store) { "Netto schwarz widersprüchliche Filialdaten" }
                            found[id] = store
                        }
                    }
                    value.filterKeys { it != "initialStores" }.values.forEach { walk(it, depth + 1) }
                }
                is JsonArray -> value.forEach { walk(it, depth + 1) }
                else -> Unit
            }
        }
        chunks.lineSequence().forEach { line ->
            val match = Regex("^[0-9a-f]+:(.*)").matchEntire(line) ?: return@forEach
            val value = runCatching { Json.parseToJsonElement(match.groupValues[1]) }.getOrNull() ?: return@forEach
            walk(value, 0)
        }
        check(found.isNotEmpty()) { "Netto schwarz: vollständige öffentliche Filialliste nicht lesbar" }
        return found.values.toList()
    }

    private suspend fun coordinates(postal: String): Pair<Double, Double> {
        lastGeocodeAt?.let { previous ->
            val wait = 1_100L - (now() - previous)
            if (wait > 0) kotlinx.coroutines.delay(wait.coerceAtMost(1_100L))
        }
        lastGeocodeAt = now()
        val url = geocodeUrl.toHttpUrl().newBuilder().addQueryParameter("postalcode", postal)
            .addQueryParameter("country", "Germany").addQueryParameter("countrycodes", "de")
            .addQueryParameter("format", "jsonv2").addQueryParameter("addressdetails", "1").addQueryParameter("limit", "1").build()
        val row = Json.parseToJsonElement(read(url.toString())).jsonArray.firstOrNull()?.jsonObject ?: error("Netto schwarz: PLZ nicht gefunden")
        val address = row["address"]?.jsonObject ?: error("Netto schwarz: PLZ-Nachweis fehlt")
        check(address.text("country_code") == "de" && address.text("postcode") == postal) { "Netto schwarz: PLZ nicht bestätigt" }
        val lat = row["lat"]?.jsonPrimitive?.doubleOrNull ?: error("PLZ-Breitengrad fehlt")
        val lon = row["lon"]?.jsonPrimitive?.doubleOrNull ?: error("PLZ-Längengrad fehlt")
        check(lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0)
        return lat to lon
    }

    private fun distance(a: Pair<Double, Double>, b: Pair<Double, Double>): Double {
        val lat = Math.toRadians(b.first - a.first); val lon = Math.toRadians(b.second - a.second)
        val h = kotlin.math.sin(lat / 2).let { it * it } + kotlin.math.cos(Math.toRadians(a.first)) *
            kotlin.math.cos(Math.toRadians(b.first)) * kotlin.math.sin(lon / 2).let { it * it }
        return 6371.0088 * 2 * kotlin.math.asin(kotlin.math.sqrt(h.coerceIn(0.0, 1.0)))
    }

    private fun JsonObject.text(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }
}
