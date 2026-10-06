package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.decodeFromJsonElement

@Serializable
data class LoyaltyBenefit(
    @SerialName("program_id") val programId: String,
    val kind: String,
    val value: Double,
    val label: String = "",
) {
    val cents: Int get() = Math.round(value * 100).toInt()
    val displayLabel: String get() = label.ifBlank { programId }
}

/** Concrete source values only; points and personal coupons are never estimated. */
object LoyaltyBenefits {
    private val json = Json { ignoreUnknownKeys = true }

    fun parse(raw: String): List<LoyaltyBenefit> = runCatching {
        (json.parseToJsonElement(raw) as? JsonArray).orEmpty().mapNotNull { item ->
            runCatching { json.decodeFromJsonElement<LoyaltyBenefit>(item) }.getOrNull()
        }.filter {
            it.programId.isNotBlank() && it.kind in setOf("direct_price", "cashback") &&
                it.value.isFinite() && it.value > 0 && it.value < Int.MAX_VALUE / 100.0 && it.cents > 0
        }
    }.getOrDefault(emptyList())

    fun encode(benefits: List<LoyaltyBenefit>): String = json.encodeToString(benefits)

    fun forOffer(offer: OfferEntity): List<LoyaltyBenefit> {
        val stored = parse(offer.loyaltyBenefitsJson)
        if (stored.isNotEmpty()) return stored
        val program = offer.loyaltyProgram ?: return emptyList()
        return listOfNotNull(
            offer.loyaltyPriceCents?.takeIf { it > 0 }?.let {
                LoyaltyBenefit(program, "direct_price", it / 100.0, offer.loyaltyLabel.orEmpty())
            },
            offer.loyaltyCashbackCents?.takeIf { it > 0 }?.let {
                LoyaltyBenefit(program, "cashback", it / 100.0, offer.loyaltyLabel.orEmpty())
            },
        )
    }
}
