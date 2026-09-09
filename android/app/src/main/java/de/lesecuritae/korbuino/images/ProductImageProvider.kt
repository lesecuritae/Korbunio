package de.lesecuritae.korbuino.images

import de.lesecuritae.korbuino.data.ProductImageEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request

data class ImageCandidate(
    val url: String,
    val source: String,
    val matchMethod: String,
    val confidence: Double,
)

/** Conservative image lookup: exact GTIN wins; weak name matches are rejected. */
class ProductImageProvider(private val http: OkHttpClient = OkHttpClient()) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun find(productId: String, gtin: String?, name: String, brand: String, size: String): ProductImageEntity? =
        withContext(Dispatchers.IO) {
            val code = gtin?.filter(Char::isDigit).orEmpty()
            if (code.isBlank()) return@withContext null
            val request = Request.Builder()
                .url("https://world.openfoodfacts.org/api/v2/product/$code.json?fields=code,product_name,image_front_url,brands,quantity")
                .header("User-Agent", "Korbuino/0.1 (product-image-provider)")
                .build()
            val candidate = runCatching {
                http.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) return@use null
                    val body = response.body?.string().orEmpty()
                    val root = json.parseToJsonElement(body).jsonObject
                    val product = root["product"]?.jsonObject ?: return@use null
                    val image = product["image_front_url"]?.jsonPrimitive?.content.orEmpty()
                    val productName = product["product_name"]?.jsonPrimitive?.content.orEmpty()
                    val productBrand = product["brands"]?.jsonPrimitive?.content.orEmpty()
                    if (!image.startsWith("https://") || !matches(productName, productBrand, name, brand, size)) null
                    else ImageCandidate(image, "Open Food Facts", "exact_gtin", 0.98)
                }
            }.getOrNull() ?: return@withContext null
            ProductImageEntity(
                productId = productId,
                imageUrl = candidate.url,
                source = candidate.source,
                matchMethod = candidate.matchMethod,
                confidence = candidate.confidence,
                verifiedAt = System.currentTimeMillis(),
                cachedAt = System.currentTimeMillis(),
            )
        }

    private fun matches(sourceName: String, sourceBrand: String, name: String, brand: String, size: String): Boolean {
        val actual = "$sourceBrand $sourceName".lowercase()
        val tokens = name.lowercase().split(Regex("\\W+")).filter { it.length > 2 }
        val nameMatch = tokens.count { actual.contains(it) } >= maxOf(1, tokens.size / 2)
        val sizeTokens = size.lowercase().split(Regex("\\W+")).filter { it.length > 1 }
        val sizeMatch = sizeTokens.isEmpty() || sizeTokens.any { actual.contains(it) }
        return nameMatch && sizeMatch &&
            (brand.isBlank() || sourceBrand.isBlank() || actual.contains(brand.lowercase()))
    }
}
