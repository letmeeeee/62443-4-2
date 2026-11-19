"""Create an allowlisted build kit without any PKI, logs or runtime user data."""
from pathlib import Path
import zipfile

FILES = ('__init__.py','__main__.py','protocol.py','trust.py','runner.py','gui.py','windows_entry.py',
         'requirements-gui.txt','requirements-windows.txt','requirements.txt','build_windows.py',
         'build_windows.bat','build_installer.bat','GoosePublisher.iss','README.md','WINDOWS.md','THIRD-PARTY.md','.gitignore')


def main():
    package = Path(__file__).resolve().parent
    output = package/'dist'
    output.mkdir(exist_ok=True)
    target = output/'GoosePublisher-Windows-buildkit.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            data = (package/name).read_bytes()
            if name.endswith('.bat'):
                data = data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            archive.writestr('tools/goose_publisher/'+name,data)
        # An explicit package avoids conflicts with unrelated installed 'tools'.
        archive.writestr('tools/__init__.py','')
        archive.writestr('START-HERE.txt',
            'Windows 10/11 x64: install Python 3.12 x64 (with Tcl/Tk), then run\r\n'
            'tools\\goose_publisher\\build_windows.bat for the portable EXE.\r\n'
            'Install Inno Setup 6 and run build_installer.bat for the Setup EXE.\r\n'
            'Install Npcap separately from https://npcap.com/#download on the test PC.\r\n'
            'This archive is a build kit, not a compiled EXE. No private keys are included.\r\n')
    print(target)
    return target


if __name__ == '__main__':
    main()
