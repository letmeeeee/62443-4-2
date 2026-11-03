"""Prepare an allowlisted Windows build kit, excluding all user keys and data."""
from pathlib import Path
import zipfile


FILES = (
    '__init__.py', '__main__.py', 'gui.py', 'core.py', 'certificates.py', 'certificate_crypto.py',
    'windows_entry.py', 'build_windows.py', 'build_windows.bat', 'requirements-windows.txt',
    'WINDOWS.md', 'README.md', '.gitignore',
)


def main():
    package = Path(__file__).resolve().parent
    output = package / 'dist'
    output.mkdir(exist_ok=True)
    target = output / 'ModbusTLS-Windows-buildkit.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            if name.endswith('.bat'):
                data = (package / name).read_text(encoding='utf-8').replace('\n', '\r\n')
                archive.writestr('tools/modbus_gui/' + name, data)
            else:
                archive.write(package / name, 'tools/modbus_gui/' + name)
        archive.writestr('START-HERE.txt', 'On Windows: install Python 3.12 x64, then double-click\r\n'
                          'tools\\modbus_gui\\build_windows.bat\r\n'
                          'Output: tools\\modbus_gui\\dist\\ModbusTLS.exe\r\n'
                          'See tools\\modbus_gui\\WINDOWS.md for instructions.\r\n')
    print(target)


if __name__ == '__main__':
    main()
