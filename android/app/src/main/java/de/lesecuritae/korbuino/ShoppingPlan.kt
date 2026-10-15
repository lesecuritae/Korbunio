package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.ShoppingListRow
import java.time.LocalDate

/**
 * Turns the shopping list into an at-a-glance plan: which shops the cheapest
 * run needs, and where a tiny price gap does not justify a separate trip.
 *
 * Issue #56: the user wants to see after adding filtered items that they would
 * have to visit several shops, but could skip some because an item is only a
 * few cents cheaper elsewhere. [build] is pure so it can be unit tested without
 * Android, and [ShoppingListOverview] renders the result.
 */
object ShoppingPlan {
    /** A separate shop is not worth it when the item is at most this much dearer at the main shop. */
    const val DEFAULT_CONSOLIDATION_THRESHOLD_CENTS = 50

    /** One shopping-list entry's cheapest offer per shop. */
    private data class ItemOffers(val row: ShoppingListRow, val pricePerRetailer: Map<String, Int>) {
        val name: String get() = row.name
        val cheapestRetailer: String? = pricePerRetailer.minByOrNull { it.value }?.key
        val cheapestCents: Int? = cheapestRetailer?.let { pricePerRetailer.getValue(it) }
    }

    data class Consolidation(val itemName: String, val skippedRetailerId: String, val extraCents: Int, val itemId: String = "")

    data class Position(
        val itemId: String,
        val productId: String,
        val name: String,
        val quantity: Int,
        val retailerId: String?,
        val selectedOfferId: String?,
        val selectedOffer: OfferDisplay?,
        val chosenOffer: OfferDisplay?,
        val suggestedOffer: OfferDisplay?,
        val unitPriceCents: Int?,
        val totalCents: Int?,
        val depositCents: Int?,
        val cashbackCents: Int?,
        val basePriceCents: Int?,
        val baseUnit: String?,
        val quote: PriceQuote?,
    )

    data class Plan(
        val matchedCount: Int,
        val unmatchedItems: List<String>,
        val cheapestTotalCents: Int,
        val cheapestStores: List<String>,
        val primaryStoreId: String?,
        val consolidations: List<Consolidation>,
        val consolidatedStores: List<String>,
        val consolidationExtraCents: Int,
        val positions: List<Position> = emptyList(),
        val actualTotalCents: Int? = null,
        val actualStores: List<String> = emptyList(),
    ) {
        val hasPlan: Boolean get() = matchedCount > 0
        val suggestionsComplete: Boolean get() = unmatchedItems.isEmpty() && positions.isNotEmpty()
        val suggestedTotalCents: Int? get() = cheapestTotalCents.takeIf { suggestionsComplete }
        val savedTrips: Int get() = if (suggestionsComplete) (cheapestStores.size - consolidatedStores.size).coerceAtLeast(0) else 0
    }

    fun build(
        items: List<String>,
        offers: List<OfferDisplay>,
        selectedPrograms: Set<String>,
        thresholdCents: Int = DEFAULT_CONSOLIDATION_THRESHOLD_CENTS,
    ): Plan {
        val seen = LinkedHashSet<String>()
        val rows = items.map { it.trim() }.filter { it.isNotBlank() && seen.add(it.lowercase()) }
            .map { ShoppingListRow(it, it, 1, false) }
        return buildRows(rows, offers, selectedPrograms, thresholdCents = thresholdCents)
    }

