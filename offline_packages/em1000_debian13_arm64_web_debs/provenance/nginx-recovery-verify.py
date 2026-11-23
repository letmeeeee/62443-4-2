from pathlib import Path
import json, os, subprocess, tempfile, shlex
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
stage=Path('/tmp/em1000-web-nginx-fix')
s=(root/'install-web-runtime.sh').read_text()
helper=s[s.index('install_offline_debs()'):s.index('\nmapfile -t packages')]
(stage/'helper.sh').write_text(helper)
requested=(root/'requested-packages.txt').read_text().split()
records=json.loads((root/'manifest.json').read_text())
nginx={r['package']+'='+r['version'] for r in records if r['package'] in ('nginx','nginx-common','nginx-core') or r['package'].startswith('libnginx-mod-')}
selected=None
for mode in ('check','install'):
 harness='''set -Eeuo pipefail
err() { echo "ERROR $*"; exit 99; }
apt-get() { printf 'APT'; printf ' %q' "$@"; printf '\\n'; }
source /tmp/em1000-web-nginx-fix/helper.sh
MODE='''+mode+'\ninstall_offline_debs '+shlex.quote(str(root/'debs'))+' '+' '.join(map(shlex.quote,requested))+'\n'
 result=subprocess.run(['bash','-c',harness],capture_output=True,text=True,check=True)
 commands=[shlex.split(line)[1:] for line in result.stdout.splitlines() if line.startswith('APT ')]
 args=commands[-1]
 assert '--reinstall' in args and '--no-remove' in args,args
 assert ('--simulate' in args)==(mode=='check')
 targets=args[args.index('install')+1:]
 assert nginx.issubset(set(targets)),targets
 assert len(targets)==len(set(targets))
 assert not any(t in targets for t in ('nginx','nginx-core','nginx-common'))
 selected=targets
 print(mode,'all 9 Nginx packages pinned, reinstall enabled, no duplicates PASS')
# All installed status: prove same-version packages will really be reinstalled.
repo=Path('/tmp/em1000-web-stage/offline-repo')
status=stage/'installed-status'
status.write_text(''.join(subprocess.check_output(['dpkg-deb','--field',str(root/'debs'/r['filename'])],text=True).rstrip()+'\nStatus: install ok installed\n\n' for r in records))
base=['apt-get','-o','Dir::State::status='+str(status),'--simulate','--reinstall','--no-remove','--no-install-recommends','install',*selected]
env=dict(os.environ,APT_CONFIG=str(repo/'apt.conf'),LC_ALL='C')
result=subprocess.run(base,env=env,capture_output=True,text=True)
assert result.returncode==0,result.stdout+result.stderr
(stage/'same-version-reinstall.log').write_text(result.stdout+result.stderr)
assert '18 reinstalled' in result.stdout,result.stdout
assert 'Inst nginx [' in result.stdout,result.stdout
print('Actual APT same-version state: 18 reinstalled, including main binary and every Nginx module PASS')
# Also prove the revised selection resolves from an empty installed state.
result=subprocess.run(['apt-get','--simulate','--reinstall','--no-remove','--no-install-recommends','install',*selected],env=env,capture_output=True,text=True)
assert result.returncode==0,result.stdout+result.stderr
(stage/'empty-state-resolution.log').write_text(result.stdout+result.stderr)
print('Actual APT empty-state dependency resolution PASS')
