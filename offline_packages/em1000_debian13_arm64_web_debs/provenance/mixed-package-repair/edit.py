from pathlib import Path
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
p=root/'install-web-runtime.sh';s=p.read_text()
old='''    if [ "$MODE" = check ]; then
        apt-get --simulate --reinstall --no-remove --no-install-recommends install "${targets[@]}"
    else
        apt-get --yes --reinstall --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "${targets[@]}"
    fi
'''
new='''    # Repair interrupted/mixed-distribution installs in this isolated offline repository.
    # Validate the proposed removals before allowing normal t64 package transitions.
    local plan action name rest replacement
    export LC_ALL=C
    plan="$repo/install-plan.log"
    if ! apt-get --simulate --fix-broken --reinstall --no-install-recommends \\
        install "${targets[@]}" > "$plan" 2>&1; then
        cat "$plan"
        err "Offline dependency repair cannot be resolved; no packages changed"
    fi
    cat "$plan"
    validate_removal_plan "$plan" "$repo/Packages"
    if [ "$MODE" = check ]; then
        log "Offline repair plan validated; no packages changed"
    else
        apt-get --yes --fix-broken --reinstall --no-install-recommends \\
            -o Dpkg::Options::=--force-confold install "${targets[@]}"
    fi
'''
assert old in s
s=s.replace(old,new,1)
helper='''validate_removal_plan()
{
    local plan=$1 index=$2 action name rest replacement
    while read -r action name rest; do
        [ "$action" = Remv ] || continue
        name=${name%%:*}
        case "$name" in
            libcurl4) replacement=libcurl4t64 ;;
            libgeoip1) replacement=libgeoip1t64 ;;
            libgnutls30) replacement=libgnutls30t64 ;;
            libnettle8) replacement=libnettle8t64 ;;
            libhogweed6) replacement=libhogweed6t64 ;;
            libpsl5) replacement=libpsl5t64 ;;
            libssh2-1) replacement=libssh2-1t64 ;;
            libssl3) replacement=libssl3t64 ;;
            libpng16-16) replacement=libpng16-16t64 ;;
            libelf1) replacement=libelf1t64 ;;
            libtirpc3) replacement=libtirpc3t64 ;;
            libdb5.3) replacement=libdb5.3t64 ;;
            *) err "Unexpected removal in offline repair plan: $name; no packages changed" ;;
        esac
        grep -Fx "Package: $replacement" "$index" >/dev/null ||
            err "Replacement package is missing from offline bundle: $replacement"
        # The proposed solution must actually install/reinstall the replacement.
        awk -v wanted="$replacement" '$1 == "Inst" {split($2, n, ":"); if (n[1] == wanted) found=1} END {exit !found}' "$plan" ||
            err "Removal of $name has no replacement installation in the plan"
        log "Allowed package transition: $name -> $replacement"
    done < "$plan"
}

'''
s=s.replace('install_offline_debs()\n',helper+'install_offline_debs()\n',1)
p.write_text(s)
r=root/'README.txt';text=r.read_text()
text+='''
混装/中断安装恢复：
install-web-runtime.sh 在同一个离线仓库中使用 --fix-broken 解析并先模拟验证。
允许将 libcurl4 等已列明的旧包替换为包内对应 t64 库，并要求计划确实安装替代包。
若 APT 计划移除业务程序或任何白名单以外的软件包，脚本在实际安装前退出并打印计划。
无需执行使用联网源的 apt --fix-broken install，也不使用 dpkg --force-depends。
--check-only 会展示相同的修复计划，但不执行安装或移除。
''';r.write_text(text)
print('Prepared offline mixed-package repair with bounded replacement plan')
