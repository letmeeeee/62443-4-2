from pathlib import Path
import hashlib,os,pwd,shlex,subprocess
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs');stage=Path('/tmp/em1000-web-mixed-fix')
s=(root/'install-web-runtime.sh').read_text()
functions=s[s.index('validate_removal_plan()'):s.index('\nmapfile -t packages')]
status=stage/'mixed-status'
functions=functions.replace('/var/lib/dpkg/status',str(status))
head='''set -Eeuo pipefail
log() { echo "INFO $*"; }
err() { echo "ERROR $*"; exit 91; }
apt-get() {
    for arg in "$@"; do [ "$arg" != --yes ] || { echo 'Unexpected actual install'; exit 92; }; done
    /usr/bin/apt-get -o APT::Architecture=arm64 -o APT::Architectures::=arm64 -o APT::Sandbox::User='''+pwd.getpwuid(os.getuid()).pw_name+''' "$@"
}
'''
script=head+functions+'\nBUNDLE_DIR='+shlex.quote(str(root))+'\nMODE=check\nmapfile -t packages < "$BUNDLE_DIR/requested-packages.txt"\ninstall_offline_debs "$BUNDLE_DIR/debs" "${packages[@]}"\n'
before=hashlib.sha256(status.read_bytes()).hexdigest()
result=subprocess.run(['bash','-c',script],capture_output=True,text=True)
(stage/'integration-check-only.log').write_text(result.stdout+result.stderr)
assert result.returncode==0,result.stdout+result.stderr
assert 'Offline repair and installation plans validated; no packages changed' in result.stdout
assert 'Allowed package transition: libcurl4 -> libcurl4t64' in result.stdout
assert before==hashlib.sha256(status.read_bytes()).hexdigest()
print('Whole installer function: actual file-repo update, real APT repair/projection/install simulations PASS')
print('Check-only never invoked installation and preserved original status bytes PASS')
