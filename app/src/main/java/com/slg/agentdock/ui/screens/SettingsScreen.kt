package com.slg.agentdock.ui.screens

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.data.model.AppPreferences

@Composable
fun SettingsScreen(
    serverUrl: String,
    preferences: AppPreferences,
    onSaveServerUrl: (String) -> Unit,
    onPreferencesChange: (AppPreferences) -> Unit,
    accountContent: @Composable () -> Unit = {},
) {
    var address by remember(serverUrl) { mutableStateOf(serverUrl) }
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .testTag("settings.screen")
            .padding(horizontal = 20.dp)
            .padding(top = 18.dp, bottom = 24.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = stringResource(R.string.settings_title),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = stringResource(R.string.settings_description),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        accountContent()

        SettingsSectionTitle(stringResource(R.string.settings_appearance))
        SettingsChoice(
            title = stringResource(R.string.theme_title),
            options = listOf(
                "system" to stringResource(R.string.theme_system),
                "dark" to stringResource(R.string.theme_dark),
                "light" to stringResource(R.string.theme_light),
            ),
            selected = preferences.themeMode,
            onSelected = { onPreferencesChange(preferences.copy(themeMode = it)) },
            tag = "settings.theme",
        )
        Spacer(Modifier.height(12.dp))
        SettingsChoice(
            title = stringResource(R.string.accent_title),
            options = listOf(
                "emerald" to stringResource(R.string.accent_emerald),
                "blue" to stringResource(R.string.accent_blue),
                "amber" to stringResource(R.string.accent_amber),
            ),
            selected = preferences.accentColor,
            onSelected = { onPreferencesChange(preferences.copy(accentColor = it)) },
            tag = "settings.accent",
        )
        Spacer(Modifier.height(12.dp))
        SettingsChoice(
            title = stringResource(R.string.font_size_title),
            options = listOf(
                "0.9" to stringResource(R.string.font_small),
                "1.0" to stringResource(R.string.font_default),
                "1.15" to stringResource(R.string.font_large),
            ),
            selected = preferences.fontScale.toString(),
            onSelected = {
                onPreferencesChange(preferences.copy(fontScale = it.toFloatOrNull() ?: 1f))
            },
            tag = "settings.fontSize",
        )
        Spacer(Modifier.height(5.dp))
        Text(
            text = stringResource(R.string.font_size_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        SettingsSectionTitle(stringResource(R.string.settings_experience))
        PreferenceSwitch(
            title = stringResource(R.string.haptics_title),
            description = stringResource(R.string.haptics_description),
            checked = preferences.hapticsEnabled,
            onCheckedChange = { onPreferencesChange(preferences.copy(hapticsEnabled = it)) },
            tag = "settings.haptics",
        )
        PreferenceSwitch(
            title = stringResource(R.string.sound_title),
            description = stringResource(R.string.sound_description),
            checked = preferences.soundEnabled,
            onCheckedChange = { onPreferencesChange(preferences.copy(soundEnabled = it)) },
            tag = "settings.sound",
        )

        SettingsSectionTitle(stringResource(R.string.settings_language))
        Text(
            text = stringResource(R.string.language_description),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = {
                if (Build.VERSION.SDK_INT >= 33) {
                    runCatching {
                        context.startActivity(
                            Intent(Settings.ACTION_APP_LOCALE_SETTINGS).putExtra(
                                Settings.EXTRA_APP_PACKAGE,
                                context.packageName,
                            ),
                        )
                    }.onFailure { error ->
                        if (error is ActivityNotFoundException) {
                            context.startActivity(
                                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                    data = android.net.Uri.parse("package:${context.packageName}")
                                },
                            )
                        }
                    }
                }
            },
            enabled = Build.VERSION.SDK_INT >= 33,
            modifier = Modifier.fillMaxWidth().testTag("settings.language"),
        ) {
            Text(stringResource(R.string.language_button))
        }
        if (Build.VERSION.SDK_INT < 33) {
            Text(
                text = stringResource(R.string.language_older_android),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        SettingsSectionTitle(stringResource(R.string.server_section))
        OutlinedTextField(
            value = address,
            onValueChange = { address = it },
            modifier = Modifier.fillMaxWidth().testTag("settings.serverUrl"),
            label = { Text(stringResource(R.string.server_url_label)) },
            placeholder = { Text(stringResource(R.string.server_url_hint)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            shape = RoundedCornerShape(12.dp),
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = stringResource(R.string.server_url_help),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = { onSaveServerUrl(address) },
            modifier = Modifier.fillMaxWidth().testTag("settings.saveServer"),
        ) {
            Text(stringResource(R.string.save_settings))
        }

        SettingsSectionTitle(stringResource(R.string.settings_connections))
        SettingsRow(
            title = stringResource(R.string.ai_provider_title),
            detail = stringResource(R.string.not_configured_yet),
        )
        Spacer(Modifier.height(14.dp))
        SettingsRow(
            title = stringResource(R.string.integrations_title),
            detail = stringResource(R.string.integrations_not_ready),
        )
        Spacer(Modifier.height(14.dp))
        SettingsRow(
            title = stringResource(R.string.security_title),
            detail = stringResource(R.string.security_summary),
        )
        Spacer(Modifier.height(22.dp))
        Text(
            text = stringResource(R.string.settings_version),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SettingsSectionTitle(title: String) {
    Spacer(Modifier.height(22.dp))
    HorizontalDivider(color = MaterialTheme.colorScheme.outline)
    Spacer(Modifier.height(16.dp))
    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(12.dp))
}

@Composable
private fun SettingsChoice(
    title: String,
    options: List<Pair<String, String>>,
    selected: String,
    onSelected: (String) -> Unit,
    tag: String,
) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(6.dp))
        Row(
            modifier = Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            options.forEach { (value, label) ->
                FilterChip(
                    selected = selected == value,
                    onClick = { onSelected(value) },
                    label = { Text(label, maxLines = 1) },
                    modifier = Modifier.testTag("$tag.$value"),
                )
            }
        }
    }
}

@Composable
private fun PreferenceSwitch(
    title: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    tag: String,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 64.dp)
            .toggleable(value = checked, role = Role.Switch, onValueChange = onCheckedChange)
            .testTag(tag),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
            Text(
                description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = checked, onCheckedChange = null)
    }
}

@Composable
private fun SettingsRow(title: String, detail: String) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(3.dp))
        Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
