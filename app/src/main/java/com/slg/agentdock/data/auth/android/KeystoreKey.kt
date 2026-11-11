package com.slg.agentdock.data.auth.android

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/**
 * Returns the app-private AES-256 key stored in the Android Keystore, creating it on
 * first use. The key is non-exportable; androidx.security-crypto is deprecated so
 * the Keystore is used directly with AES-GCM.
 */
object KeystoreKey {
    const val SESSION_KEY_ALIAS = "agentdock_session_key_v1"

    @Synchronized
    fun getOrCreate(alias: String = SESSION_KEY_ALIAS): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private const val ANDROID_KEYSTORE = "AndroidKeyStore"
}
