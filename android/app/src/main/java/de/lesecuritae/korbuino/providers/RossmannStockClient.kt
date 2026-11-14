package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.time.Instant
import java.util.concurrent.TimeUnit

internal data class StockStore(val id: String, val city: String, val street: String, val postalCode: String,
    val raw: String, val minimum: Int?, val exact: Boolean) {
    val inStock: Boolean? get() = minimum?.let { if (it == 0 && !exact) null else it > 0 }
}
internal data class StockProduct(val dan: String, val stores: List<StockStore> = emptyList(),
    val checkedAt: String = "", val fromCache: Boolean = false, val error: String? = null)

/** Direct anonymous requests. No retailer app, account, cookies or SDK required. */
internal class RossmannStockClient(
    private val http: OkHttpClient,
    private val endpoint: String = "https://api-ocm-de-prod.rossmann.net/storefinder/.rest/rsmnapp/stores",
    private val geocodeUrl: String = "https://nominatim.openstreetmap.org/search",
    private val now: () -> Long = { System.nanoTime() / 1_000_000 },
    private val pause: suspend (Long) -> Unit = { delay(it) },
) {
    private val transport = http.newBuilder().followRedirects(false).followSslRedirects(false)
        .retryOnConnectionFailure(false).connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS).callTimeout(10, TimeUnit.SECONDS).build()
    private val admission = Mutex()
    private val cache = linkedMapOf<Pair<String, String>, Pair<Long, StockProduct>>()
    private val origins = linkedMapOf<String, Pair<Long, Pair<Double, Double>>>()
    private var nextRequest = 0L

    suspend fun check(postal: String, dans: List<String>): List<StockProduct> = withContext(Dispatchers.IO) {
        require(Regex("[0-9]{5}").matches(postal)) { "Bitte eine fünfstellige PLZ eingeben." }
        require(dans.size in 1..5 && dans.all { Regex("[0-9]{6}").matches(it) }) { "Eine bis fünf sechsstellige Artikelnummern eingeben." }
        check(admission.tryLock()) { "Eine Bestandsabfrage läuft bereits. Bitte kurz warten." }
        try {
            val saved = origins[postal]
            val point = if (saved != null && now() - saved.first < 86_400_000) saved.second else {
                pace()
                coordinates(postal).also {
                    if (origins.size >= 128) origins.remove(origins.keys.first())
                    origins[postal] = now() to it
                }
            }
            dans.distinct().map { dan ->
                ensureActive()
                val key = postal to dan
                val savedStock = cache[key]
                if (savedStock != null && now() - savedStock.first < 60_000) savedStock.second.copy(fromCache = true)
                else {
                    pace()
                    try {
                        val url = endpoint.toHttpUrl().newBuilder().addQueryParameter("latitude", point.first.toString())
                            .addQueryParameter("longitude", point.second.toString()).addQueryParameter("dan", dan).build()
                        StockProduct(dan, parse(read(url.toString()), dan), Instant.now().toString()).also {
                            if (cache.size >= 128) cache.remove(cache.keys.first())
                            cache[key] = now() to it
                        }
                    } catch (cancelled: CancellationException) { throw cancelled }
                    catch (error: Exception) { StockProduct(dan, error = error.message ?: "Bestand nicht abrufbar") }
                }
            }
        } finally { admission.unlock() }
    }

    private suspend fun pace() {
        val wait = nextRequest - now()
        if (wait > 0) pause(wait)
        nextRequest = now() + 2000
    }

    private fun read(url: String): JsonElement = transport.newCall(Request.Builder().url(url)
        .header("Accept", "application/json")
        .header("User-Agent", USER_AGENT).build()).execute().use { response ->
        check(response.isSuccessful) { "Bestand nicht abrufbar (HTTP ${response.code}); nicht als ausverkauft werten." }
        val source = response.body?.source() ?: error("Antwort fehlt")
        check(!source.request(2_000_001)) { "Bestandsantwort zu groß" }
        Json.parseToJsonElement(source.readUtf8())
    }

    private fun coordinates(postal: String): Pair<Double, Double> {
        val url = geocodeUrl.toHttpUrl().newBuilder().addQueryParameter("postalcode", postal)
            .addQueryParameter("country", "Germany").addQueryParameter("format", "jsonv2")
            .addQueryParameter("addressdetails", "1").addQueryParameter("limit", "1").build()
        val row = (read(url.toString()) as? JsonArray)?.firstOrNull()?.jsonObject ?: error("PLZ nicht auflösbar")
        val address = row["address"]?.jsonObject ?: error("PLZ nicht bestätigt")
        check(address["country_code"]?.jsonPrimitive?.content == "de" && address["postcode"]?.jsonPrimitive?.content == postal) { "PLZ nicht eindeutig bestätigt" }
        val lat = row["lat"]?.jsonPrimitive?.doubleOrNull ?: error("Breitengrad fehlt")
        val lon = row["lon"]?.jsonPrimitive?.doubleOrNull ?: error("Längengrad fehlt")
        check(lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0)
        return lat to lon
    }

    companion object {
        const val USER_AGENT = "Korbuino-Availability/1 (+https://github.com/lesecuritae/Korbunio)"
        val shared: RossmannStockClient by lazy {
            RossmannStockClient(OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
                .connectTimeout(8, TimeUnit.SECONDS).readTimeout(8, TimeUnit.SECONDS)
                .callTimeout(10, TimeUnit.SECONDS).retryOnConnectionFailure(false).build())
        }
        fun parse(payload: JsonElement, dan: String): List<StockStore> {
            val rows = payload as? JsonArray ?: error("Unbekanntes Filialformat")
            check(rows.size <= 200) { "Zu viele Filialdaten" }
            val stores = linkedMapOf<String, StockStore>()
            for (element in rows) {
                val row = element.jsonObject
                val id = row["id"]?.jsonPrimitive?.content ?: error("Filialkennung fehlt")
                check(Regex("[0-9]{1,12}").matches(id)) { "Ungültige Filialkennung" }
                val matches = (row["productInfos"] as? JsonArray ?: error("Artikeldaten fehlen"))
                    .filter { it.jsonObject["dan"]?.jsonPrimitive?.content == dan }
                check(matches.size == 1) { "Artikelzuordnung fehlt oder widerspricht sich" }
                val raw = matches.single().jsonObject["stock"]?.jsonPrimitive?.content.orEmpty()
                val count = Regex("([0-9]{1,6})(\\+?)").matchEntire(raw)
                fun text(key: String, max: Int) = row[key]?.jsonPrimitive?.content.orEmpty().take(max)
                val store = StockStore(id, text("city", 120), text("street", 200), text("zipCode", 5),
                    raw.take(30), count?.groupValues?.get(1)?.toInt(), count != null && count.groupValues[2].isEmpty())
                check(stores[id] == null || stores[id] == store) { "Widersprüchliche Filialbestände" }
                stores[id] = store
            }
            return stores.values.toList()
        }
    }
}
