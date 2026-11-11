package com.slg.agentdock.data.auth.android

import android.content.Context
import android.util.Base64
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.slg.agentdock.data.auth.SecureBlobStore
import kotlinx.coroutines.flow.first

private val Context.sessionStore by preferencesDataStore(name = "agentdock_session")

/** Stores only already-encrypted bytes (base64) in a dedicated DataStore file. */
class DataStoreSecureBlob(context: Context) : SecureBlobStore {
    private val store = context.applicationContext.sessionStore

    override suspend fun read(): ByteArray? {
        val encoded = store.data.first()[BLOB_KEY] ?: return null
        return try {
            Base64.decode(encoded, Base64.NO_WRAP)
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    override suspend fun write(bytes: ByteArray) {
        val encoded = Base64.encodeToString(bytes, Base64.NO_WRAP)
        store.edit { it[BLOB_KEY] = encoded }
    }

    override suspend fun clear() {
        store.edit { it.remove(BLOB_KEY) }
    }

    private companion object {
        val BLOB_KEY = stringPreferencesKey("session_blob_v1")
    }
}
