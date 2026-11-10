package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.*
import org.junit.Assert.*
import org.junit.Test

class ProductImportTest {
    private fun product(id: String, gtin: String? = null) = ProductEntity(id, "Jacobs Krönung", normalizedKey = "jacobs-kronung", gtin = gtin)
    private fun offer(id: String, product: String, pack: String = "500 g") = OfferEntity(
        id, "edeka", product, externalId = id, priceCents = 649, sourceUrl = "https://example.invalid/", cachedAt = 1, packSize = pack,
    )

    @Test fun `same name never collapses the two source-proven coffee GTINs during actual import preparation`() {
        val products = listOf(product("ground", "8711000708651"), product("beans", "4000508059087"))
        val offers = listOf(offer("a", "ground"), offer("b", "beans"))
        val result = prepareProductImport(emptyList(), emptyList(), products, offers)
        assertEquals(2, result.products.size)
        assertEquals(2, result.offers.map { it.productId }.distinct().size)
        assertEquals(setOf("8711000708651", "4000508059087"), result.products.map { it.gtin }.toSet())
    }

    @Test fun `unverified same-name packs remain separate but an exact GTIN can share an established product`() {
        val unknown = prepareProductImport(emptyList(), emptyList(), listOf(product("small"), product("large")),
            listOf(offer("a", "small"), offer("b", "large", "1000 g")))
        assertEquals(2, unknown.products.size)
        val existing = product("favorite-id", "8711000708651")
        val result = prepareProductImport(listOf(existing), emptyList(), listOf(product("source-new", existing.gtin)), listOf(offer("new", "source-new")))
        assertEquals("favorite-id", result.offers.single().productId)
    }

    @Test fun `an exact old source offer preserves an unambiguous legacy favorite ID`() {
        val result = prepareProductImport(listOf(product("favorite-id")), listOf(offer("a", "favorite-id")),
            listOf(product("source-id")), listOf(offer("a", "source-id")))
        assertEquals("favorite-id", result.products.single().id)
        assertEquals("favorite-id", result.offers.single().productId)
        val nextWeek = prepareProductImport(result.products, result.offers, listOf(product("source-id")), listOf(offer("new-week", "source-id")))
        assertEquals("favorite-id", nextWeek.products.single().id)
        assertEquals("favorite-id", nextWeek.offers.single().productId)
    }

    @Test fun `an already collapsed historical row is not reused for two incoming identities`() {
        val result = prepareProductImport(listOf(product("legacy")), listOf(offer("a", "legacy"), offer("b", "legacy")),
            listOf(product("small"), product("large")), listOf(offer("a", "small"), offer("b", "large", "1000 g")))
        assertEquals(2, result.products.size)
        assertFalse(result.products.any { it.id == "legacy" })
    }

    @Test fun `a conflicting known GTIN preserves the old row for favorites and partial offline offers`() {
        val old = product("ground", "4000508059087") // Previously overwritten by the name-only merge.
        val incoming = listOf(product("ground", "8711000708651"), product("beans", "4000508059087"))
        for (order in listOf(incoming, incoming.reversed())) {
            val result = prepareProductImport(listOf(old), listOf(offer("a", "ground"), offer("b", "ground")), order,
                listOf(offer("a", "ground"), offer("b", "beans")))
            assertEquals(2, result.products.size)
            val byId = result.products.associateBy { it.id }
            assertEquals("8711000708651", byId.getValue(result.offers.single { it.id == "a" }.productId).gtin)
            assertEquals("ground", result.offers.single { it.id == "b" }.productId)
            assertEquals("4000508059087", byId.getValue("ground").gtin)
        }
        val partial = prepareProductImport(listOf(old), listOf(offer("a", "ground"), offer("b", "ground")),
            listOf(incoming.first()), listOf(offer("a", "ground")))
        assertNotEquals("ground", partial.offers.single().productId)
        assertEquals("4000508059087", old.gtin) // The caller does not delete the retained old row.
    }
}
