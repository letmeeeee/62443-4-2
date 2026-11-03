"""Build on Windows: python tools/modbus_gui/build_windows.py."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--console', action='store_true', help='Build a console version for diagnostics')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Windows EXE must be built using Windows Python; this is not a cross compiler.')
    if sys.version_info < (3, 10):
        parser.error('Use Windows Python 3.10 or newer (recommended: Python 3.12 x64).')
    import tkinter
    import cryptography
    import PyInstaller
    package = Path(__file__).resolve().parent
    root = package.parents[1]
    output = package / 'dist'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
               '--console' if args.console else '--windowed', '--name', 'ModbusTLS',
               '--paths', str(root), '--distpath', str(output), '--workpath', str(package / 'build-windows'),
               '--specpath', str(package / 'build-windows'), '--noupx',
               '--hidden-import', 'tools.modbus_gui.certificate_crypto', str(package / 'windows_entry.py')]
    subprocess.run(command, cwd=root, check=True)
    shutil.copyfile(package / 'WINDOWS.md', output / 'WINDOWS.md')
    shutil.copyfile(package / 'README.md', output / 'README.md')
    print('Built: ' + str(output / 'ModbusTLS.exe'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
