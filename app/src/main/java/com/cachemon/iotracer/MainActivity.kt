package com.cachemon.iotracer

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.cachemon.iotracer.ui.IOTracerTheme
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {

    private val requestNotif =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestNotif.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        // Probe root off the main thread once at launch.
        if (TracerState.status.value.rootAvailable == null) {
            thread(isDaemon = true) {
                val ok = TraceEngine.checkRoot()
                TracerState.update { it.copy(rootAvailable = ok) }
            }
        }

        setContent {
            IOTracerTheme {
                TracerScreen(
                    onStart = { anon, interval -> TracerService.start(this, anon, interval) },
                    onStop = { TracerService.stop(this) },
                    onShare = { shareLatest() },
                )
            }
        }
    }

    /** Zip nothing fancy — just share the session directory path via ACTION_SEND text. */
    private fun shareLatest() {
        val dir = TracerState.status.value.sessionDir ?: return
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, "IO Tracer session saved at:\n$dir")
        }
        startActivity(Intent.createChooser(send, "Share trace location"))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TracerScreen(
    onStart: (Boolean, Int) -> Unit,
    onStop: () -> Unit,
    onShare: () -> Unit,
) {
    val status by TracerState.status.collectAsState()
    var anonymous by remember { mutableStateOf(false) }
    var intervalMin by remember { mutableStateOf(5f) }

    Scaffold(
        topBar = { TopAppBar(title = { Text("IO Tracer (Android)") }) }
    ) { padding ->
        Column(
            Modifier
                .padding(padding)
                .padding(16.dp)
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Root status.
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Root access", style = MaterialTheme.typography.titleMedium)
                    Text(
                        when (status.rootAvailable) {
                            null -> "Checking…"
                            true -> "Available — full block-I/O tracing enabled."
                            false -> "Not available — needs a rooted/userdebug device. " +
                                "Block I/O cannot be traced without root."
                        }
                    )
                }
            }

            // Options.
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Options", style = MaterialTheme.typography.titleMedium)
                    Row(
                        Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Anonymize names/paths")
                        Switch(checked = anonymous, onCheckedChange = { anonymous = it }, enabled = !status.running)
                    }
                    Spacer(Modifier.padding(4.dp))
                    Text("Process snapshot interval: ${intervalMin.toInt()} min")
                    Slider(
                        value = intervalMin,
                        onValueChange = { intervalMin = it },
                        valueRange = 1f..30f,
                        steps = 28,
                        enabled = !status.running,
                    )
                }
            }

            // Live status.
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("Status", style = MaterialTheme.typography.titleMedium)
                    Text(if (status.running) "● Tracing" else "○ Idle")
                    Divider(Modifier.padding(vertical = 8.dp))
                    Text("Block I/O rows: ${status.dsRows}")
                    Text("Lines parsed: ${status.linesSeen}")
                    Text("Process rows: ${status.processRows}")
                    status.sessionDir?.let { Text("\nSession:\n$it") }
                    if (status.lastMessage.isNotEmpty()) {
                        Text("\n${status.lastMessage}", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            // Controls.
            if (!status.running) {
                Button(
                    onClick = { onStart(anonymous, (intervalMin.toInt() * 60)) },
                    enabled = status.rootAvailable != null,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Start tracing") }
            } else {
                Button(onClick = onStop, modifier = Modifier.fillMaxWidth()) {
                    Text("Stop tracing")
                }
            }

            Button(
                onClick = onShare,
                enabled = status.sessionDir != null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Share session location") }

            Text(
                "Traces are saved under the app's external files dir " +
                    "(Android/data/com.cachemon.iotracer/files/traces). Pull them with adb " +
                    "or a file manager. CSV columns match the Linux io-tracer schema.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
