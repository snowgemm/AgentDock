package com.slg.agentdock.data.auth

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import java.security.GeneralSecurityException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class InMemoryBlob : SecureBlobStore {
    var bytes: ByteArray? = null
    override suspend fun read(): ByteArray? = bytes
    override suspend fun write(bytes: ByteArray) {
        this.bytes = bytes
    }

    override suspend fun clear() {
        bytes = null
    }
}

class EncryptedSessionStoreTest {
    private fun newKey(): SecretKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private val aad = "agentdock.session.v1".encodeToByteArray()
    private val session = StoredSession(
        accessToken = "access-token-value-1",
        refreshToken = "refresh-token-value-1",
        accessExpiresAtMs = 1_000L,
        sessionExpiresAtMs = 2_000L,
        userId = "user",
        tenantId = "tenant",
        sessionId = "session",
    )

    @Test
    fun roundTripsAndNeverStoresPlaintext() = runTest {
        val key = newKey()
        val blob = InMemoryBlob()
        val store = EncryptedSessionStore(blob, AesGcmCipher({ key }, aad))

        store.save(session)

        val raw = blob.bytes!!.decodeToString(throwOnInvalidSequence = false)
        assertFalse(raw.contains("access-token-value-1"))
        assertFalse(raw.contains("refresh-token-value-1"))
        assertEquals(session, store.load())
    }

    @Test
    fun usesFreshIvPerMessage() {
        val key = newKey()
        val cipher = AesGcmCipher({ key }, aad)
        val a = cipher.encrypt("same".encodeToByteArray())
        val b = cipher.encrypt("same".encodeToByteArray())
        assertNotEquals(a.toList(), b.toList())
        assertArrayEquals("same".encodeToByteArray(), cipher.decrypt(a))
    }

    @Test
    fun tamperedCiphertextIsDiscardedAsSignedOut() = runTest {
        val key = newKey()
        val blob = InMemoryBlob()
        val store = EncryptedSessionStore(blob, AesGcmCipher({ key }, aad))
        store.save(session)
        blob.bytes = blob.bytes!!.also { it[it.size - 1] = (it[it.size - 1].toInt() xor 0x01).toByte() }

        assertNull(store.load())
        assertNull(blob.bytes)
    }

    @Test
    fun missingKeyOrWrongPurposeCannotDecrypt() = runTest {
        val blob = InMemoryBlob()
        EncryptedSessionStore(blob, AesGcmCipher({ newKey() }, aad)).save(session)
        // A different key (e.g. the Keystore entry was wiped) reads as signed out.
        assertNull(EncryptedSessionStore(blob, AesGcmCipher({ newKey() }, aad)).load())

        val key = newKey()
        val other = AesGcmCipher({ key }, "other-purpose".encodeToByteArray())
        val sealed = AesGcmCipher({ key }, aad).encrypt("x".repeat(40).encodeToByteArray())
        assertThrows(GeneralSecurityException::class.java) { other.decrypt(sealed) }
    }

    @Test
    fun clearRemovesTheBlob() = runTest {
        val key = newKey()
        val blob = InMemoryBlob()
        val store = EncryptedSessionStore(blob, AesGcmCipher({ key }, aad))
        store.save(session)
        assertNotNull(blob.bytes)
        store.clear()
        assertNull(store.load())
    }

    @Test
    fun toStringDoesNotLeakTokens() {
        assertFalse(session.toString().contains("access-token-value-1"))
        assertFalse(session.toString().contains("refresh-token-value-1"))
    }
}
