package com.slg.agentdock

import android.content.Context
import com.slg.agentdock.data.auth.AesGcmCipher
import com.slg.agentdock.data.auth.AuthConfig
import com.slg.agentdock.data.auth.AuthConfigResult
import com.slg.agentdock.data.auth.BearerInterceptor
import com.slg.agentdock.data.auth.EncryptedSessionStore
import com.slg.agentdock.data.auth.HttpAuthApi
import com.slg.agentdock.data.auth.SessionAuthenticator
import com.slg.agentdock.data.auth.SessionManager
import com.slg.agentdock.data.auth.android.AppAuthOidcClient
import com.slg.agentdock.data.auth.android.DataStoreSecureBlob
import com.slg.agentdock.data.auth.android.KeystoreKey
import com.slg.agentdock.data.auth.android.OidcClient
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Everything that exists only when sign-in is configured at build time. */
class AuthServices(
    val config: AuthConfig,
    val sessions: SessionManager,
    val oidc: OidcClient,
    /** Carries the session bearer token and refreshes it; use for AgentDock API calls only. */
    val apiHttp: OkHttpClient,
    val json: Json,
)

/** Manual dependency container; wiring stays in one reviewable place. */
class AppContainer(context: Context) {
    private val appContext = context.applicationContext

    val authConfig: AuthConfigResult = AuthConfig.parse(
        issuer = BuildConfig.OIDC_ISSUER,
        clientId = BuildConfig.OIDC_CLIENT_ID,
        redirectUri = BuildConfig.OIDC_REDIRECT_URI,
        scope = BuildConfig.OIDC_SCOPE,
        audience = BuildConfig.OIDC_AUDIENCE,
        apiBaseUrl = BuildConfig.API_BASE_URL,
    )

    val auth: AuthServices? by lazy {
        val config = (authConfig as? AuthConfigResult.Configured)?.config ?: return@lazy null
        val json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
        val baseClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            // The API never redirects; refusing redirects keeps bearer tokens on one origin.
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
        val store = EncryptedSessionStore(
            blobs = DataStoreSecureBlob(appContext),
            cipher = AesGcmCipher(
                keyProvider = { KeystoreKey.getOrCreate() },
                associatedData = "agentdock.session.v1".encodeToByteArray(),
            ),
            json = json,
        )
        val sessions = SessionManager(
            store = store,
            api = HttpAuthApi(baseClient, config.apiBaseUrl.toHttpUrl(), json),
        )
        AuthServices(
            config = config,
            sessions = sessions,
            oidc = AppAuthOidcClient(appContext, config),
            apiHttp = baseClient.newBuilder()
                .addInterceptor(BearerInterceptor(sessions))
                .authenticator(SessionAuthenticator(sessions))
                .build(),
            json = json,
        )
    }
}
