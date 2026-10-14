package de.lesecuritae.korbuino

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
    private data class ItemOffers(val name: String, val pricePerRetailer: Map<String, Int>) {
        val cheapestRetailer: String? = pricePerRetailer.minByOrNull { it.value }?.key
        val cheapestCents: Int? = cheapestRetailer?.let { pricePerRetailer.getValue(it) }
    }

    data class Consolidation(val itemName: String, val skippedRetailerId: String, val extraCents: Int)

    data class Plan(
        val matchedCount: Int,
        val unmatchedItems: List<String>,
        val cheapestTotalCents: Int,
        val cheapestStores: List<String>,
        val primaryStoreId: String?,
        val consolidations: List<Consolidation>,
        val consolidatedStores: List<String>,
        val consolidationExtraCents: Int,
    ) {
        val hasPlan: Boolean get() = matchedCount > 0
        val savedTrips: Int get() = (cheapestStores.size - consolidatedStores.size).coerceAtLeast(0)
    }

    fun build(
        items: List<String>,
        offers: List<OfferDisplay>,
        selectedPrograms: Set<String>,
        thresholdCents: Int = DEFAULT_CONSOLIDATION_THRESHOLD_CENTS,
    ): Plan {
        // Each distinct item once, keeping the list order. Duplicate entries
        // (same product from two shops) must not count a shop twice.
        val seen = LinkedHashSet<String>()
        val distinct = items.map { it.trim() }.filter { it.isNotBlank() && seen.add(it.lowercase()) }

        val matched = mutableListOf<ItemOffers>()
        val unmatched = mutableListOf<String>()
        for (name in distinct) {
            val best = HashMap<String, Int>()
            for (match in OfferMatcher.matches(name, offers)) {
                val price = effectivePriceCents(match.offer, selectedPrograms)
                best.merge(match.offer.retailerId, price) { a, b -> minOf(a, b) }
            }
            if (best.isEmpty()) unmatched += name else matched += ItemOffers(name, best)
        }

        if (matched.isEmpty()) {
            return Plan(0, unmatched, 0, emptyList(), null, emptyList(), emptyList(), 0)
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
                consolidations += Consolidation(item.name, cheapest, extra)
                assignedStore[item.name] = primary
            } else {
                assignedStore[item.name] = cheapest
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
        )
    }
}
