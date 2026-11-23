import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

root = Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_debs')
state = Path('/tmp/em1000-debian13-apt')
os.environ['APT_CONFIG'] = str(state / 'apt.conf')
def fields(text):
    result = {}
    for line in text.splitlines():
        if line and not line[0].isspace() and ':' in line:
            name, value = line.split(':', 1)
            result[name] = value.strip()
    return result

uris = {}
for line in (root / 'provenance' / 'download-uris.log').read_text().splitlines():
    if line.startswith("'https://"):
        parts = shlex.split(line)
        uri, filename, size = parts[:3]
        filename = filename.replace('%3a', '_').replace('%3A', '_')
        uris[filename] = dict(url=uri, size=int(size))
entries = []
index = []
versions = {}
for deb in sorted((root / 'debs').glob('*.deb')):
    # Plain local filenames avoid percent-decoding ambiguity in file: APT URIs.
    local_name = deb.name.replace('%3a', '_').replace('%3A', '_')
    if local_name != deb.name:
        deb = deb.rename(deb.with_name(local_name))
    content = deb.read_bytes()
    metadata_text = subprocess.check_output(['dpkg-deb', '--field', str(deb)], text=True)
    metadata = fields(metadata_text)
    name, version, arch = (metadata[k] for k in ('Package', 'Version', 'Architecture'))
    assert arch in ('arm64', 'all'), (name, arch)
    assert name not in versions, name
    versions[name] = version
    candidate_text = subprocess.check_output(
        ['apt-cache', '-c', str(state / 'apt.conf'), 'show', name + '=' + version], text=True)
    candidates = [fields(block) for block in candidate_text.split('\n\n') if block.strip()]
    matching = [c for c in candidates if c.get('Package') == name and
                c.get('Version') == version and c.get('Architecture') == arch]
    assert matching, 'Missing signed index entry: ' + name
    digest = hashlib.sha256(content).hexdigest()
    assert any(c.get('SHA256') == digest and int(c['Size']) == len(content)
               for c in matching), 'Upstream SHA-256 mismatch: ' + name
    uri = uris[deb.name]
    assert uri['size'] == len(content)
    subprocess.run(['dpkg-deb', '--contents', str(deb)], stdout=subprocess.DEVNULL, check=True)
    entry = dict(package=name, version=version, architecture=arch,
                 filename='debs/' + deb.name, size_bytes=len(content), sha256=digest,
                 upstream_url=uri['url'], depends=metadata.get('Depends', ''),
                 pre_depends=metadata.get('Pre-Depends', ''))
    entries.append(entry)
    index.append(metadata_text.rstrip() + '\nFilename: debs/' + deb.name +
                 '\nSize: ' + str(len(content)) + '\nSHA256: ' + digest + '\n\n')
assert len(entries) == len(uris), 'Download set incomplete'
requested = (root / 'requested-packages.txt').read_text().splitlines()
assert set(requested).issubset(versions)
(root / 'Packages').write_text(''.join(index))
(root / 'Packages.gz').write_bytes(gzip.compress((root / 'Packages').read_bytes(), mtime=0))
(root / 'versions.lock.txt').write_text(''.join(e['package'] + '=' + e['version'] + '\n' for e in entries))
(root / 'manifest.json').write_text(json.dumps(dict(
    target=dict(device='EM-1000', distribution='Debian GNU/Linux 13 (trixie)', architecture='arm64'),
    repositories=['trixie/main', 'trixie-updates/main', 'trixie-security/main'],
    requested_packages=requested, package_count=len(entries), packages=entries),
    ensure_ascii=False, indent=2) + '\n')
verify_state = state / 'offline-verify'
for path in ('lists/partial', 'archives/partial', 'empty'):
    (verify_state / path).mkdir(parents=True, exist_ok=True)
(verify_state / 'status').write_text('')
(verify_state / 'sources.list').write_text('deb [trusted=yes] file:' + str(root) + ' ./\n')
config = (state / 'apt.conf').read_text()
config = config.replace(str(state), str(verify_state))
config = config.replace(str(root / 'debs'), str(verify_state / 'archives'))
config_path = verify_state / 'apt.conf'
config_path.write_text(config)
env = dict(os.environ, APT_CONFIG=str(config_path))
def run(args, logname):
    with (root / 'provenance' / logname).open('w') as log:
        result = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((root / 'provenance' / logname).read_text())
        result.check_returncode()
run(['apt-get', 'update'], 'offline-update.log')
run(['apt-get', '--simulate', '--no-install-recommends', 'install'] +
    [name + '=' + versions[name] for name in requested], 'offline-resolution.log')
run(['apt-get', '--yes', '--download-only', '--no-install-recommends', 'install'] +
    [name + '=' + versions[name] for name in requested], 'offline-file-access.log')
subprocess.run(['sh', '-n', str(root / 'install.sh')], check=True)
validation = dict(package_count=len(entries), architecture_arm64_or_all='passed',
                 official_repository_signatures='verified by APT',
                 sha256_against_official_signed_indexes='passed',
                 package_data_and_control_archives='passed',
                 offline_apt_dependency_resolution_empty_dpkg_status='passed',
                 offline_apt_package_file_access='passed',
                 installer_shell_syntax='passed',
                 device_installation='not performed')
(root / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
shutil.copy('/tmp/build_em1000_debs.py', root / 'provenance' / 'build_em1000_debs.py')
shutil.copy(__file__, root / 'provenance' / 'verify_em1000_debs.py')
for path in (root / 'debs' / 'lock',):
    if path.exists(): path.unlink()
partial = root / 'debs' / 'partial'
if partial.exists() and not list(partial.iterdir()): partial.rmdir()
files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
(root / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() +
    '  ' + p.relative_to(root).as_posix() + '\n' for p in files))
archive_path = root.with_suffix('.tar.gz')
with tarfile.open(archive_path, 'w:gz') as archive:
    archive.add(root, arcname=root.name)
archive_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
archive_path.with_name(archive_path.name + '.sha256').write_text(
    archive_digest + '  ' + archive_path.name + '\n')
with tempfile.TemporaryDirectory(prefix='em1000-deb-extract-') as tmp:
    with tarfile.open(archive_path) as archive:
        archive.extractall(tmp)
    result = subprocess.run(['sha256sum', '-c', 'SHA256SUMS'],
        cwd=str(Path(tmp) / root.name), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert result.returncode == 0, result.stdout
print(json.dumps(dict(archive=str(archive_path), size_MiB=round(archive_path.stat().st_size/1024/1024, 2),
    sha256=archive_digest, requested_versions={p: versions[p] for p in requested},
    validation=validation), ensure_ascii=False, indent=2))
