package de.lesecuritae.korbuino.grocy

import org.junit.Assert.assertEquals
import org.junit.Test

class GrocySyncPlanTest {
    @Test fun addsMissingAndNeverReAddsWhatIsStillOpenOnTheList() {
        val plan = GrocySyncPlan.plan(setOf("milch", "brot"), mapOf("milch" to "11"), setOf("11"))
        assertEquals(setOf("brot"), plan.toAdd); assertEquals(emptySet<String>(), plan.toRemoveKeys)
    }

    @Test fun removesOnlyRowsKorbuinoCreatedAndThatAreNoLongerWanted() {
        val plan = GrocySyncPlan.plan(setOf("brot"), mapOf("milch" to "11", "brot" to "12"), setOf("11", "12", "99"))
        assertEquals(setOf("milch"), plan.toRemoveKeys); assertEquals(emptySet<String>(), plan.toAdd)
    }

    @Test fun aRowDeletedInGrocyIsAddedAgainOnlyIfStillWanted() {
        val plan = GrocySyncPlan.plan(setOf("milch"), mapOf("milch" to "11"), emptySet())
        assertEquals(setOf("milch"), plan.toAdd)
    }

    @Test fun foreignRowsAreNeverInThePlan() {
        val plan = GrocySyncPlan.plan(emptySet(), emptyMap(), setOf("1", "2"))
        assertEquals(emptySet<String>(), plan.toRemoveKeys); assertEquals(emptySet<String>(), plan.toAdd)
    }
}
