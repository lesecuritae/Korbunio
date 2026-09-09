package de.lesecuritae.korbuino

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { KorbuinoApp() }
    }
}

@Composable
private fun KorbuinoApp() {
    val viewModel: MainViewModel = viewModel()
    val state by viewModel.state.collectAsState()
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.padding(24.dp).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Korbuino", style = MaterialTheme.typography.headlineMedium)
                Text("Serverlose native Android-App", style = MaterialTheme.typography.titleMedium)
                Text("REWE-Angebote werden direkt abgerufen und lokal gespeichert.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(
                        value = state.postalCode,
                        onValueChange = viewModel::postalCode,
                        label = { Text("PLZ") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = state.city,
                        onValueChange = viewModel::city,
                        label = { Text("Stadt") },
                        singleLine = true,
                        modifier = Modifier.weight(2f),
                    )
                }
                Button(onClick = viewModel::refresh, enabled = !state.loading) {
                    if (state.loading) CircularProgressIndicator()
                    else Text("Angebote laden")
                }
                Text(state.message)
                LazyColumn(modifier = Modifier.fillMaxWidth().weight(1f)) {
                    items(state.offers, key = { it.id }) { offer ->
                        Text(
                            "${offer.productId.removePrefix("rewe-product-")} · ${offer.priceCents / 100},${(offer.priceCents % 100).toString().padStart(2, '0')} €",
                            modifier = Modifier.padding(vertical = 6.dp),
                        )
                    }
                }
            }
        }
    }
}
