package com.slg.agentdock.data.auth

import kotlinx.serialization.json.Json
import java.security.GeneralSecurityException
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

interface SessionStore {
    suspend fun load(): StoredSession?
    suspend fun save(session: StoredSession)
    suspend fun clear()
}

/** Persists an opaque byte blob. Implementations must never see plaintext tokens. */
interface SecureBlobStore {
    suspend fun read(): ByteArray?
    suspend fun write(bytes: ByteArray)
    suspend fun clear()
}

interface TokenCipher {
    fun encrypt(plain: ByteArray): ByteArray

    /** @throws GeneralSecurityException when the data is corrupt, tampered with or the key is gone. */
    fun decrypt(encrypted: ByteArray): ByteArray
}

/**
 * AES-256-GCM with a fresh random IV per message. The key comes from [keyProvider]
 * (the Android Keystore in production), so key material never enters the app process
 * for hardware-backed keys. [associatedData] binds ciphertext to this purpose.
 */
class AesGcmCipher(
    private val keyProvider: () -> SecretKey,
    private val associatedData: ByteArray,
) : TokenCipher {
    override fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, keyProvider())
        cipher.updateAAD(associatedData)
        val iv = cipher.iv
        check(iv.size == IV_BYTES) { "Unexpected GCM IV length." }
        return iv + cipher.doFinal(plain)
    }

    override fun decrypt(encrypted: ByteArray): ByteArray {
        if (encrypted.size <= IV_BYTES + TAG_BYTES) throw GeneralSecurityException("Ciphertext is too short.")
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            keyProvider(),
            GCMParameterSpec(TAG_BYTES * 8, encrypted, 0, IV_BYTES),
        )
        cipher.updateAAD(associatedData)
        return cipher.doFinal(encrypted, IV_BYTES, encrypted.size - IV_BYTES)
    }

    private companion object {
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BYTES = 16
    }
}

class EncryptedSessionStore(
    private val blobs: SecureBlobStore,
    private val cipher: TokenCipher,
    private val json: Json = Json { ignoreUnknownKeys = true },
) : SessionStore {
    override suspend fun load(): StoredSession? {
        val encrypted = blobs.read() ?: return null
        return try {
            json.decodeFromString(StoredSession.serializer(), cipher.decrypt(encrypted).decodeToString())
        } catch (_: GeneralSecurityException) {
            discardUnreadable()
        } catch (_: IllegalArgumentException) {
            // kotlinx.serialization failures extend IllegalArgumentException.
            discardUnreadable()
        } catch (_: IllegalStateException) {
            discardUnreadable()
        }
    }

    override suspend fun save(session: StoredSession) {
        val plain = json.encodeToString(StoredSession.serializer(), session).encodeToByteArray()
        try {
            blobs.write(cipher.encrypt(plain))
        } finally {
            plain.fill(0)
        }
    }

    override suspend fun clear() = blobs.clear()

    private suspend fun discardUnreadable(): StoredSession? {
        // An unreadable blob (lost Keystore key, corruption, tampering) means signed out.
        blobs.clear()
        return null
    }
}

