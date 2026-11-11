
package com.slg.agentdock.ui.components

import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R

private const val ROUTE_HOME = "home"
private const val ROUTE_TABS = "tabs"
private const val ROUTE_ACTIVITY = "activity"
private const val ROUTE_SETTINGS = "settings"

@Composable
fun MainNavigationBar(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
) {
    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
    ) {
        NavigationBarItem(
            modifier = Modifier.testTag("navigation.home"),
            selected = currentRoute == ROUTE_HOME,
            onClick = { onNavigate(ROUTE_HOME) },
            icon = { Icon(Icons.Filled.Home, contentDescription = null, modifier = Modifier.size(22.dp)) },
            label = { Text(stringResource(R.string.home_nav)) },
        )
        NavigationBarItem(
            modifier = Modifier.testTag("navigation.tabs"),
            selected = currentRoute == ROUTE_TABS,
            onClick = { onNavigate(ROUTE_TABS) },
            icon = { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null, modifier = Modifier.size(22.dp)) },
            label = { Text(stringResource(R.string.tabs_nav)) },
        )
        NavigationBarItem(
            modifier = Modifier.testTag("navigation.activity"),
            selected = currentRoute == ROUTE_ACTIVITY || currentRoute?.startsWith("task/") == true,
            onClick = { onNavigate(ROUTE_ACTIVITY) },
            icon = { Icon(Icons.Filled.History, contentDescription = null, modifier = Modifier.size(22.dp)) },
            label = { Text(stringResource(R.string.activity_nav)) },
        )
        NavigationBarItem(
            modifier = Modifier.testTag("navigation.settings"),
            selected = currentRoute == ROUTE_SETTINGS,
            onClick = { onNavigate(ROUTE_SETTINGS) },
            icon = { Icon(Icons.Filled.Settings, contentDescription = null, modifier = Modifier.size(22.dp)) },
            label = { Text(stringResource(R.string.settings_nav)) },
        )
    }
}
