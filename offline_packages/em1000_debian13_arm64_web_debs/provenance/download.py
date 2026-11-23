from pathlib import Path
import concurrent.futures, hashlib, json, os, re, shlex, shutil, subprocess, urllib.parse
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
state=Path('/tmp/em1000-web-apt')
env=dict(os.environ,APT_CONFIG=str(state/'apt.conf'),LC_ALL='C')
requested=(root/'requested-packages.txt').read_text().split()
(state/'uri-cache/partial').mkdir(parents=True,exist_ok=True)
plan=subprocess.check_output(['apt-get','-o','Dir::Cache::archives='+str(state/'uri-cache'),'--print-uris','--yes','--download-only','--no-install-recommends','install',*requested],env=env,text=True)
(root/'provenance/download-uris.log').write_text(plan)
(root/'provenance/apt-plan.log').write_text(subprocess.check_output(['apt-get','--simulate','--no-install-recommends','install',*requested],env=env,text=True))
urls=[shlex.split(line)[0] for line in plan.splitlines() if line.startswith("'")]
packages=[urllib.parse.unquote(url.rsplit('/',1)[1]).split('_')[0] for url in urls]
metadata=subprocess.check_output(['apt-cache','show',*packages],env=env,text=True)
def fields(block):
 return dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line[0].isspace())
index={fields(b).get('Filename'):fields(b) for b in metadata.split('\n\n') if b.startswith('Package: ')}
records=[]
for url in urls:
 filename=urllib.parse.unquote(url.split('/pool/',1)[1]); path='pool/'+filename
 info=index[path]
 assert info['Architecture'] in ('arm64','all'),info
 assert 'ubuntu' not in info['Version'].lower(),info
 records.append(dict(package=info['Package'],version=info['Version'],architecture=info['Architecture'],filename=Path(path).name,size_bytes=int(info['Size']),sha256=info['SHA256'],upstream_url=url,depends=info.get('Depends',''),pre_depends=info.get('Pre-Depends',''),provides=info.get('Provides','')))
(root/'provenance/selected-package-metadata.txt').write_text(metadata)
reuse=[Path('/home/wx/WorkStation/G3-package/Debian/EM1000config/python/offline_pkg/debs'),Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_debs/debs')]
def download(record):
 target=root/'debs'/record['filename']
 for directory in [root/'debs',*reuse]:
  src=directory/record['filename']
  if src.exists() and hashlib.sha256(src.read_bytes()).hexdigest()==record['sha256']:
   if src!=target:shutil.copy2(src,target)
   return 'cached '+record['package']
 # HTTP contents are checked against SHA256 in official, signature-verified APT indexes.
 candidates=[record['upstream_url'].replace('https://','http://',1),record['upstream_url']]
 for url in candidates:
  part=target.with_suffix('.partial')
  result=subprocess.run(['curl','--fail','--location','--silent','--show-error','--connect-timeout','15','--max-time','600','--retry','1','--continue-at','-','--output',str(part),url],capture_output=True,text=True)
  if result.returncode==0 and part.exists() and hashlib.sha256(part.read_bytes()).hexdigest()==record['sha256'] and part.stat().st_size==record['size_bytes']:
   part.replace(target)
   return 'downloaded '+record['package']
  if result.returncode in (0,33):part.unlink(missing_ok=True)
 raise RuntimeError('Download failed: '+record['filename']+' '+result.stderr[-250:])
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
 for future in concurrent.futures.as_completed([pool.submit(download,r) for r in records]):print(future.result(),flush=True)
(root/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
for name in ('sources.list','apt.conf','debian13.gpg','update.log'):
 shutil.copy2(state/name,root/'provenance'/name)
for release in (state/'lists').glob('*InRelease'):shutil.copy2(release,root/'provenance'/release.name)
for packages_index in (state/'lists').glob('*Packages'):
 import lzma
 with lzma.open(root/'provenance'/(packages_index.name+'.xz'),'wb',preset=1) as output:output.write(packages_index.read_bytes())
print('COMPLETE',len(records),round(sum(r['size_bytes'] for r in records)/1024**2,2),'MiB',flush=True)
