import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

val releaseKeystorePath = providers.environmentVariable("AGENTDOCK_KEYSTORE_PATH").orNull
val releaseStorePassword = providers.environmentVariable("AGENTDOCK_KEYSTORE_PASSWORD").orNull
val releaseKeyAlias = providers.environmentVariable("AGENTDOCK_KEY_ALIAS").orNull
val releaseKeyPassword = providers.environmentVariable("AGENTDOCK_KEY_PASSWORD").orNull
val canSignRelease = listOf(
    releaseKeystorePath,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword,
).all { !it.isNullOrBlank() }

val appVersionCode = providers.gradleProperty("agentdockVersionCode").orNull?.toIntOrNull() ?: 1
val appVersionName = providers.gradleProperty("agentdockVersionName").orNull ?: "0.1.0"

// Sign-in configuration is explicit and has no defaults. Supply these through
// Gradle properties (-P or ~/.gradle/gradle.properties); never commit real values
// that identify a private deployment. When any value is missing or invalid the app
// shows "sign-in not configured" and keeps working as a local-draft workspace.
fun optionalProperty(name: String): String =
    providers.gradleProperty(name).orNull?.trim().orEmpty()

fun buildConfigString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val oidcIssuer = optionalProperty("agentdockOidcIssuer")
val oidcClientId = optionalProperty("agentdockOidcClientId")
val oidcRedirectUri = optionalProperty("agentdockOidcRedirectUri")
val oidcScope = optionalProperty("agentdockOidcScope")
val oidcAudience = optionalProperty("agentdockOidcAudience")
val apiBaseUrl = optionalProperty("agentdockApiBaseUrl")
// AppAuth needs a redirect scheme placeholder for its manifest entry. An inert
// value that no provider can redirect to is used when sign-in is not configured.
val oidcRedirectScheme = runCatching { URI(oidcRedirectUri).scheme }.getOrNull()
    ?.takeIf { it.contains('.') }
    ?: "agentdock.signin.unconfigured"

android {
    namespace = "com.slg.agentdock"
    compileSdk = 36

    androidResources {
        generateLocaleConfig = true
    }

    defaultConfig {
        applicationId = "com.slg.agentdock"
        minSdk = 23
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
        manifestPlaceholders["appAuthRedirectScheme"] = oidcRedirectScheme
        buildConfigField("String", "OIDC_ISSUER", buildConfigString(oidcIssuer))
        buildConfigField("String", "OIDC_CLIENT_ID", buildConfigString(oidcClientId))
        buildConfigField("String", "OIDC_REDIRECT_URI", buildConfigString(oidcRedirectUri))
        buildConfigField("String", "OIDC_SCOPE", buildConfigString(oidcScope))
        buildConfigField("String", "OIDC_AUDIENCE", buildConfigString(oidcAudience))
        buildConfigField("String", "API_BASE_URL", buildConfigString(apiBaseUrl))
    }

    signingConfigs {
        if (canSignRelease) {
            create("release") {
                storeFile = file(requireNotNull(releaseKeystorePath))
                storePassword = requireNotNull(releaseStorePassword)
                keyAlias = requireNotNull(releaseKeyAlias)
                keyPassword = requireNotNull(releaseKeyPassword)
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            if (canSignRelease) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
        create("benchmark") {
            initWith(getByName("release"))
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources {
            excludes += setOf(
                "/META-INF/{AL2.0,LGPL2.1}",
                "/META-INF/DEPENDENCIES",
                "/META-INF/LICENSE*",
                "/META-INF/NOTICE*",
            )
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.06.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.navigation:navigation-compose:2.9.8")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.datastore:datastore-preferences:1.2.1")
    implementation("androidx.profileinstaller:profileinstaller:1.4.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.12.0")
    implementation("com.squareup.okhttp3:okhttp:5.5.1")
    implementation("com.squareup.okhttp3:okhttp-sse:5.5.1")
    implementation("net.openid:appauth:0.11.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("com.squareup.okhttp3:mockwebserver3:5.5.1")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.7.0")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}

