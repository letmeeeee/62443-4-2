from pathlib import Path
import subprocess, tempfile, shlex
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
s=(root/'install-pcre3-compat.sh').read_text()
start=s.index('BUNDLE_DIR=');end=s.index('\n',start)
s=s[:start]+'BUNDLE_DIR='+shlex.quote(str(root))+s[end:]
s=s.replace('. /etc/os-release','ID=debian; VERSION_ID=13').replace('/usr/sbin/nginx -t','nginx_test')
for mode in ('install','check','oldlibc','restartfail'):
 with tempfile.TemporaryDirectory() as d:
  log=Path(d)/'calls'
  head='''
id() { echo 0; }
dpkg() {
    if [ "$1" = --print-architecture ]; then echo arm64
    elif [ "$1" = --compare-versions ]; then /usr/bin/dpkg "$@"
    elif [ "$1" = -i ]; then echo "install $2" >> "$CALLS"
    else return 88; fi
}
dpkg-query() { if [ "${@: -1}" = libc6:arm64 ]; then echo "$LIBC_VERSION"; else return 1; fi; }
ldconfig() { echo ldconfig >> "$CALLS"; }
nginx_test() { echo nginx-test >> "$CALLS"; }
systemctl() { echo "systemctl $*" >> "$CALLS"; if [ "$MODE" = restartfail ]; then return 1; fi; }
'''
  args=' --check-only' if mode=='check' else ''
  script=head+'\nCALLS='+shlex.quote(str(log))+'\nMODE='+mode+'\nLIBC_VERSION='+('2.33' if mode=='oldlibc' else '2.41-12+deb13u4')+'\nset --'+args+'\n'+s
  result=subprocess.run(['bash','-c',script],text=True,capture_output=True)
  calls=log.read_text() if log.exists() else ''
  assert (result.returncode==0)==(mode in ('install','check')),(mode,result.stdout,result.stderr)
  if mode in ('check','oldlibc'):assert not calls,(mode,calls)
  if mode=='install':
   assert calls.count('install ')==1 and '/debs/libpcre3_8.39-15_arm64.deb' in calls
   assert 'systemctl restart nginx.service' in calls
   assert 'dpkg' not in calls and 'nginx_' not in calls
  if mode=='restartfail':assert 'existing Nginx is active' not in result.stdout
  print(mode,'PASS')
print('No host package, service or disk changes performed')
