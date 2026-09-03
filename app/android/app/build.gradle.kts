plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "de.korbklar.korbklar_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "de.korbklar.korbklar_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    val releaseKeystorePath = System.getenv("KORBKLAR_STORE_FILE")
    val releaseBuildRequested = gradle.startParameter.taskNames.any { it.contains("release", ignoreCase = true) }

    signingConfigs {
        create("release") {
            if (!releaseKeystorePath.isNullOrBlank()) {
                storeFile = file(releaseKeystorePath)
                storePassword = System.getenv("KORBKLAR_STORE_PASSWORD")
                keyAlias = System.getenv("KORBKLAR_KEY_ALIAS")
                keyPassword = System.getenv("KORBKLAR_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            require(!releaseBuildRequested || !releaseKeystorePath.isNullOrBlank()) {
                "KORBKLAR_STORE_FILE is required for a signed release build"
            }
            if (!releaseKeystorePath.isNullOrBlank()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
