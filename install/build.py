#!/usr/bin/env python3
import subprocess
import sys
import os
import shutil

def build():
    print("[*] Starting build process for Initio...")
    
    # 1. Check for PyInstaller
    if not shutil.which("pyinstaller"):
        print("[!] PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    # 2. Clean previous builds
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")

    # 3. Run PyInstaller
    # We collect the 'initio' package explicitly to ensure all internal modules are included
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--name=initio",
        "--collect-all", "initio",
        "main.py"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("\n[+] Build successful! Binary located in 'dist/initio/'")
        
        # 4. English installation instructions
        print("\n" + "="*50)
        print("INSTALLATION INSTRUCTIONS:")
        print("="*50)
        print("1. Move the 'initio' directory to /opt:")
        print("   sudo mv dist/initio /opt/")
        print("2. Create a symbolic link for the binary:")
        print("   sudo ln -sf /opt/initio/initio /usr/local/bin/initio")
        print("3. Set root privileges for PAM authentication:")
        print("   sudo chown root:root /usr/local/bin/initio")
        print("   sudo chmod +s /usr/local/bin/initio")
        print("4. Register the session in your login manager:")
        print("   sudo bash -c 'cat > /usr/share/xsessions/initio.desktop <<EOF")
        print("[Desktop Entry]")
        print("Name=Initio")
        print("Exec=/usr/local/bin/initio")
        print("Type=Application")
        print("EOF'")
        print("="*50)
        
    except subprocess.CalledProcessError as e:
        print(f"[!] Build failed: {e}")

if __name__ == "__main__":
    build()
