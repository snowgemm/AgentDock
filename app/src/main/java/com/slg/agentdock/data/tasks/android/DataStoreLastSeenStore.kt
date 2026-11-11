package com.slg.agentdock.data.tasks.android

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.slg.agentdock.data.tasks.LastSeenStore
import kotlinx.coroutines.flow.first

private val Context.lastSeenStore by preferencesDataStore(name = "agentdock_last_seen")

/** Bounded: keeps the 100 most recently updated tasks. */
class DataStoreLastSeenStore(context: Context) : LastSeenStore {
    private val store = context.applicationContext.lastSeenStore

    override suspend fun get(taskId: String): Long =
        decode(store.data.first()[KEY]).firstOrNull { it.first == taskId }?.second ?: 0L

    override suspend fun put(taskId: String, sequence: Long) {
        store.edit { preferences ->
            val updated = listOf(taskId to sequence) +
                decode(preferences[KEY]).filter { it.first != taskId }
            preferences[KEY] = updated.take(MAX_ENTRIES).joinToString(";") { "${it.first}=${it.second}" }
        }
    }

    private fun decode(raw: String?): List<Pair<String, Long>> =
        raw.orEmpty().split(';').mapNotNull { entry ->
            val parts = entry.split('=')
            val sequence = parts.getOrNull(1)?.toLongOrNull()
            if (parts.size == 2 && parts[0].isNotBlank() && sequence != null) parts[0] to sequence else null
        }

    private companion object {
        const val MAX_ENTRIES = 100
        val KEY = stringPreferencesKey("last_seen_sequences")
    }
}
