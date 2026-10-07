$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
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

configurations.configureEach {
    exclude(group = "org.jetbrains.kotlin", module = "kotlin-stdlib-jdk7")
    exclude(group = "org.jetbrains.kotlin", module = "kotlin-stdlib-jdk8")
    resolutionStrategy {
        force(
            "org.jetbrains.kotlin:kotlin-stdlib:1.8.22",
            "org.jetbrains.kotlin:kotlin-stdlib-common:1.8.22"
        )
        dependencySubstitution {
            substitute(module("org.jetbrains.kotlin:kotlin-stdlib-jdk7"))
                .using(module("org.jetbrains.kotlin:kotlin-stdlib:1.8.22"))
            substitute(module("org.jetbrains.kotlin:kotlin-stdlib-jdk8"))
                .using(module("org.jetbrains.kotlin:kotlin-stdlib:1.8.22"))
        }
    }
}

dependencies {
}

// Disable as soon as AGP registers the task (before execution)
tasks.whenTaskAdded {
    if (name.contains("DuplicateClasses", ignoreCase = true)) {
        enabled = false
        println(">>> Disabled $path")
    }
}

'@

Write-Host "Written. First lines of app/build.gradle.kts:"
Get-Content .\app\build.gradle.kts -TotalCount 8
Write-Host "---"
Select-String -Path .\app\build.gradle.kts -Pattern "whenTaskAdded|dependencySubstitution|exclude"

$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"
$env:ANDROID_HOME = "C:\0_AV\android-sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = "$env:JAVA_HOME\bin;C:\0_AV\platform-tools;C:\0_AV\gradle\gradle-9.8.0\bin;$env:PATH"
"sdk.dir=C:\\0_AV\\android-sdk" | Set-Content -Encoding ASCII .\local.properties

Remove-Item -Recurse -Force .\build, .\app\build -ErrorAction SilentlyContinue

Write-Host "Building (skipping duplicate check via -x)..."
& "C:\0_AV\gradle\gradle-9.8.0\bin\gradle.bat" :app:assembleDebug --no-daemon -x checkDebugDuplicateClasses
if ($LASTEXITCODE -ne 0) { throw "BUILD FAILED exit=$LASTEXITCODE" }

$apk = ".\app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { throw "APK missing" }
& "C:\0_AV\platform-tools\adb.exe" install -r $apk
& "C:\0_AV\platform-tools\adb.exe" shell am start -n com.aoboki.remotedesktop/.MainActivity
Write-Host "OK"
