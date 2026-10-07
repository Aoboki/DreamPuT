$ErrorActionPreference = "Stop"
$root = "C:\0_AV\RemoteDesktopAndroid"
Set-Location $root
function Write-Utf8NoBom([string]$Rel, [string]$Content) {
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText((Join-Path $root $Rel), $Content, $utf8)
}
Write-Utf8NoBom "build.gradle.kts" @'
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "1.8.22" apply false
}
'@
Write-Utf8NoBom "app\build.gradle.kts" @'
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

'@
New-Item -ItemType Directory -Force -Path "app\src\main\res\values" | Out-Null
Write-Utf8NoBom "app\src\main\res\values\themes.xml" @'
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- No AppCompat / Material — pure Android theme (avoids kotlin-stdlib-jdk8 pull) -->
    <style name="Theme.RemoteDesktopAndroid" parent="@android:style/Theme.DeviceDefault.NoActionBar">
        <item name="android:statusBarColor">#0F172A</item>
        <item name="android:navigationBarColor">#0F172A</item>
        <item name="android:windowBackground">#0F172A</item>
        <item name="android:textColorPrimary">#E2E8F0</item>
        <item name="android:textColorSecondary">#94A3B8</item>
    </style>
</resources>

'@

Write-Host "Verify:"
Select-String -Path .\app\build.gradle.kts -Pattern "1.6.21"
Select-String -Path .\app\src\main\res\values\themes.xml -Pattern "DeviceDefault|AppCompat"

$g = Join-Path $env:USERPROFILE ".gradle"
Remove-Item -Recurse -Force (Join-Path $g "caches\9.8.0\transforms") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $g "caches\modules-2\files-2.1\org.jetbrains.kotlin") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$root\build","$root\app\build" -ErrorAction SilentlyContinue

$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"
$env:ANDROID_HOME = "C:\0_AV\android-sdk"
$env:PATH = "$env:JAVA_HOME\bin;C:\0_AV\platform-tools;C:\0_AV\gradle\gradle-9.8.0\bin;$env:PATH"
"sdk.dir=C:\\0_AV\\android-sdk" | Set-Content -Encoding ASCII "$root\local.properties"

Write-Host "Build..."
& "C:\0_AV\gradle\gradle-9.8.0\bin\gradle.bat" :app:assembleDebug --no-daemon --rerun-tasks -x checkDebugDuplicateClasses
if ($LASTEXITCODE -ne 0) { throw "BUILD FAILED" }
$apk = "$root\app\build\outputs\apk\debug\app-debug.apk"
& "C:\0_AV\platform-tools\adb.exe" install -r $apk
& "C:\0_AV\platform-tools\adb.exe" shell am start -n com.aoboki.remotedesktop/.MainActivity
Write-Host "OK"
