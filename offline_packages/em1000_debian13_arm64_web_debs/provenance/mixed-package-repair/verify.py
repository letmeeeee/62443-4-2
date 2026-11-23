from pathlib import Path
import json,os,subprocess,shlex
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs');stage=Path('/tmp/em1000-web-mixed-fix')
records=json.loads((root/'manifest.json').read_text())
repo=Path('/tmp/em1000-web-stage/offline-repo')
env=dict(os.environ,APT_CONFIG=str(repo/'apt.conf'),LC_ALL='C')
nginx=[r['package']+'='+r['version'] for r in records if r['package'] in ('nginx','nginx-common','nginx-core') or r['package'].startswith('libnginx-mod-')]
requested=[name for name in (root/'requested-packages.txt').read_text().split() if name not in ('nginx','nginx-common','nginx-core') and not name.startswith('libnginx-mod-')]
targets=requested+nginx
s=(root/'install-web-runtime.sh').read_text()
validator=s[s.index('validate_removal_plan()'):s.index('install_offline_debs()')]
(stage/'validator.sh').write_text(validator)
def validate(plan,index=repo/'Packages'):
 script='set -Eeuo pipefail\nerr() { echo "$*"; exit 91; }\nlog() { :; }\nsource '+str(stage/'validator.sh')+'\nvalidate_removal_plan '+shlex.quote(str(plan))+' '+shlex.quote(str(index))
 return subprocess.run(['bash','-c',script],capture_output=True,text=True)
def simulate(name,status):
 args=['apt-get']
 if status is not None:args+=['-o','Dir::State::status='+str(status)]
 args+=['--simulate','--fix-broken','--no-install-recommends','install']
 result=subprocess.run(args,env=env,capture_output=True,text=True)
 log=stage/(name+'.log');log.write_text(result.stdout+result.stderr)
 return result,log
# Reproduce the user's broken state: an Ubuntu libcurl4 alongside Debian GD/Nginx packages.
missing={'libcurl4t64','libldap2','libavif16','libheif1','libimagequant0','libgeoip1t64','curl'}
status_text=''
for r in records:
 if r['package'] in missing:continue
 control=subprocess.check_output(['dpkg-deb','--field',str(root/'debs'/r['filename'])],text=True)
 status_text+=control.rstrip()+'\nStatus: install ok installed\n\n'
ssl=next(Path('/home/wx/WorkStation/G3-package/Debian/EM1000config/python/offline_pkg/debs').glob('libssl1.1_*.deb'))
status_text+=subprocess.check_output(['dpkg-deb','--field',str(ssl)],text=True).rstrip()+'\nStatus: install ok installed\n\n'
status_text+='''Package: libcurl4
Status: install ok installed
Version: 7.68.0-1ubuntu2.25
Architecture: arm64
Maintainer: test
Depends: libc6 (>= 2.17), libldap-2.4-2 (>= 2.4.7), libssl1.1 (>= 1.1.1)
Description: Reproduced old curl runtime

Package: curl
Status: install ok installed
Version: 7.68.0-1ubuntu2.25
Architecture: arm64
Maintainer: test
Depends: libcurl4 (= 7.68.0-1ubuntu2.25)
Description: Reproduced old curl command

'''
status=stage/'mixed-status';status.write_text(status_text)
result,plan=simulate('mixed-repair',status)
assert result.returncode==0,result.stdout+result.stderr
assert 'Remv libcurl4 ' in result.stdout
for name in ('libcurl4t64','libavif16','libheif1','libimagequant0','libgeoip1t64'):
 assert 'Inst '+name+' ' in result.stdout,(name,result.stdout)
assert validate(plan).returncode==0,validate(plan).stdout
projected=stage/'projected-status'
subprocess.run(['python3',str(root/'project-status.py'),str(status),str(repo/'Packages'),str(plan),str(projected)],check=True)
second=subprocess.run(['apt-get','-o','Dir::State::status='+str(projected),
 '-o','Dir::Cache::pkgcache='+str(stage/'projected-pkgcache.bin'),
 '-o','Dir::Cache::srcpkgcache='+str(stage/'projected-srcpkgcache.bin'),
 '--simulate','--reinstall','--no-remove','--no-install-recommends','install',*targets],env=env,capture_output=True,text=True)
(stage/'mixed-stage2.log').write_text(second.stdout+second.stderr)
assert second.returncode==0,second.stdout+second.stderr
assert 'Remv ' not in second.stdout
assert 'Inst nginx [' in second.stdout
print('Real APT: old Ubuntu libcurl4 replaced and five missing dependencies installed; projected Nginx reinstall PASS')
result,plan=simulate('empty-state',None)
assert result.returncode==0,result.stdout+result.stderr
assert validate(plan).returncode==0
empty=stage/'empty-status';empty.write_text('')
subprocess.run(['python3',str(root/'project-status.py'),str(empty),str(repo/'Packages'),str(plan),str(projected)],check=True)
second=subprocess.run(['apt-get','-o','Dir::State::status='+str(projected),
 '-o','Dir::Cache::pkgcache='+str(stage/'empty-pkgcache.bin'),
 '-o','Dir::Cache::srcpkgcache='+str(stage/'empty-srcpkgcache.bin'),
 '--simulate','--reinstall','--no-remove','--no-install-recommends','install',*targets],env=env,capture_output=True,text=True)
assert second.returncode==0,second.stdout+second.stderr
(stage/'empty-stage2.log').write_text(second.stdout+second.stderr)
print('Clean target full two-stage dependency resolution PASS')
# The removal gate must reject business software, missing replacement installs, and missing archives.
plan=stage/'unexpected-removal.log';plan.write_text('Remv libcurl4 [7.68]\nInst libcurl4t64 (8.14)\nRemv device-business-agent [1.0]\n')
assert validate(plan).returncode!=0
plan=stage/'missing-replacement.log';plan.write_text('Remv libcurl4 [7.68]\n')
assert validate(plan).returncode!=0
index=stage/'empty-index';index.write_text('')
plan.write_text('Remv libcurl4 [7.68]\nInst libcurl4t64 (8.14)\n')
assert validate(plan,index).returncode!=0
print('Unexpected removal / missing replacement / missing archive gates PASS')
print('No host packages or services changed')
