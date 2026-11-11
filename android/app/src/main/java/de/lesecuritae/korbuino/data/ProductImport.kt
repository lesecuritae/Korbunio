package de.lesecuritae.korbuino.data

data class ProductImport(val products: List<ProductEntity>, val offers: List<OfferEntity>)

/** Names are search labels. Only source identity or an explicit GTIN can alias products. */
fun prepareProductImport(
    existingProducts: List<ProductEntity>, existingOffers: List<OfferEntity>,
    incomingProducts: List<ProductEntity>, incomingOffers: List<OfferEntity>,
): ProductImport {
    fun gtin(product: ProductEntity) = product.gtin?.trim()?.takeIf { it.matches(Regex("(?:\\d{8}|\\d{12,14})")) }
    fun identity(product: ProductEntity) = gtin(product)?.let { "gtin:$it" } ?: "source:${product.id}"
    require(incomingProducts.groupBy { it.id }.values.all { it.distinct().size == 1 }) {
        "Widersprüchliche Produktdaten für dieselbe Quell-ID"
    }
    val incoming = incomingProducts.distinctBy { it.id }
    val existingById = existingProducts.associateBy { it.id }
    val existingByGtin = existingProducts.filter { gtin(it) != null }.groupBy { gtin(it) }.mapValues { it.value.sortedBy { row -> row.id } }
    // Persist proven aliases in the existing identity-index column, so a
    // weekly offer-ID change does not detach a previously mapped favorite.
    val existingByIdentity = existingProducts.filter {
        it.normalizedKey.startsWith("source:") || it.normalizedKey == gtin(it)?.let { code -> "gtin:$code" }
    }.groupBy { it.normalizedKey }.mapValues { it.value.sortedBy { row -> row.id } }
    fun sourceId(product: ProductEntity): String {
        val previous = existingById[product.id]
        val code = gtin(product)
        // A reused source ID must not rewrite a different known GTIN that a
        // favorite or an offline offer still references.
        return if (code != null && previous != null && gtin(previous) != null && gtin(previous) != code)
            "${product.id}:gtin:$code" else product.id
    }
    val reservedIds = incoming.associate { sourceId(it) to identity(it) }
    val oldOffers = existingOffers.associateBy { it.id }
    val incomingById = incoming.associateBy { it.id }
    val legacyCandidates = incomingOffers.mapNotNull { offer ->
        val product = incomingById[offer.productId] ?: return@mapNotNull null
        val oldId = oldOffers[offer.id]?.productId ?: return@mapNotNull null
        val old = existingById[oldId] ?: return@mapNotNull null
        // Repair the historical name-only alias only when no conflicting
        // GTIN exists and this exact source offer still identifies the row.
        if (gtin(old) != null && gtin(old) != gtin(product)) return@mapNotNull null
        identity(product) to oldId
    }.groupBy({ it.first }, { it.second }).mapValues { it.value.toSet() }
    val legacyOwners = legacyCandidates.flatMap { (key, ids) -> ids.map { it to key } }
        .groupBy({ it.first }, { it.second }).mapValues { it.value.toSet() }
    val claimedIds = mutableMapOf<String, String>()
    val productIds = mutableMapOf<String, String>()
    val products = mutableListOf<ProductEntity>()
    incoming.groupBy(::identity).forEach { (key, group) ->
        fun available(id: String) = (reservedIds[id] == null || reservedIds[id] == key) &&
            (claimedIds[id] == null || claimedIds[id] == key)
        val direct = group.map(::sourceId).firstOrNull { it in existingById && available(it) }
        val exact = gtin(group.first())?.let { code -> existingByGtin[code].orEmpty().firstOrNull { available(it.id) }?.id }
        val legacy = legacyCandidates[key]?.singleOrNull()?.takeIf {
            legacyOwners[it]?.size == 1 && available(it)
        }
        val alias = existingByIdentity[key].orEmpty().firstOrNull { available(it.id) }?.id
        val canonicalId = direct ?: legacy ?: alias ?: exact ?: sourceId(group.first())
        check(available(canonicalId)) { "Produktidentität kollidiert beim Import" }
        claimedIds[canonicalId] = key
        group.forEach { productIds[it.id] = canonicalId }
        // Preserve the established ID while updating actual source metadata.
        products += group.first().copy(id = canonicalId, normalizedKey = key, gtin = group.first().gtin ?: existingById[canonicalId]?.gtin)
    }
    return ProductImport(products, incomingOffers.map { offer ->
        offer.copy(productId = productIds[offer.productId] ?: error("Angebot verweist auf unbekanntes Produkt"))
    }.distinctBy { it.id })
}
