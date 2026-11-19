"""Build the Windows executable on Windows Python 3.10+ x64."""
import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--console',action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info < (3,10) or struct.calcsize('P') != 8:
        parser.error('使用 Windows Python 3.10+ x64（建议 3.12，含 Tcl/Tk）。Linux 不能直接构建 Windows EXE。')
    package = Path(__file__).resolve().parent
    root = package.parents[1]
    output = package/'dist'
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',
               '--console' if args.console else '--windowed','--name','GoosePublisher','--uac-admin',
               '--paths',str(root),'--distpath',str(output),'--workpath',str(package/'build-windows'),
               '--specpath',str(package/'build-windows'),'--noupx']
    for dependency in ('scapy','OpenSSL','cryptography'):
        command += ['--collect-all',dependency]
    for metadata in ('scapy','pyOpenSSL','cryptography'):
        command += ['--copy-metadata',metadata]
    command += [str(package/'windows_entry.py')]
    subprocess.run(command,cwd=root,check=True)
    for name in ('WINDOWS.md','README.md','THIRD-PARTY.md'):
        shutil.copyfile(package/name,output/name)
    print('Built: '+str(output/'GoosePublisher.exe'))


if __name__ == '__main__':
    main()
