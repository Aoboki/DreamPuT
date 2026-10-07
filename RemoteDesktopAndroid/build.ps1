$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"
$env:ANDROID_HOME = "C:\0_AV\android-sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:PATH = "$env:JAVA_HOME\bin;C:\0_AV\platform-tools;C:\0_AV\gradle\gradle-9.8.0\bin;$env:PATH"
"sdk.dir=C:\\0_AV\\android-sdk" | Set-Content -Encoding ASCII "$ProjectRoot\local.properties"

Write-Host "==> Clean project + kotlin-stdlib-jdk caches"
& "C:\0_AV\gradle\gradle-9.8.0\bin\gradle.bat" --stop 2>$null
Remove-Item -Recurse -Force "$ProjectRoot\app\build","$ProjectRoot\build" -ErrorAction SilentlyContinue
$g = Join-Path $env:USERPROFILE ".gradle"
@(
  "caches\modules-2\files-2.1\org.jetbrains.kotlin\kotlin-stdlib-jdk7",
  "caches\modules-2\files-2.1\org.jetbrains.kotlin\kotlin-stdlib-jdk8",
  "caches\9.8.0\transforms"
) | ForEach-Object {
  $p = Join-Path $g $_
  if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}

Write-Host "==> ADB"
& "C:\0_AV\platform-tools\adb.exe" devices

Write-Host "==> assembleDebug"
& "C:\0_AV\gradle\gradle-9.8.0\bin\gradle.bat" :app:assembleDebug --no-daemon --rerun-tasks -x checkDebugDuplicateClasses
if ($LASTEXITCODE -ne 0) {
  Write-Host "---- errors ----"
  & "C:\0_AV\gradle\gradle-9.8.0\bin\gradle.bat" :app:compileDebugKotlin --no-daemon 2>&1 | Select-String -Pattern "e:|error:|FAILED"
  throw "BUILD FAILED"
}

$apk = Join-Path $ProjectRoot "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { throw "APK not found: $apk" }

Write-Host "==> Install"
& "C:\0_AV\platform-tools\adb.exe" install -r $apk
Write-Host "==> Start"
& "C:\0_AV\platform-tools\adb.exe" shell am start -n com.aoboki.remotedesktop/.MainActivity
Write-Host "OK - application started"
