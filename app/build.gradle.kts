plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.cachemon.iotracer"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.cachemon.iotracer"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    // Release signing is driven by environment variables (set by the release
    // workflow). When they are absent — e.g. a plain local `assembleDebug` — no
    // signing config is attached and the release variant is left unsigned.
    val envKeystoreFile = System.getenv("KEYSTORE_FILE")
    val envKeystorePassword = System.getenv("KEYSTORE_PASSWORD")
    val envKeyAlias = System.getenv("KEY_ALIAS")
    val envKeyPassword = System.getenv("KEY_PASSWORD")
    val hasSigningEnv = !envKeystoreFile.isNullOrEmpty() &&
        !envKeystorePassword.isNullOrEmpty() &&
        !envKeyAlias.isNullOrEmpty() &&
        !envKeyPassword.isNullOrEmpty()
    // Fail loudly on a half-configured keystore rather than silently publishing an
    // unsigned release: if a keystore is named, the rest must be present too.
    require(envKeystoreFile.isNullOrEmpty() || hasSigningEnv) {
        "KEYSTORE_FILE is set, but one or more of KEYSTORE_PASSWORD, KEY_ALIAS, " +
            "KEY_PASSWORD is missing or empty."
    }
    signingConfigs {
        create("release") {
            if (hasSigningEnv) {
                // Resolve a relative path against the repo root, not the app module.
                storeFile = rootProject.file(envKeystoreFile!!)
                storePassword = envKeystorePassword
                keyAlias = envKeyAlias
                keyPassword = envKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            if (hasSigningEnv) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    buildFeatures {
        compose = true
    }
    composeOptions {
        // Compose compiler matching Kotlin 1.9.24.
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.3")
    implementation("androidx.lifecycle:lifecycle-service:2.8.3")
    implementation("androidx.activity:activity-compose:1.9.0")

    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    debugImplementation("androidx.compose.ui:ui-tooling")

    testImplementation("junit:junit:4.13.2")
}
