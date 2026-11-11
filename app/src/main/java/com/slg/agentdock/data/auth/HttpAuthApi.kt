package com.slg.agentdock.data.auth

import com.slg.agentdock.data.net.await
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException

/**
 * Auth endpoints. [client] must NOT carry the session interceptor/authenticator:
 * these calls send explicit credentials (external token, refresh token, or the
 * access token being revoked) and must never trigger a refresh themselves.
 * Request and response bodies are never logged.
 */
class HttpAuthApi(
    private val client: OkHttpClient,
    baseUrl: HttpUrl,
    private val json: Json,
) : AuthApi {
    private val sessionUrl = baseUrl.newBuilder().addPathSegments("api/v1/auth/session").build()
    private val refreshUrl = baseUrl.newBuilder().addPathSegments("api/v1/auth/session/refresh").build()
    private val logoutUrl = baseUrl.newBuilder().addPathSegments("api/v1/auth/session/logout").build()

    override suspend fun createSession(externalAccessToken: String): SessionResponseDto =
        execute(
            Request.Builder()
                .url(sessionUrl)
                .header("Authorization", "Bearer $externalAccessToken")
                .post(ByteArray(0).toRequestBody())
                .build(),
        ) { decodeSession(it) }

    override suspend fun refresh(refreshToken: String): SessionResponseDto {
        val body = json.encodeToString(RefreshRequestDto.serializer(), RefreshRequestDto(refreshToken))
        return execute(
            Request.Builder()
                .url(refreshUrl)
                .post(body.toRequestBody(JSON_MEDIA_TYPE))
                .build(),
        ) { decodeSession(it) }
    }

    override suspend fun logout(accessToken: String) {
        execute(
            Request.Builder()
                .url(logoutUrl)
                .header("Authorization", "Bearer $accessToken")
                .post(ByteArray(0).toRequestBody())
                .build(),
        ) { }
    }

    private fun decodeSession(response: Response): SessionResponseDto {
        val dto = json.decodeFromString(
            SessionResponseDto.serializer(),
            response.peekBody(MAX_BODY_BYTES).string(),
        )
        if (!dto.tokenType.equals("Bearer", ignoreCase = true)) throw SerializationException("token_type")
        return dto
    }

    private suspend fun <T> execute(request: Request, onSuccess: (Response) -> T): T =
        withContext(Dispatchers.IO) {
            val response = try {
                client.newCall(request).await()
            } catch (error: IOException) {
                throw AuthApiException.Unavailable(null, error)
            }
            response.use {
                when {
                    it.isSuccessful -> try {
                        onSuccess(it)
                    } catch (error: SerializationException) {
                        throw AuthApiException.Protocol(error)
                    } catch (error: IllegalArgumentException) {
                        throw AuthApiException.Protocol(error)
                    } catch (error: IOException) {
                        throw AuthApiException.Unavailable(null, error)
                    }
                    it.code == 401 -> throw AuthApiException.Unauthorized()
                    it.code == 403 -> throw AuthApiException.Forbidden()
                    else -> throw AuthApiException.Unavailable(it.code)
                }
            }
        }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        const val MAX_BODY_BYTES = 64L * 1024L
    }
}
