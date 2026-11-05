#!/usr/bin/env python3
"""Build CA and PC SSH desktop executables; optionally build the local device agent."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from build_provisioning_tools import build as build_zipapps

ROOT = Path(__file__).resolve().parent


def execute(*args):
    subprocess.run([str(a) for a in args], cwd=str(ROOT), check=True)


def archive(directory):
    if os.name == 'nt':
        output = directory.with_suffix('.zip')
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as stream:
            for path in directory.rglob('*'):
                if path.is_file(): stream.write(path,str(path.relative_to(directory.parent)))
    else:
        output = directory.with_suffix('.tar.gz')
        with tarfile.open(output,'w:gz') as stream: stream.add(directory,arcname=directory.name)
    return output


def write_hashes(directory):
    files = {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'}
    (directory/'SHA256SUMS').write_text(''.join(value+'  '+name+'\n' for name,value in files.items()),encoding='utf-8')


def build_ca(output, builder='auto'):
    architecture = platform.machine().lower()
    tag = ('windows-' if os.name=='nt' else 'linux-') + architecture
    destination = output/('LC400_CA_'+tag)
    if builder=='auto':
        builder = 'pyinstaller' if importlib.util.find_spec('PyInstaller') else 'portable'
    with tempfile.TemporaryDirectory(prefix='.ca-build-',dir=str(output)) as temporary:
        stage = Path(temporary)/destination.name
        stage.mkdir()
        info = dict(platform=platform.platform(),architecture=architecture,python=platform.python_version(),
                    executable='LC400_CA_Manager.exe' if os.name=='nt' else 'LC400_CA_Manager')
        if builder=='portable':
            from provisioning.portable_build import build_portable_ca
            info.update(build_portable_ca(ROOT,stage))
        else:
            execute(sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',
                    '--name','LC400_CA_Manager','--distpath',stage,
                    '--workpath',Path(temporary)/'work','--specpath',temporary,
                    '--collect-all','cryptography','--hidden-import','provisioning.ui',ROOT/'ca_manager.py')
            info.update(builder='pyinstaller',self_contained_python=True,layout='single-file')
        executable = stage/info['executable']
        result = subprocess.run([str(executable),'--help'],capture_output=True,text=True)
        if result.returncode: raise RuntimeError('CA executable startup failed: '+result.stderr[-5000:])
        if '--vault-file' not in result.stdout: raise RuntimeError('CA executable/password CLI smoke check failed')
        shutil.copyfile(ROOT/'provisioning/README.md',stage/'使用说明.md')
        (stage/'运行说明.txt').write_text(
            '直接运行 LC400_CA_Manager（Windows 为 .exe）启动 GUI；--help 查看命令行。\n'
            '包含 Python、Tk 和 cryptography；GUI 需要桌面显示环境。\n'
            '目录式发行包请保留 app/、runtime/ 与可执行文件在一起，移动时移动整个文件夹。\n'
            '默认 CA 数据在当前用户主目录/lc400-ca；加密口令文件另选目录。\n'
            '支持随机生成、加密保存、读取 CA 口令；文件保护口令至少12位且须单独保管。\n'
            '该包不含任何正式 CA 私钥或口令；仅支持包名对应系统/架构。\n'
            'Linux 最低 glibc 版本见 build-info.json；Windows EXE 须在 Windows 环境构建。\n',encoding='utf-8')
        (stage/'build-info.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
        write_hashes(stage)
        backup = Path(temporary)/'previous'
        if destination.exists():
            if not (destination/'build-info.json').is_file():
                raise ValueError('拒绝覆盖不是本工具生成的目录: '+str(destination))
            os.rename(destination,backup)
        try: os.rename(stage,destination)
        except Exception:
            if backup.exists(): os.rename(backup,destination)
            raise
    return destination/info['executable'],archive(destination)


def build_device_agent(output, architecture):
    if platform.system() != 'Linux': raise ValueError('设备 ELF 请在 Linux 构建')
    if architecture not in ('aarch64','x86_64'): raise ValueError('Unsupported device architecture')
    compiler = 'aarch64-linux-gnu-gcc' if architecture=='aarch64' and platform.machine() not in ('aarch64','arm64') else 'cc'
    if not shutil.which(compiler): raise ValueError('缺少编译器: '+compiler)
    destination = output/('LC400_Device_Agent_linux-'+architecture)
    destination.mkdir(parents=True,exist_ok=True)
    target = destination/'LC400_Device_Agent'
    with tempfile.TemporaryDirectory(prefix='lc400-device-elf-') as temporary:
        stage = Path(temporary)
        build_zipapps(stage)
        launcher = stage/'launcher'
        execute(compiler,'-std=c99','-O2','-Wall','-Wextra','-Werror','-static',
                ROOT/'provisioning/device_launcher.c','-o',launcher)
        # ZIP offsets support a leading native ELF; Python's zipimport reads the appended application.
        with target.open('wb') as stream:
            stream.write(launcher.read_bytes());stream.write((stage/'device_agent.pyz').read_bytes())
        target.chmod(0o755)
    shutil.copyfile(ROOT/'provisioning/README.md',destination/'使用说明.md')
    (destination/'运行说明.txt').write_text(
        '本地应急后端：chmod +x LC400_Device_Agent；./LC400_Device_Agent --help\n'
        '无参数为 GUI（设备需桌面和 tkinter）；无桌面时使用 CLI。\n'
        '本文件为静态 Linux ELF 启动器 + 内嵌 Python 应用，仍使用设备已有 Python 3.8+。\n'
        '默认优先 /home/zlg/myenv/bin/python3，再 /usr/bin/python3、/usr/local/bin/python3；\n'
        '可通过 LC400_PYTHON=/绝对路径/python3 指定解释器。\n'
        '仍需当前版本 app 配套脚本、modbus_tee_identity、OpenSSL；应用需 Nginx/systemd 维护权限。\n'
        'INI 沿用设备原配置；tems 服务名必须使用设备实际名称。\n',encoding='utf-8')
    (destination/'build-info.json').write_text(json.dumps(dict(
        architecture=architecture,format='static-ELF+zipapp',requires_device_python='>=3.8',
        self_contained_python=False,compiler=compiler),indent=2),encoding='utf-8')
    write_hashes(destination)
    return target,archive(destination)


def build_device(output,builder='auto'):
    architecture=platform.machine().lower()
    tag=('windows-' if os.name=='nt' else 'linux-')+architecture
    destination=output/('LC400_Device_PC_'+tag)
    if builder=='auto': builder='pyinstaller' if importlib.util.find_spec('PyInstaller') else 'portable'
    with tempfile.TemporaryDirectory(prefix='.pc-ssh-build-',dir=str(output)) as temporary:
        stage=Path(temporary)/destination.name;stage.mkdir()
        info=dict(platform=platform.platform(),architecture=architecture,mode='pc-ssh',
                  executable='LC400_Device_Deploy.exe' if os.name=='nt' else 'LC400_Device_Deploy')
        if builder=='portable':
            from provisioning.portable_build import build_portable_ca
            info.update(build_portable_ca(ROOT,stage,desktop='device'))
        else:
            command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile',
                     '--name','LC400_Device_Deploy','--distpath',stage,'--workpath',Path(temporary)/'work',
                     '--specpath',temporary,'--collect-all','paramiko','--collect-all','cryptography']
            for name in ('__init__','common','device','ssh_agent'):
                command+=['--add-data',str(ROOT/'provisioning'/(name+'.py'))+os.pathsep+'provisioning']
            execute(*command,ROOT/'device_deploy.py')
            info.update(builder='pyinstaller',self_contained_python=True,layout='single-file')
        executable=stage/info['executable']
        result=subprocess.run([str(executable),'--help'],capture_output=True,text=True)
        if result.returncode or '--host-fingerprint' not in result.stdout:
            raise RuntimeError('PC SSH executable startup failed: '+result.stderr[-3000:])
        shutil.copyfile(ROOT/'provisioning/SSH_DEPLOY.md',stage/'SSH部署说明.md')
        (stage/'运行说明.txt').write_text(
            '在 PC 上运行 LC400_Device_Deploy，通过 SSH/SFTP 连接设备。\n'
            '支持 SSH 口令、私钥、SSH Agent；主机必须已在 known_hosts 中或核对后填写 SHA256 指纹。\n'
            '设备只需已有 Python3、当前 app 脚本及 modbus_tee_identity；临时执行代码自动上传和清理。\n'
            'CSR 生成后下载至 PC；签发证书包由 PC 上传。设备私钥及 CA 私钥均不传输。\n'
            '目录式发行包请保留 runtime/、app/ 和可执行文件在一起。\n'
            '支持原有 file/TEE 模式，INI 由设备现有配置提供。\n',encoding='utf-8')
        (stage/'build-info.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
        write_hashes(stage)
        backup=Path(temporary)/'previous'
        if destination.exists():
            if not (destination/'build-info.json').is_file(): raise ValueError('拒绝覆盖未知目录')
            os.rename(destination,backup)
        try:os.rename(stage,destination)
        except Exception:
            if backup.exists():os.rename(backup,destination)
            raise
    return destination/info['executable'],archive(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'provisioning/build-output/executables')
    parser.add_argument('--tool',choices=['all','ca','device','device-agent'],default='all')
    parser.add_argument('--ca-builder',choices=['auto','pyinstaller','portable'],default='auto')
    parser.add_argument('--device-arch',choices=['aarch64','x86_64'],default='aarch64')
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    outputs=[]
    if args.tool in ('all','ca'): outputs.extend(build_ca(args.out,args.ca_builder))
    if args.tool in ('all','device'): outputs.extend(build_device(args.out,args.ca_builder))
    if args.tool=='device-agent': outputs.extend(build_device_agent(args.out,args.device_arch))
    print('\nArtifacts:\n'+'\n'.join(str(p) for p in outputs))


if __name__=='__main__': main()
