from pathlib import Path
import hashlib,subprocess,json
stage=Path('/tmp/em1000-pcre3-update')
name='libpcre3_8.39-15_arm64.deb'
expected='ffff38112e92b032688c0efdc19673686feb2aff8b85f65f54d9f2f6b55992d9'
url='https://deb.debian.org/debian/pool/main/p/pcre3/'+name
for candidate in (url.replace('https://','http://',1),url):
 result=subprocess.run(['curl','--fail','--location','--silent','--show-error','--connect-timeout','15','--max-time','120','--retry','1','--output',str(stage/name),candidate],capture_output=True,text=True)
 if result.returncode==0 and hashlib.sha256((stage/name).read_bytes()).hexdigest()==expected:break
else:raise SystemExit('Verified download failed: '+result.stderr)
assert (stage/name).stat().st_size==313352
metadata=subprocess.check_output(['dpkg-deb','--field',str(stage/name)],text=True)
(stage/'package-metadata.txt').write_text(metadata)
print(metadata,flush=True)
(stage/'manifest.json').write_text(json.dumps(dict(package='libpcre3',version='2:8.39-15',architecture='arm64',filename=name,size_bytes=313352,sha256=expected,upstream_url=url,depends='libc6 (>= 2.34)',pre_depends='',provides='',origin='Debian 12 bookworm compatibility library for existing PCRE1 binaries on Debian 13; no bookworm repository is enabled',verification_source='https://packages.debian.org/bookworm/arm64/libpcre3/download'),indent=2)+'\n')
