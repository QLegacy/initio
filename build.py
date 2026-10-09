#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys

# Пакеты проекта: window.py лежит в initio, а аплеты (settings, wallpaper,
# winlist, ximage) импортируются как applet.* — собрать нужно оба.
PACKAGES = ("initio", "applet")


def build():
    print("[*] Starting build process for Initio...")

    # 1. Check for PyInstaller (import check, not PATH-dependent).
    #    A `pip install --user pyinstaller` puts the *script* in ~/.local/bin,
    #    which may not be on PATH even though the package itself is importable.
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[!] PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # 2. Clean previous builds
    for d in ("dist", "build"):
        if os.path.exists(d):
            shutil.rmtree(d)

    # 3. Run PyInstaller via `python -m PyInstaller`, so it doesn't depend on
    #    the script's install location being on PATH.
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name=initio",
        "--paths", ".",              # чтобы найти пакеты проекта рядом с main.py
        # Xlib грузит расширения (composite и др.) динамически — PyInstaller их не видит
        "--collect-submodules", "Xlib",
        "--hidden-import", "pam",
        "--hidden-import", "PIL.ImageOps",
    ]
    for pkg in PACKAGES:
        if os.path.isdir(pkg):
            cmd += ["--collect-all", pkg]
        else:
            print(f"[!] Package '{pkg}' not found next to build.py, skipping.")
    cmd.append("main.py")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[!] Build failed: {e}")
        sys.exit(1)

    print("\n[+] Build successful! Binary located in 'dist/initio/'")

    # 4. Installation instructions
    print("\n" + "=" * 50)
    print("INSTALLATION INSTRUCTIONS:")
    print("=" * 50)
    print("1. Move the 'initio' directory to /opt:")
    print("   sudo mv dist/initio /opt/")
    print("2. Create a symbolic link for the binary:")
    print("   sudo ln -sf /opt/initio/initio /usr/local/bin/initio")
    print("3. Register the session in your login manager:")
    print("   sudo bash -c 'cat > /usr/share/xsessions/initio.desktop <<EOF")
    print("[Desktop Entry]")
    print("Name=Initio")
    print("Exec=/usr/local/bin/initio")
    print("Type=Application")
    print("EOF'")
    print("=" * 50)
    print("Note: do NOT set the setuid bit (chmod +s) on the binary.")
    print("=" * 50)


if __name__ == "__main__":
    build()
