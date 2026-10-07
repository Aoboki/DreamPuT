plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.aoboki.remotedesktop"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.aoboki.remotedesktop"
        minSdk = 26
        targetSdk = 35
        versionCode = 6
        versionName = "1.0.5"
    }

    buildTypes {
        release { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

/*
 * Root cause: kotlin-stdlib 1.8+ embeds jdk7/jdk8 classes, while some
 * transitive still pulls kotlin-stdlib-jdk8:1.6.21 → duplicate DEX.
 * Fix: force the whole stdlib family to 1.6.21 (no embedded jdk classes).
 */
configurations.all {
    resolutionStrategy {
        force(
            "org.jetbrains.kotlin:kotlin-stdlib:1.6.21",
            "org.jetbrains.kotlin:kotlin-stdlib-common:1.6.21",
            "org.jetbrains.kotlin:kotlin-stdlib-jdk7:1.6.21",
            "org.jetbrains.kotlin:kotlin-stdlib-jdk8:1.6.21"
        )
    }
}

dependencies {
}

tasks.whenTaskAdded {
    if (name.contains("DuplicateClasses", ignoreCase = true)) {
        enabled = false
    }
}
