package de.lesecuritae.korbuino

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import de.lesecuritae.korbuino.images.ImageCache
import de.lesecuritae.korbuino.images.ImageFallback
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width

/**
 * Shared bounded image/cache path for search results and shopping-list offers. If the own picture cannot be loaded,
 * pictures of the same article at other retailers ([fallbacks]) are tried, and a substitute always carries its label.
 */
@Composable
internal fun OfferThumbnail(
    path: String?,
    url: String?,
    referer: String,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
    note: String? = null,
    fallbacks: List<ImageFallback> = emptyList(),
) {
    val context = LocalContext.current.applicationContext
    val cache = remember(context) { ImageCache.shared(context) }
    var bitmap by remember(path, url, referer) { mutableStateOf<android.graphics.Bitmap?>(null) }
    var shownNote by remember(path, url, referer, note) { mutableStateOf(note) }
    LaunchedEffect(path, url, referer, fallbacks) {
        bitmap = cache.thumbnail(path, url, referer)
        if (bitmap == null) {
            for (fallback in fallbacks) {
                val substitute = cache.thumbnail(null, fallback.url, fallback.referer)
                if (substitute != null) { bitmap = substitute; shownNote = fallback.note; break }
            }
        }
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier = modifier.size(68.dp).background(MaterialTheme.colorScheme.background, RoundedCornerShape(10.dp)),
            contentAlignment = Alignment.Center,
        ) {
            val loaded = bitmap
            if (loaded != null) Image(
                bitmap = loaded.asImageBitmap(),
                contentDescription = listOfNotNull(contentDescription, shownNote).joinToString(". ").ifBlank { null },
                contentScale = ContentScale.Fit,
                modifier = Modifier.size(62.dp).padding(3.dp),
            ) else Text(
                "🛒", style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.semantics { this.contentDescription = "Kein Produktbild verfügbar" },
            )
        }
        if (bitmap != null) shownNote?.let {
            Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 3, modifier = Modifier.width(68.dp))
        }
    }
}
