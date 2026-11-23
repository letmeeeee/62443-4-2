import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_debs')
STATE = Path('/tmp/em1000-debian13-apt')
ROOT.mkdir(parents=True, exist_ok=True)
for directory in ('debs/partial', 'provenance'):
    (ROOT / directory).mkdir(parents=True, exist_ok=True)
for directory in ('lists/partial', 'sourceparts', 'trustedparts', 'preferencesparts', 'aptparts'):
    (STATE / directory).mkdir(parents=True, exist_ok=True)
(STATE / 'status').touch()
(STATE / 'preferences').touch()
keys = []
for name in ('archive-key-13', 'archive-key-13-security', 'release-13'):
    url = 'https://ftp-master.debian.org/keys/' + name + '.asc'
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read()
    (ROOT / 'provenance' / (name + '.asc')).write_bytes(content)
    result = subprocess.run(['gpg', '--batch', '--dearmor'], input=content,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    keys.append(result.stdout)
(STATE / 'debian13.gpg').write_bytes(b''.join(keys))
sources = '\n'.join([
    'deb [arch=arm64 signed-by=' + str(STATE / 'debian13.gpg') + '] https://deb.debian.org/debian trixie main',
    'deb [arch=arm64 signed-by=' + str(STATE / 'debian13.gpg') + '] https://deb.debian.org/debian trixie-updates main',
    'deb [arch=arm64 signed-by=' + str(STATE / 'debian13.gpg') + '] https://security.debian.org/debian-security trixie-security main',
]) + '\n'
(STATE / 'sources.list').write_text(sources)
(ROOT / 'provenance' / 'sources.list').write_text(sources)
config = '''APT::Architecture "arm64";
APT::Architectures { "arm64"; };
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
Acquire::Retries "3";
Acquire::https::Timeout "60";
Acquire::AllowInsecureRepositories "false";
APT::Get::AllowUnauthenticated "false";
APT::Sandbox::User "''' + __import__('pwd').getpwuid(os.getuid()).pw_name + '''";
Dir::State::status "''' + str(STATE / 'status') + '''";
Dir::State::lists "''' + str(STATE / 'lists') + '''";
Dir::State::extended_states "''' + str(STATE / 'extended_states') + '''";
Dir::Cache::archives "''' + str(ROOT / 'debs') + '''";
Dir::Cache::pkgcache "''' + str(STATE / 'pkgcache.bin') + '''";
Dir::Cache::srcpkgcache "''' + str(STATE / 'srcpkgcache.bin') + '''";
Dir::Etc::sourcelist "''' + str(STATE / 'sources.list') + '''";
Dir::Etc::sourceparts "''' + str(STATE / 'sourceparts') + '''";
Dir::Etc::trusted "''' + str(STATE / 'debian13.gpg') + '''";
Dir::Etc::trustedparts "''' + str(STATE / 'trustedparts') + '''";
Dir::Etc::preferences "''' + str(STATE / 'preferences') + '''";
Dir::Etc::preferencesparts "''' + str(STATE / 'preferencesparts') + '''";
Dir::Etc::parts "''' + str(STATE / 'aptparts') + '''";
Dir::Etc::main "''' + str(STATE / 'no-system-config') + '''";
Dir::Log "''' + str(STATE) + '''";
'''
config_path = STATE / 'apt.conf'
config_path.write_text(config)
os.environ['APT_CONFIG'] = str(config_path)
(ROOT / 'provenance' / 'download-apt.conf').write_text(config)
base = ['apt-get', '-c', str(config_path)]
requested = ['libpython3.13', 'libpython3.13-minimal', 'libpython3.13-stdlib',
             'python3.13', 'python3.13-minimal', 'python3.13-venv',
             'python3-pip-whl', 'sshpass', 'python3', 'python3-venv', 'python3-pip']
(ROOT / 'requested-packages.txt').write_text('\n'.join(requested) + '\n')
def run(args, logname):
    print('Running:', ' '.join(args), flush=True)
    with (ROOT / 'provenance' / logname).open('w') as log:
        result = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((ROOT / 'provenance' / logname).read_text()[-12000:], flush=True)
        result.check_returncode()
run(base + ['update'], 'apt-update.log')
run(base + ['--simulate', '--no-install-recommends', 'install'] + requested, 'apt-plan.log')
run(base + ['--print-uris', '--yes', '--download-only', '--no-install-recommends', 'install'] + requested,
    'download-uris.log')
run(base + ['--yes', '--download-only', '--no-install-recommends', 'install'] + requested, 'apt-download.log')
for release in (STATE / 'lists').glob('*InRelease'):
    (ROOT / 'provenance' / release.name).write_bytes(release.read_bytes())
print('Download completed:', len(list((ROOT / 'debs').glob('*.deb'))), 'deb files', flush=True)
