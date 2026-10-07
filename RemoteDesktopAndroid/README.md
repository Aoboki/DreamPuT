# DreamPUT Android Host

Phone registers on **https://remote.aoboki.pp.ua/** like a Windows PC:

- WebSocket: `wss://remote.aoboki.pp.ua/ws/host/{host_id}`
- Messages: `host_info` + `heartbeat` (same protocol as `agent.py` / host.py)

## Your tools (Windows)

| Tool | Path |
|------|------|
| JDK 17 | `C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot` |
| Android SDK | `C:\0_AV\android-sdk` |
| Gradle | `C:\0_AV\gradle\gradle-9.8.0` |
| ADB | `C:\0_AV\platform-tools\adb.exe` |
| Project | `C:\0_AV\RemoteDesktopAndroid` |
| Phone | Samsung SM-A325F, serial `RF8RA08ZCR` |

## Copy project

Copy this folder to:

```text
C:\0_AV\RemoteDesktopAndroid
```

## Build & install

PowerShell:

```powershell
cd C:\0_AV\RemoteDesktopAndroid
.\build.ps1
```

Or step by step:

```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"
$env:ANDROID_HOME = "C:\0_AV\android-sdk"
$env:PATH = "$env:JAVA_HOME\bin;C:\0_AV\platform-tools;C:\0_AV\gradle\gradle-9.8.0\bin;$env:PATH"

cd C:\0_AV\RemoteDesktopAndroid
echo sdk.dir=C:\\0_AV\\android-sdk > local.properties

gradle :app:assembleDebug --no-daemon
adb -s RF8RA08ZCR install -r app\build\outputs\apk\debug\app-debug.apk
adb -s RF8RA08ZCR shell am start -n ua.aoboki.remotedesktop/.MainActivity
```

## On the phone

1. Allow **Notifications** (Android 13+).
2. Tap **Start / Connect**.
3. Status should become **online**.
4. Open the site dashboard — card with Host ID (e.g. `sma325f_xxxxxx`) appears **Online**.

## VS Code

Open `C:\0_AV\RemoteDesktopAndroid` as folder. Optional extensions: Kotlin, Android.

## Next steps (later)

- Remote screen / camera over WebRTC (like PC Control / Webcam)
- Pairing token / auth
- Battery optimizations exemption

## Note about Gradle 9.8

If AGP 8.7.3 refuses Gradle 9.x, either:

- use Gradle **8.11.1** wrapper, or  
- bump AGP in `build.gradle.kts` to a version that supports Gradle 9.
