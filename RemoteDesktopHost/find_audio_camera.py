
import cv2
import sounddevice as sd
import subprocess
from pathlib import Path


# ============================================================
# НАСТРОЙКИ
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DEVICES_FILE = SCRIPT_DIR / "devices.txt"


# ============================================================
# КАМЕРА
# ============================================================

def find_camera():
    print("=" * 60)
    print("📷 ПОИСК КАМЕРЫ")
    print("=" * 60)

    camera_index = None

    for index in range(10):
        print(f"Проверяю камеру index={index}...")

        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

        if cap.isOpened():
            ret, frame = cap.read()

            if ret and frame is not None:
                camera_index = index

                print(f"✅ Камера найдена: index={index}")

                cap.release()
                break

        cap.release()

    if camera_index is None:
        print("❌ Камера не найдена")
        return None

    # --------------------------------------------------------
    # Получаем название камеры из Windows
    # --------------------------------------------------------

    powershell_command = r'''
Get-CimInstance Win32_PnPEntity |
Where-Object {
    $_.PNPClass -eq "Camera"
} |
Select-Object -ExpandProperty Name
'''

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_command
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10
        )

        camera_names = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]

    except Exception as e:
        print(f"⚠️ Ошибка получения имени камеры: {e}")
        camera_names = []

    if camera_names:
        camera_name = camera_names[0]
    else:
        camera_name = "Integrated Webcam"

    print(f"📷 Имя камеры Windows: {camera_name}")
    print(f"📷 Camera index: {camera_index}")

    return f"video={camera_name}"


# ============================================================
# МИКРОФОН — WINDOWS AUDIO ENDPOINT
# ============================================================

def find_microphone_windows():
    print()
    print("=" * 60)
    print("🎤 ПОИСК МИКРОФОНА WINDOWS AUDIO ENDPOINT")
    print("=" * 60)

    powershell_command = r'''
Get-CimInstance Win32_PnPEntity |
Where-Object {
    $_.PNPClass -eq "AudioEndpoint"
} |
Select-Object Name, Status |
ForEach-Object {
    "$($_.Status)|$($_.Name)"
}
'''

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_command
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10
        )

    except Exception as e:
        print(f"❌ Ошибка запуска PowerShell: {e}")
        return None

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if not lines:
        print("❌ Windows не вернул AudioEndpoint")
        return None

    print()
    print("Все найденные AudioEndpoint:")
    print("-" * 60)

    audio_endpoints = []

    for line in lines:
        if "|" not in line:
            continue

        status, name = line.split("|", 1)

        status = status.strip()
        name = name.strip()

        audio_endpoints.append({
            "name": name,
            "status": status
        })

        print(f"Status: {status}")
        print(f"Name:   {name}")
        print("-" * 60)

    # --------------------------------------------------------
    # Ищем РАБОЧИЕ устройства
    # --------------------------------------------------------

    working = [
        device
        for device in audio_endpoints
        if device["status"].upper() == "OK"
    ]

    print()
    print(f"🟢 Рабочих AudioEndpoint: {len(working)}")

    # --------------------------------------------------------
    # Ищем именно МИКРОФОН
    #
    # Никакой привязки к:
    # Intel
    # Realtek
    # Jabra
    # NVIDIA
    # HP
    # и т.д.
    # --------------------------------------------------------

    microphone_candidates = []

    for device in working:

        name = device["name"]
        name_lower = name.lower()

        # Не берём системный Microsoft Sound Mapper
        if "microsoft sound mapper" in name_lower:
            continue

        # Не берём динамики
        if "speaker" in name_lower:
            continue

        if "headphone" in name_lower:
            continue

        # Не берём HDMI / Display Audio
        if "display audio" in name_lower:
            continue

        if "hdmi" in name_lower:
            continue

        # Ищем типичные названия микрофона
        if (
            "microphone" in name_lower
            or "microphone array" in name_lower
            or name_lower.startswith("mic ")
            or name_lower.startswith("mic-")
            or name_lower == "mic"
        ):
            microphone_candidates.append(device)

    # --------------------------------------------------------
    # Если нашли микрофоны
    # --------------------------------------------------------

    if microphone_candidates:

        print()
        print("🎤 Кандидаты на микрофон:")

        for i, device in enumerate(microphone_candidates):
            print(f"  [{i}] {device['name']}")

        selected = microphone_candidates[0]

        print()
        print(f"✅ Выбран микрофон:")
        print(f"   {selected['name']}")

        return f"audio={selected['name']}"

    # ========================================================
    # ЗАПАСНОЙ ВАРИАНТ
    # sounddevice
    # ========================================================

    print()
    print("⚠️ Windows AudioEndpoint не смог определить микрофон.")
    print("🔄 Использую резервный поиск через sounddevice...")

    try:
        devices = sd.query_devices()

        candidates = []

        for device in devices:

            name = device["name"]
            max_input = device["max_input_channels"]

            if max_input <= 0:
                continue

            name_lower = name.lower()

            # Не используем Microsoft Sound Mapper
            if "microsoft sound mapper" in name_lower:
                continue

            # Не используем явно выходные устройства
            if "speaker" in name_lower:
                continue

            if "headphone" in name_lower:
                continue

            candidates.append(device)

        print()
        print("🎤 sounddevice кандидаты:")

        for i, device in enumerate(candidates):
            print(
                f"  [{i}] "
                f"{device['name']} | "
                f"inputs={device['max_input_channels']}"
            )

        if candidates:

            # Сначала пытаемся найти устройство,
            # которое явно называется Microphone
            microphone = None

            for device in candidates:
                if "microphone" in device["name"].lower():
                    microphone = device
                    break

            if microphone is None:
                microphone = candidates[0]

            print()
            print(f"✅ Резервный микрофон:")
            print(f"   {microphone['name']}")

            return f"audio={microphone['name']}"

    except Exception as e:
        print(f"❌ Ошибка sounddevice: {e}")

    print()
    print("❌ Микрофон не найден.")

    return None


# ============================================================
# СОХРАНЕНИЕ
# ============================================================

def save_devices(camera_device, audio_device):

    print()
    print("=" * 60)
    print("💾 СОХРАНЕНИЕ DEVICES.TXT")
    print("=" * 60)

    lines = []

    if camera_device:
        lines.append(f"CAMERA_DEVICE={camera_device}")
    else:
        lines.append("CAMERA_DEVICE=")

    if audio_device:
        lines.append(f"AUDIO_DEVICE={audio_device}")
    else:
        lines.append("AUDIO_DEVICE=")

    try:

        DEVICES_FILE.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8"
        )

        print(f"✅ Файл сохранён:")
        print(f"   {DEVICES_FILE}")

        print()
        print("Содержимое:")
        print("-" * 60)
        print("\n".join(lines))
        print("-" * 60)

    except Exception as e:
        print(f"❌ Ошибка записи devices.txt: {e}")


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("🎥 UNIVERSAL CAMERA + MICROPHONE DETECTOR")
    print("=" * 60)
    print()

    camera_device = find_camera()

    audio_device = find_microphone_windows()

    save_devices(
        camera_device,
        audio_device
    )

    print()
    print("=" * 60)
    print("🏁 ГОТОВО")
    print("=" * 60)

    if camera_device:
        print(f"📷 CAMERA_DEVICE = {camera_device}")
    else:
        print("📷 CAMERA_DEVICE = НЕ НАЙДЕНА")

    if audio_device:
        print(f"🎤 AUDIO_DEVICE  = {audio_device}")
    else:
        print("🎤 AUDIO_DEVICE  = НЕ НАЙДЕН")

    print()


if __name__ == "__main__":
    main()

