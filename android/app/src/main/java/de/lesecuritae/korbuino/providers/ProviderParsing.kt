package de.lesecuritae.korbuino.providers

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Small, shared parsers for retailer and Marktguru response variants. */
internal object ProviderParsing {
    fun cents(value: Double): Int {
        require(value.isFinite() && value >= 0) { "Ungültiger Preis" }
        return java.math.BigDecimal.valueOf(value).movePointRight(2)
            .setScale(0, java.math.RoundingMode.HALF_UP).intValueExact()
    }

    // Preserve an explicitly published quantity; never infer it from price or unit price.
    private val packPattern = Regex("""(?i)(\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?)\s*[- ]?\s*(kilogramm|milliliter|gramm|liter|ltr|kg|ml|cl|g|l)\b""")
    fun packSize(text: String): String? = packPattern.find(
        text.replace(Regex("""(?<![\d.,])([1-9]\d{0,2}(?:\.\d{3})+)(?![\d.,])""")) { it.value.replace(".", "") }
    )?.let {
        val unit = when (val raw = it.groupValues[2].lowercase()) {
            "ltr", "liter" -> "l"
            "kilogramm" -> "kg"
            "gramm" -> "g"
            "milliliter" -> "ml"
            else -> raw
        }
        "${it.groupValues[1]} $unit"
    }

    fun price(value: String?): Double? {
        var text = value?.trim()?.replace("€", "")?.replace(" ", "")?.replace('\u00A0'.toString(), "")
            ?: return null
        if (text.isBlank()) return null
        text = when {
            ',' in text && '.' in text -> {
                if (text.lastIndexOf(',') > text.lastIndexOf('.')) text.replace(".", "").replace(',', '.')
                else text.replace(",", "")
            }
            ',' in text -> text.replace(',', '.')
            else -> text
        }
        return text.toDoubleOrNull()
    }

    fun imageUrl(item: JsonObject, product: JsonObject): String? {
        sequenceOf(product, item).forEach { source ->
            sequenceOf("image", "imageUrl", "image_url", "productImage", "productImageUrl", "thumbnail", "thumbnailUrl")
                .mapNotNull { key -> source[key]?.jsonPrimitive?.content?.trim() }
                .firstOrNull { it.startsWith("http://") || it.startsWith("https://") }
                ?.let { return it }
        }

        val imageType = item["imageType"]?.jsonPrimitive?.content?.trim()?.lowercase()
        val images = item["images"]?.jsonObject
        if (imageType == "offer" && images != null) {
            val urls = images["urls"]?.jsonObject
            sequenceOf("large", "medium", "small")
                .mapNotNull { key -> urls?.get(key)?.jsonPrimitive?.content?.trim() }
                .firstOrNull { it.startsWith("http://") || it.startsWith("https://") }
                ?.let { return it }

            val count = images["count"]?.jsonPrimitive?.content?.toIntOrNull() ?: 0
            val offerId = item["id"]?.jsonPrimitive?.content?.trim().orEmpty()
            if (count > 0 && offerId.matches(Regex("\\d+"))) {
                return "https://mg2de.b-cdn.net/api/v1/offers/$offerId/images/default/0/medium.jpg"
            }
        }
        return null
    }
}
