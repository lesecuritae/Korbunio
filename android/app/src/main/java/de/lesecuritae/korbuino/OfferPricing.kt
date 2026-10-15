package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity

/** A source-confirmed quote. Unknown remainders are never priced as a bundle unit. */
data class PriceQuote(
    val unitPriceCents: Int?,
    val totalCents: Int?,
    val knownTotalCents: Int,
    val unpricedQuantity: Int,
    val minimumQuantity: Int?,
)

object OfferPricing {
    fun quote(offer: OfferEntity, quantity: Int, selectedPrograms: Set<String> = emptySet()): PriceQuote {
        val q = quantity.coerceAtLeast(1)
        val bundleQ = offer.multiBuyQuantity
        val bundleTotal = offer.multiBuyTotalCents
        if (bundleQ != null || bundleTotal != null) {
            val condition = offer.multiBuyCondition.orEmpty().lowercase(java.util.Locale.GERMAN)
            // Selecting a membership does not establish activation of a personal coupon.
            val needsCoupon = Regex("coupon|kupon|aktivier|personalisiert").containsMatchIn(condition)
            val needsMembership = Regex("karte|card|\\bapp\\b|mitglied|xtra|loyalty").containsMatchIn(condition)
            val program = offer.loyaltyProgram
            if (needsCoupon || (needsMembership && (program == null || program !in selectedPrograms))) {
                return PriceQuote(null, null, 0, q, bundleQ?.takeIf { it > 1 })
            }
        }
        if ((bundleQ != null || bundleTotal != null) &&
            (bundleQ == null || bundleQ <= 1 || bundleTotal == null || bundleTotal < 0)) {
            return PriceQuote(null, null, 0, q, bundleQ?.takeIf { it > 1 })
        }
        if (bundleQ != null && bundleQ > 1 && bundleTotal != null && bundleTotal >= 0) {
            val bundles = q / bundleQ
            val remainder = q % bundleQ
            val single = offer.singlePriceCents?.takeIf { it >= 0 }
            val known = bundles * bundleTotal + remainder * (single ?: 0)
            val unknown = if (single == null) remainder else 0
            val total = known.takeIf { unknown == 0 }
            return PriceQuote(if (q == 1) single else null, total, known, unknown, bundleQ)
        }
        val direct = LoyaltyBenefits.forOffer(offer)
            .filter { it.kind == "direct_price" && it.programId in selectedPrograms }
            .map { it.cents }.filter { it > 0 }
            .minOrNull()
        val unit = minOf(offer.priceCents, direct ?: offer.priceCents)
        return PriceQuote(unit, unit * q, unit * q, 0, null)
    }
}
