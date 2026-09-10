package de.lesecuritae.korbuino.images

import android.graphics.Bitmap
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class ImageCacheTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test fun decodesCachedImagesOfflineAcrossLoaderRecreation()  = runBlocking {
        val file = File.createTempFile("image-test", ".png", context.cacheDir)
        try {
            val original = Bitmap.createBitmap(1024, 1024, Bitmap.Config.ARGB_8888)
            original.eraseColor(android.graphics.Color.RED)
            file.outputStream().use { original.compress(Bitmap.CompressFormat.PNG, 100, it) }
            original.recycle()
            repeat(2) {
                val thumbnail = ImageCache(context).thumbnail(file.path, null, null)
                assertNotNull(thumbnail)
                assertTrue(thumbnail!!.width <= 512)
                assertEquals(android.graphics.Color.RED, thumbnail.getPixel(0, 0))
                thumbnail.recycle()
            }
        } finally { file.delete() }
    }

    @Test fun missingAndInvalidImagesProduceNoBitmap()  = runBlocking {
        val file = File.createTempFile("image-test", ".png", context.cacheDir)
        try {
            file.writeText("<html>not an image</html>")
            val cache = ImageCache(context)
            assertNull(cache.thumbnail(file.path, null, null))
            assertNull(cache.thumbnail(null, null, null))
            assertNull(cache.download("javascript:alert(1)"))
            assertNull(cache.download("http://example.test/image.png"))
        } finally { file.delete() }
    }
}
