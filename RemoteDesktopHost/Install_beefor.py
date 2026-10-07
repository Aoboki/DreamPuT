
import sys
import subprocess
import importlib.util


# ============================================================
# INSTALL PACKAGE
# Устанавливает пакет ТОЛЬКО если его нет
# ============================================================

def install_package(package_name):
    print(f"📦 Installing {package_name}...")

    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        package_name
    ])

    print(f"✅ {package_name} installed")


# ============================================================
# CHECK PACKAGE
# ============================================================

def ensure_package(package_name, import_name=None):

    # Если имя импорта не указано,
    # используем имя pip-пакета
    if import_name is None:
        import_name = package_name

    # Проверяем, существует ли модуль
    if importlib.util.find_spec(import_name) is None:

        print(f"⚠️ {package_name} not found")

        # Устанавливаем только отсутствующий пакет
        install_package(package_name)

    else:

        print(f"✅ {package_name} already installed")


# ============================================================
# START
# ============================================================

print("=" * 60)
print("🔧 CHECKING PYTHON PACKAGES")
print("=" * 60)

print(f"🐍 Python: {sys.version}")
print(f"📁 Python executable: {sys.executable}")

print()


# ============================================================
# REQUIRED EXTERNAL PACKAGES
# ============================================================

# ------------------------------------------------------------
# psutil
# import psutil
# ------------------------------------------------------------

ensure_package(
    "psutil",
    "psutil"
)


# ------------------------------------------------------------
# websockets
# import websockets
# ------------------------------------------------------------

ensure_package(
    "websockets",
    "websockets"
)


# ------------------------------------------------------------
# OpenCV
# import cv2
# pip package = opencv-python
# ------------------------------------------------------------

ensure_package(
    "opencv-python",
    "cv2"
)


# ------------------------------------------------------------
# SoundDevice
# import sounddevice
# ------------------------------------------------------------

ensure_package(
    "sounddevice",
    "sounddevice"
)


# ------------------------------------------------------------
# aiortc
# from aiortc import ...
# ------------------------------------------------------------

ensure_package(
    "aiortc",
    "aiortc"
)


# ------------------------------------------------------------
# MSS
# from mss import MSS
# ------------------------------------------------------------

ensure_package(
    "mss",
    "mss"
)


# ------------------------------------------------------------
# Pillow
# from PIL import Image
# pip package = Pillow
# ------------------------------------------------------------

ensure_package(
    "Pillow",
    "PIL"
)


# ------------------------------------------------------------
# pynput — mouse / keyboard remote control
# ------------------------------------------------------------

ensure_package(
    "pynput",
    "pynput"
)

ensure_package(
    "pystray",
    "pystray"
)

# Optional fast desktop capture (Desktop Duplication API)
try:
    ensure_package("dxcam", "dxcam")
except Exception as e:
    print(f"⚠️ dxcam optional skip: {e}")


# ============================================================
# CHECK LOCAL PowerShellPC MODULE
# ============================================================

print()
print("=" * 60)
print("🔎 CHECKING LOCAL MODULES")
print("=" * 60)

if importlib.util.find_spec("PowerShellPC") is not None:

    print("✅ PowerShellPC.py found")

else:

    print("⚠️ PowerShellPC.py not found")
    print("   Make sure PowerShellPC.py is next to host.py")


# ============================================================
# FINAL CHECK
# ============================================================

print()
print("=" * 60)
print("🧪 FINAL IMPORT CHECK")
print("=" * 60)


packages = [
    ("psutil", "psutil"),
    ("websockets", "websockets"),
    ("opencv-python", "cv2"),
    ("sounddevice", "sounddevice"),
    ("aiortc", "aiortc"),
    ("mss", "mss"),
    ("Pillow", "PIL"),
    ("pynput", "pynput"),
    ("pystray", "pystray"),
]


all_ok = True


for package_name, import_name in packages:

    try:

        __import__(import_name)

        print(f"✅ {package_name}")

    except Exception as e:

        print(f"❌ {package_name}")
        print(f"   {e}")

        all_ok = False


# ============================================================
# RESULT
# ============================================================

print()
print("=" * 60)

if all_ok:

    print("✅ ALL REQUIRED PACKAGES ARE READY")

else:

    print("❌ SOME PACKAGES HAVE PROBLEMS")

print("=" * 60)

