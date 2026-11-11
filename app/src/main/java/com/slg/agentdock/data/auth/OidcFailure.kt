package com.slg.agentdock.data.auth

enum class OidcFailure {
    /** The user closed the browser or denied the request. */
    Cancelled,

    /** The redirect response failed state/redirect/client validation or carried an error. */
    CallbackRejected,

    /** The provider metadata or token endpoint could not be reached or was inconsistent. */
    ProviderUnavailable,
    Unexpected,
}

class OidcException(val failure: OidcFailure, cause: Throwable? = null) :
    Exception("Sign-in failed: $failure", cause)
