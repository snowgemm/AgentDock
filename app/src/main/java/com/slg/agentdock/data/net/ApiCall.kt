package com.slg.agentdock.data.net

import com.slg.agentdock.data.auth.SessionUnavailableException
import com.slg.agentdock.data.auth.SignedOutException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

private const val MAX_BODY_BYTES = 2L * 1024L * 1024L

/**
 * Executes an authenticated API request and maps every outcome to [ApiResult].
 * The client carries the session interceptor; bodies are never logged.
 */
suspend fun <T> OkHttpClient.callApi(
    request: Request,
    parse: (String) -> T,
): ApiResult<T> = withContext(Dispatchers.IO) {
    val response = try {
        newCall(request).await()
    } catch (_: SignedOutException) {
        return@withContext ApiResult.Failure(ApiError.AuthRequired)
    } catch (_: SessionUnavailableException) {
        return@withContext ApiResult.Failure(ApiError.Offline)
    } catch (_: IOException) {
        return@withContext ApiResult.Failure(ApiError.Offline)
    }
    response.use {
        when {
            it.isSuccessful -> try {
                ApiResult.Success(parse(it.peekBody(MAX_BODY_BYTES).string()))
            } catch (_: SerializationException) {
                ApiResult.Failure(ApiError.Malformed)
            } catch (_: IllegalArgumentException) {
                ApiResult.Failure(ApiError.Malformed)
            } catch (_: IOException) {
                ApiResult.Failure(ApiError.Offline)
            }
            it.code == 401 -> ApiResult.Failure(ApiError.AuthRequired)
            it.code == 404 -> ApiResult.Failure(ApiError.NotFound)
            it.code == 409 -> ApiResult.Failure(ApiError.Conflict)
            it.code == 400 || it.code == 422 -> ApiResult.Failure(ApiError.Invalid)
            else -> ApiResult.Failure(ApiError.Server)
        }
    }
}
