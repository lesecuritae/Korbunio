package de.lesecuritae.korbuino.push

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import de.lesecuritae.korbuino.MainUiState
import de.lesecuritae.korbuino.MainViewModel
import kotlinx.coroutines.delay
import org.unifiedpush.android.connector.UnifiedPush

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

/** Push over UnifiedPush (NextPush, ntfy, ...): the app registers itself and tells the own server where to push. */
@Composable
internal fun PushSettingsCard(state: MainUiState, viewModel: MainViewModel) {
    val context = LocalContext.current
    fun enable() {
        val activity = context.findActivity() ?: return
        UnifiedPush.tryUseCurrentOrDefaultDistributor(activity) { ok ->
            if (ok) {
                UnifiedPush.register(context, messageForDistributor = "Korbuino: Angebotsmeldungen")
                viewModel.message("Push wird angemeldet…")
            } else {
                viewModel.message("Kein UnifiedPush-Verteiler gefunden. NextPush (oder ntfy) installieren und anmelden.")
            }
        }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { enable() }
    LaunchedEffect(Unit) { while (true) { viewModel.refreshPush(); delay(2000) } }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        Text("Push über UnifiedPush (z. B. NextPush)", style = MaterialTheme.typography.titleMedium)
        Text("Die App meldet sich bei deinem Verteiler an und gibt den Endpunkt an deinen Korbuino-Server weiter; Beobachtungen kommen dann als Benachrichtigung an. Server-Adresse unten eintragen.", style = MaterialTheme.typography.bodySmall)
        if (state.pushStatus.isNotBlank()) Text(state.pushStatus, style = MaterialTheme.typography.bodyMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                if (Build.VERSION.SDK_INT >= 33 && !PushNotifier.canNotify(context)) permission.launch(Manifest.permission.POST_NOTIFICATIONS) else enable()
            }) { Text(if (state.pushActive) "Neu anmelden" else "Aktivieren") }
            if (state.pushActive) {
                OutlinedButton(onClick = { viewModel.registerPushOnServer() }) { Text("Beim Server anmelden") }
                OutlinedButton(onClick = { UnifiedPush.unregister(context); viewModel.disablePush() }) { Text("Abmelden") }
            }
        }
    }
}
