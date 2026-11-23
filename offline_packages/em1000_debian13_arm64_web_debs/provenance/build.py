from pathlib import Path
import hashlib, json, lzma, os, pwd, shutil, subprocess, tarfile, zipfile, zlib, copy
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
stage=Path('/tmp/em1000-web-stage'); state=Path('/tmp/em1000-web-apt')
base=Path('/home/wx/WorkStation/G3-package/Debian')
records=json.loads((root/'manifest.json').read_text())
# Independently check official signatures and the exact uncompressed APT indexes.
proof=[]
for release in sorted((state/'lists').glob('*InRelease')):
 result=subprocess.run(['gpgv','--status-fd','1','--keyring',str(state/'debian13.gpg'),str(release)],capture_output=True,text=True)
 # Debian dual-signs some indexes with old/new release keys. As with APT,
 # require a valid signature from our pinned Debian 13 keys; an unknown
 # additional Debian 12 co-signature does not invalidate the valid signature.
 assert '[GNUPG:] VALIDSIG ' in result.stdout,result.stderr
 assert not any('[GNUPG:] '+bad in result.stdout for bad in ('BADSIG ', 'EXPSIG ', 'EXPKEYSIG ', 'REVKEYSIG ')),result.stderr
 proof.append(result.stdout+result.stderr)
 entries={};active=False
 for line in release.read_text().splitlines():
  if line=='SHA256:':active=True;continue
  if active and not line.startswith(' '):active=False
  if active:
   digest,size,name=line.split();entries[name]=(digest,int(size))
 name='main/binary-arm64/Packages';digest,size=entries[name]
 packages_index=release.with_name(release.name.replace('_InRelease','_main_binary-arm64_Packages'))
 content=packages_index.read_bytes()
 assert len(content)==size and hashlib.sha256(content).hexdigest()==digest,release
 proof.append('PASS index SHA256 '+packages_index.name+'\n')