    /** Prices are pack prices multiplied by packs; unknown prices stay unknown. */
    fun buildRows(
        items: List<ShoppingListRow>,
        offers: List<OfferDisplay>,
        selectedPrograms: Set<String>,
        today: LocalDate = LocalDate.now(java.time.ZoneId.of("Europe/Berlin")),
        thresholdCents: Int = DEFAULT_CONSOLIDATION_THRESHOLD_CENTS,
    ): Plan {
        val currentOffers = offers.filter { isCurrent(it, today) }
        val matched = mutableListOf<ItemOffers>()
        val unmatched = mutableListOf<String>()
        val positions = items.filterNot { it.checked }.map { row ->
            val quantity = row.quantity.coerceAtLeast(1)
            val candidates = OfferMatcher.matches(row.name, currentOffers)
            val priced = candidates.mapNotNull { candidate ->
                OfferPricing.quote(candidate.offer, quantity, selectedPrograms).totalCents?.let { candidate to it }
            }
            val best = priced.groupBy { it.first.offer.retailerId }.mapValues { (_, values) -> values.minOf { it.second } }
            if (best.isEmpty()) unmatched += row.name else matched += ItemOffers(row, best)
            val selected = row.offerId?.let { id -> currentOffers.firstOrNull { it.offer.id == id && (row.retailerId == null || it.offer.retailerId == row.retailerId) } }
            // An explicitly selected offer must never silently turn into a different pack.
            val chosen = if (row.offerId != null) selected else if (row.retailerId == null) null else candidates
                .filter { row.retailerId == null || it.offer.retailerId == row.retailerId }
                .minByOrNull { OfferPricing.quote(it.offer, quantity, selectedPrograms).totalCents ?: Int.MAX_VALUE }
            val suggested = candidates.minByOrNull { OfferPricing.quote(it.offer, quantity, selectedPrograms).totalCents ?: Int.MAX_VALUE }
            val quote = chosen?.let { OfferPricing.quote(it.offer, quantity, selectedPrograms) }
            val unit = quote?.unitPriceCents
            val cashback = chosen?.let { display -> LoyaltyBenefits.forOffer(display.offer)
                .filter { it.programId in selectedPrograms && it.kind == "cashback" }.maxOfOrNull { it.cents } }
            Position(row.itemId, row.productId, row.name, quantity, row.retailerId ?: chosen?.offer?.retailerId,
                row.offerId, selected, chosen, suggested, unit, quote?.totalCents,
                chosen?.offer?.depositCents?.times(quantity), cashback?.times(quantity),
                chosen?.offer?.basePriceCents?.takeIf { quote?.minimumQuantity == null && unit == chosen?.offer?.priceCents },
                chosen?.offer?.baseUnit?.takeIf { quote?.minimumQuantity == null && unit == chosen?.offer?.priceCents }, quote)
        }
        val actualTotal = if (positions.isNotEmpty() && positions.all { it.totalCents != null }) positions.sumOf { it.totalCents!! } else null
        val actualStores = positions.filter { it.chosenOffer != null }.mapNotNull { it.retailerId }.distinct()

        if (matched.isEmpty()) {
            return Plan(0, unmatched, 0, emptyList(), null, emptyList(), emptyList(), 0, positions, actualTotal, actualStores)
        }

        val cheapestStores = matched.mapNotNull { it.cheapestRetailer }.distinct()
        val cheapestTotal = matched.sumOf { it.cheapestCents ?: 0 }

        // Main shop: the one that can supply the most items (most consolidation
        // potential); ties go to the shop that is already cheapest most often,
        // then the alphabetically last id so the result stays deterministic.
        val cheapestWins = matched.groupingBy { it.cheapestRetailer }.eachCount()
        val primary = matched.flatMap { it.pricePerRetailer.keys }
            .groupingBy { it }.eachCount()
            .entries
            .maxWithOrNull(
                compareBy<Map.Entry<String, Int>> { it.value }
                    .thenBy { cheapestWins[it.key] ?: 0 }
                    .thenBy { it.key },
            )?.key

        val consolidations = mutableListOf<Consolidation>()
        val assignedStore = HashMap<String, String>()
        for (item in matched) {
            val cheapest = item.cheapestRetailer ?: continue
            val priceAtPrimary = primary?.let { item.pricePerRetailer[it] }
            val cheapestCents = item.cheapestCents
            val extra = if (priceAtPrimary != null && cheapestCents != null) priceAtPrimary - cheapestCents else null
            if (primary != null && cheapest != primary && extra != null && extra <= thresholdCents) {
                consolidations += Consolidation(item.name, cheapest, extra, item.row.itemId)
                assignedStore[item.row.itemId] = primary
            } else {
                assignedStore[item.row.itemId] = cheapest
            }
        }
        val consolidatedStores = assignedStore.values.distinct()
        val consolidationExtra = consolidations.sumOf { it.extraCents }

        return Plan(
            matchedCount = matched.size,
            unmatchedItems = unmatched,
            cheapestTotalCents = cheapestTotal,
            cheapestStores = cheapestStores,
            primaryStoreId = primary,
            consolidations = consolidations,
            consolidatedStores = consolidatedStores,
            consolidationExtraCents = consolidationExtra,
            positions = positions,
            actualTotalCents = actualTotal,
            actualStores = actualStores,
        )
    }

    private fun isCurrent(display: OfferDisplay, today: LocalDate): Boolean {
        fun date(value: String?): LocalDate? = value?.takeIf { it.isNotBlank() }?.let {
            runCatching { LocalDate.parse(it.take(10)) }.getOrNull()
        }
        val offer = display.offer
        if (!offer.validFrom.isNullOrBlank() && date(offer.validFrom) == null) return false
        if (!offer.validUntil.isNullOrBlank() && date(offer.validUntil) == null) return false
        return date(offer.validFrom)?.let { !today.isBefore(it) } != false &&
            date(offer.validUntil)?.let { !today.isAfter(it) } != false
    }
}
