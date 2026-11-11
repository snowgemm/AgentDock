package com.slg.agentdock.data.net

enum class ApiError {
    /** No usable session; the user must sign in again. */
    AuthRequired,

    /** The device could not reach the server (offline, DNS, timeout, TLS). */
    Offline,

    /** The server answered with 5xx/429 or an unexpected status. */
    Server,
    NotFound,

    /** The idempotency key was reused for a different request or has expired. */
    Conflict,

    /** The server rejected the request content (422/400). */
    Invalid,

    /** The server answered successfully with something this client cannot parse. */
    Malformed,
}

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>

    data class Failure(val error: ApiError) : ApiResult<Nothing>
}

inline fun <T, R> ApiResult<T>.map(transform: (T) -> R): ApiResult<R> = when (this) {
    is ApiResult.Success -> ApiResult.Success(transform(value))
    is ApiResult.Failure -> this
}