(root/'provenance/signature-verification.log').write_text(''.join(proof))
repo=stage/'offline-repo'
for name in ('debs','lists/partial','archives/partial','empty'):(repo/name).mkdir(parents=True,exist_ok=True)
index=[]
for record in records:
 deb=root/'debs'/record['filename']
 assert deb.stat().st_size==record['size_bytes'] and hashlib.sha256(deb.read_bytes()).hexdigest()==record['sha256']
 fields=subprocess.check_output(['dpkg-deb','--field',str(deb),'Package','Version','Architecture'],text=True)
 expected='Package: '+record['package']+'\nVersion: '+record['version']+'\nArchitecture: '+record['architecture']+'\n'
 # dpkg-deb multi-field output order is the requested order.
 assert fields==expected,(fields,expected)
 subprocess.run(['dpkg-deb','--contents',str(deb)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
 link=repo/'debs'/deb.name
 if not link.exists():link.symlink_to(deb)
 meta=subprocess.check_output(['dpkg-deb','--field',str(deb)],text=True)
 index.append(meta.rstrip()+'\nFilename: debs/'+deb.name+'\nSize: '+str(record['size_bytes'])+'\nSHA256: '+record['sha256']+'\n\n')
(repo/'Packages').write_text(''.join(index))
(repo/'status').write_text('')
(repo/'sources.list').write_text('deb [trusted=yes] file:'+str(repo)+' ./\n')
conf='APT::Architecture "arm64";\nAPT::Architectures { "arm64"; };\nAPT::Sandbox::User "'+pwd.getpwuid(os.getuid()).pw_name+'";\nAPT::Install-Recommends "false";\nAcquire::Languages "none";\n'
values={'Dir::Etc::parts':repo/'empty','Dir::Etc::main':repo/'no-main','Dir::Etc::sourcelist':repo/'sources.list','Dir::Etc::sourceparts':repo/'empty','Dir::Etc::preferences':repo/'no-preferences','Dir::Etc::preferencesparts':repo/'empty','Dir::State::status':repo/'status','Dir::State::lists':repo/'lists','Dir::State::extended_states':repo/'extended_states','Dir::Cache::archives':repo/'archives','Dir::Cache::pkgcache':repo/'pkgcache.bin','Dir::Cache::srcpkgcache':repo/'srcpkgcache.bin'}
conf+=''.join(name+' "'+str(path)+'";\n' for name,path in values.items())
(repo/'apt.conf').write_text(conf)
env=dict(os.environ,APT_CONFIG=str(repo/'apt.conf'),LC_ALL='C')
requested=(root/'requested-packages.txt').read_text().split()
for args,log in [(['update'],'offline-update.log'),(['--simulate','--no-remove','--no-install-recommends','install',*requested],'offline-resolution.log')]:
 result=subprocess.run(['apt-get',*args],env=env,capture_output=True,text=True)
 (root/'provenance'/log).write_text(result.stdout+result.stderr)
 assert result.returncode==0,result.stdout+result.stderr
# Nginx binary and modules must all match their declared source version/ARM64 ABI.
nginx=[r for r in records if r['package'] in ('nginx','nginx-common','nginx-core') or r['package'].startswith('libnginx-mod-')]
assert len({r['version'] for r in nginx})==1,nginx
elf_dir=stage/'nginx-elf';elf_dir.mkdir(exist_ok=True)
for record in nginx:
 if record['architecture']=='all':continue
 subprocess.run(['dpkg-deb','--extract',str(root/'debs'/record['filename']),str(elf_dir)],check=True)
elf_proof=[]
for path in [elf_dir/'usr/sbin/nginx',*sorted((elf_dir/'usr/lib/nginx/modules').glob('*.so'))]:
 header=subprocess.check_output(['readelf','-h',str(path)],text=True)
 assert 'AArch64' in header,path
 elf_proof.append(str(path.relative_to(elf_dir))+': AArch64\n')
(root/'provenance/elf-validation.log').write_text(''.join(elf_proof))
# Preserve the exact preparation sources used for this bundle.
shutil.copy2(state/'download.py',root/'provenance/download.py')
shutil.copy2(stage/'prepare.py',root/'provenance/prepare.py')
shutil.copy2(stage/'build.py',root/'provenance/build.py')
files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
(root/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n' for p in files))
subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=root,stdout=subprocess.DEVNULL,check=True)
archive=stage/'em1000-web-runtime-debian13-arm64.tar.gz'
with tarfile.open(archive,'w:gz') as output:output.add(root,arcname='em1000-web-runtime-debian13-arm64')
(stage/(archive.name+'.sha256')).write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
# Stage updated full archive from the current expanded files, preserving all current changes.
additions={'EM1000config/web/offline_pkg/'+p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file()}
with zipfile.ZipFile(base/'EM1000config.zip') as original, zipfile.ZipFile(stage/'EM1000config.zip','w') as output:
 existing=set()
 for info in original.infolist():
  existing.add(info.filename)
  if info.is_dir():output.writestr(copy.copy(info),b'');continue
  path=additions.get(info.filename,base/info.filename)
  with path.open('rb') as src,output.open(copy.copy(info),'w') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
 for name,path in additions.items():
  if name not in existing:output.write(path,arcname=name)
with zipfile.ZipFile(stage/'EM1000config.zip') as output:
 assert output.testzip() is None
 for info in output.infolist():
  if info.is_dir():continue
  data=additions.get(info.filename,base/info.filename).read_bytes()
  assert len(data)==info.file_size and zlib.crc32(data)==info.CRC,info.filename
(stage/'original-hashes.json').write_text(json.dumps({name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in ('setenv.sh','EM1000config.zip')},indent=2))
(stage/'verification-summary.json').write_text(json.dumps(dict(packages=len(records),size_bytes=sum(r['size_bytes'] for r in records),nginx_version=nginx[0]['version'],arm64=sum(r['architecture']=='arm64' for r in records),all=sum(r['architecture']=='all' for r in records),archive_bytes=archive.stat().st_size),indent=2))
print((stage/'verification-summary.json').read_text(),flush=True)
print('PASS signatures/indexes, all deb hashes/metadata/contents, offline dependency closure, Nginx ABI, SHA256SUMS and full zip CRC',flush=True)
