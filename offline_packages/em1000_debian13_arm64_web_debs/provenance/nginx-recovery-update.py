from pathlib import Path
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
p=root/'install-web-runtime.sh';s=p.read_text()
s=s.replace('    local deb_dir=$1 repo deb metadata\n','''    local deb_dir=$1 repo deb metadata package version nginx_version="" requested
    local -a nginx_packages=() targets=()
''',1)
s=s.replace('        metadata=$(dpkg-deb --field "$deb")\n','''        metadata=$(dpkg-deb --field "$deb")
        package=${deb##*/}
        package=${package%%_*}
        case "$package" in
            nginx|nginx-common|nginx-core|libnginx-mod-*)
                version=$(sed -n 's/^Version: //p' <<< "$metadata")
                [ -n "$version" ] || err "Missing version: $deb"
                if [ -n "$nginx_version" ] && [ "$version" != "$nginx_version" ]; then
                    err "Nginx/module version mismatch in offline bundle"
                fi
                nginx_version=$version
                nginx_packages+=("$package=$version") ;;
        esac
''',1)
s=s.replace('    export APT_CONFIG="$repo/apt.conf"\n','''    [ "${#nginx_packages[@]}" -gt 0 ] || err "No Nginx packages in offline bundle"
    for requested in "$@"; do
        case "$requested" in
            nginx|nginx-common|nginx-core|libnginx-mod-*) ;;
            *) targets+=("$requested") ;;
        esac
    done
    targets+=("${nginx_packages[@]}")
    export APT_CONFIG="$repo/apt.conf"
''',1)
s=s.replace('apt-get --simulate --no-remove --no-install-recommends install "$@"','apt-get --simulate --reinstall --no-remove --no-install-recommends install "${targets[@]}"',1)
s=s.replace('apt-get --yes --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "$@"','apt-get --yes --reinstall --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "${targets[@]}"',1)
s=s.replace('    nginx -t\n    curl --version\n','''    /usr/sbin/nginx -t
    /usr/bin/curl --version
    systemctl restart nginx.service
    systemctl is-active --quiet nginx.service
''',1)
p.write_text(s)
readme=root/'README.txt'
s=readme.read_text().replace('安装后验证 nginx -t 和 curl --version；HTTPS 身份由 install_keys_certs.py 单独安装。','''安装时按包内版本重新安装 Nginx 主程序、nginx-common、nginx-core 及全部配套模块，
同时重新安装请求清单中的库，修复 dpkg 记录相同版本但实际文件被旧程序覆盖的情况。
不强制重装全部 99 个依赖；其余依赖仍按设备实际状态解析。
安装后验证 /usr/sbin/nginx -t 和 /usr/bin/curl --version，并重启、检查 nginx.service。
HTTPS 身份由 install_keys_certs.py 单独安装。''')
readme.write_text(s)
