"""Linux directory distribution with bundled Python/Tk/cryptography, no network build dependency."""
import importlib
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig


def build_portable_ca(root, destination, desktop='ca'):
    if platform.system() != 'Linux':
        raise ValueError('离线运行时打包仅支持 Linux；Windows 请使用 PyInstaller')
    destination = Path(destination)
    runtime = destination/'runtime'
    application = destination/'app'
    # Refuse stale or mixed runtime trees. The caller selects a new staging directory.
    runtime.mkdir(); application.mkdir()
    (runtime/'bin').mkdir(); (runtime/'lib').mkdir()
    version = 'python' + '.'.join(map(str,sys.version_info[:2]))
    python = Path(getattr(sys,'_base_executable',sys.executable)).resolve()
    shutil.copy2(python,runtime/'bin/python3')
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    target_stdlib = runtime/'lib'/version
    shutil.copytree(stdlib,target_stdlib,ignore=shutil.ignore_patterns(
        '__pycache__','*.pyc','*.pyo','test','tests','site-packages','dist-packages','ensurepip','idlelib'))
    packages = target_stdlib/'site-packages'; packages.mkdir()
    dependencies = ['cryptography','cffi','pycparser','_cffi_backend']
    if desktop=='device': dependencies.extend(('paramiko','nacl','bcrypt'))
    for name in dependencies:
        module = importlib.import_module(name)
        source = Path(module.__file__).resolve()
        if source.name=='__init__.py':
            shutil.copytree(source.parent,packages/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','tests'))
        else:
            shutil.copy2(source,packages/source.name)
    # Tcl's non-GUI interpreter locates Tcl resources without requiring a desktop display.
    import tkinter
    import _tkinter
    tcl = Path(tkinter.Tcl().eval('info library'))
    tk = tcl.parent/('tk'+_tkinter.TK_VERSION)
    if not tk.is_dir(): raise ValueError('找不到 Tk 资源目录: '+str(tk))
    (runtime/'share').mkdir()
    shutil.copytree(tcl,runtime/'share/tcl')
    shutil.copytree(tk,runtime/'share/tk')
    package = application/'provisioning'; package.mkdir()
    modules = ('__init__','common','ca','passwords','password_ui','ui') if desktop=='ca' else ('__init__','common','device','ssh_agent','ssh_device','deployment_record','ui')
    entry='ca_manager' if desktop=='ca' else 'device_deploy'
    for name in modules:
        shutil.copy2(root/'provisioning'/(name+'.py'),package/(name+'.py'))
    shutil.copy2(root/(entry+'.py'),application/(entry+'.py'))
    # Carry non-glibc shared dependencies. Use the host's glibc/loader on compatible targets.
    core = re.compile(r'^(?:ld-linux.*|lib(?:c|m|pthread|dl|rt|util|resolv|anl)\.so(?:\..*)?)$')
    binaries = [python]+list(runtime.rglob('*.so'))+list(runtime.rglob('*.so.*'))
    copied = set()
    while binaries:
        binary = binaries.pop()
        result = subprocess.run(['ldd',str(binary)],capture_output=True,text=True)
        if result.returncode: continue  # Some stdlib data files are not ELF objects.
        if 'not found' in result.stdout:
            raise ValueError('构建机动态库缺失: '+str(binary)+'\n'+result.stdout)
        for match in re.finditer(r'^\s*(\S+)\s+=>\s+(/[^\s]+)',result.stdout,re.M):
            soname, source = match.groups()
            if core.fullmatch(soname) or soname in copied: continue
            copied.add(soname)
            shutil.copy2(Path(source).resolve(),runtime/'lib'/soname)
            binaries.append(Path(source).resolve())
    # Include licenses for the bundled interpreter and Python dependencies.
    notices = destination/'licenses'; notices.mkdir()
    distributions = ['cryptography','cffi','pycparser']
    if desktop=='device': distributions.extend(('paramiko','PyNaCl','bcrypt'))
    for distribution in distributions:
        dist = importlib.metadata.distribution(distribution)
        for item in dist.files or ():
            if 'license' in item.name.lower() or item.name.lower().startswith('copying'):
                source = Path(dist.locate_file(item))
                if source.is_file(): shutil.copy2(source,notices/(distribution+'-'+item.name))
    for name, path in [('Python','/usr/share/doc/python3.8/copyright'),('Tcl','/usr/share/doc/tcl8.6/copyright'),('Tk','/usr/share/doc/tk8.6/copyright')]:
        if Path(path).is_file(): shutil.copy2(path,notices/(name+'-copyright.txt'))
    executable = destination/('LC400_CA_Manager' if desktop=='ca' else 'LC400_Device_Deploy')
    subprocess.run(['cc','-std=c99','-O2','-Wall','-Wextra','-Werror','-static',
                    '-DLC_PYTHON_SITE="runtime/lib/'+version+'/site-packages"',
                    '-DLC_APP_SCRIPT="app/'+entry+'.py"',
                    str(root/'provisioning/ca_launcher.c'),'-o',str(executable)],check=True)
    executable.chmod(0o755)
    return dict(builder='portable-runtime',python=platform.python_version(),
                minimum_glibc=platform.libc_ver()[1],self_contained_python=True,
                layout='directory: keep executable, app/ and runtime/ together')
