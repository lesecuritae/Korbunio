plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
    id("com.google.dagger.hilt.android")
}

android {
    namespace = "de.lesecuritae.korbuino"
    compileSdk = 37

    defaultConfig {
        // Keep the package used by the previously distributed Android app so
        // the native serverless release can replace it without losing data.
        applicationId = "de.korbunio.korbunio_app"
        minSdk = 26
        targetSdk = 37
        versionCode = 52
        versionName = "0.1.52"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables { useSupportLibrary = true }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            val releaseStore = System.getenv("KORBUINO_STORE_FILE")
            if (!releaseStore.isNullOrBlank()) {
                signingConfig = signingConfigs.create("korbuinoRelease") {
                    storeFile = file(releaseStore)
                    storePassword = System.getenv("KORBUINO_STORE_PASSWORD")
                    keyAlias = System.getenv("KORBUINO_KEY_ALIAS")
                    keyPassword = System.getenv("KORBUINO_KEY_PASSWORD")
                }
            }
            if (System.getenv("KORBUINO_REQUIRE_SIGNED_RELEASE") == "true") {
                require(!releaseStore.isNullOrBlank()) { "KORBUINO_STORE_FILE is required for a signed release" }
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true; buildConfig = true }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.core:core-ktx:1.19.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")

    implementation("androidx.room:room-runtime:2.8.5")
    implementation("androidx.room:room-ktx:2.8.5")
    ksp("androidx.room:room-compiler:2.8.5")
    implementation("androidx.work:work-runtime-ktx:2.11.2")
    implementation("com.google.dagger:hilt-android:2.60.1")
    ksp("com.google.dagger:hilt-compiler:2.60.1")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("com.google.net.cronet:cronet-okhttp:0.1.1")
    implementation("com.google.android.gms:play-services-cronet:18.1.1")
    implementation("org.conscrypt:conscrypt-android:2.7.0")
    implementation("com.google.android.material:material:1.14.0")
    implementation("androidx.security:security-crypto:1.1.0")
    implementation("org.jsoup:jsoup:1.23.2")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
    arg("room.generateKotlin", "true")
}
