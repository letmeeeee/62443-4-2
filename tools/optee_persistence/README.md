# 厂家原 TA 的跨重启持久化验证

只新增普通世界客户端，不修改或重编 `origin/optee_ta_examples` 内的 TA。
共享头直接使用厂家原版 `crypto_ta.h`，只调用命令 1、6、3、5。

- `init`：命令 1 确保 RSA 密钥存在，然后导出公钥、签名、验签。
- `check`：只调用 6、3、5；缺少密钥时直接失败，不调用生成命令。
- stdout 只输出固定格式的 RSA 公钥 n/e，可用 `cmp` 比较。
- stderr 输出失败阶段、命令号、result、origin；成功退出 0。
- PSS 签名每次可能不同，不作为身份比较依据。

该测试使用厂家原 TA 的通用 RSA 对象，不使用 Modbus 角色对象。
它验证同一身份跨重启保留及私钥可用性，不能单凭结果区分 REE/RPMB 后端。

## 编译客户端

在仓库根目录执行（需要 ARM64 交叉编译器）：

```bash
make -C tools/optee_persistence
```

也可在安装了 libteec 开发头的设备上编译：

```bash
make -C tools/optee_persistence CROSS_COMPILE= \
  OPTEE_CLIENT_INC=/usr/include LIBTEEC_LIB=/usr/lib/aarch64-linux-gnu
```

## 部署原 TA

原 TA 与当前 Modbus TA 的 UUID 相同，无法并存于同一个加载路径。原 TA 不支持
Modbus 命令 8～11，因此测试期间使用该 TA 的 Modbus TLS 功能不可用。
在维护窗口进行；停止实际调用 TA 的应用，备份现有 TA 后再替换。

把以下两个文件传到设备 `/home/zlg/vendor-ta-test/`（传输本身不覆盖已安装 TA）：

1. `tools/optee_persistence/crypto_persistence`
2. `origin/optee_ta_examples/ta/crypto_ta/5319e0a0-0001-4e2a-9c01-0c34da100001.ta`

仓库原 TA 的 SHA256：
`7486a890b9c90ffd9402043684011ab4a7c74ab59efb7081ef273f08b9af7296`。

板端操作示例（若备份已存在，先核实，不要覆盖）：

```bash
cd /home/zlg/vendor-ta-test
ta_file=5319e0a0-0001-4e2a-9c01-0c34da100001.ta
test ! -e installed-ta.before-test && \
  cp -p /lib/optee_armtz/"$ta_file" installed-ta.before-test
# 确认上一步备份成功后，执行以下命令。
sha256sum installed-ta.before-test "$ta_file"
install -m 0644 "$ta_file" /lib/optee_armtz/"$ta_file"
chmod +x crypto_persistence
sync
reboot
```

替换后整机重启以避免继续使用已加载的旧 TA，不使用单独重启 tee-supplicant 的方式。

## 重启前建立基线

基线放在持久目录，不能用 `/tmp`。首次测试执行：

```bash
cd /home/zlg/vendor-ta-test
./crypto_persistence init > before.pub
echo "init_exit=$?"
# 仅在 init_exit=0 时继续。
./crypto_persistence check > same-boot.pub
echo "check_exit=$?"
# 仅在 check_exit=0 时比较，应该输出 SAME。
cmp before.pub same-boot.pub && echo SAME
sha256sum /lib/optee_armtz/5319e0a0-0001-4e2a-9c01-0c34da100001.ta \
  ./crypto_persistence before.pub > baseline.sha256
sync
reboot
```

## 重启后只读验证

先不运行原 `crypto_test_ta`、`init`、`renew` 或其他密钥生成操作：

```bash
cd /home/zlg/vendor-ta-test
sha256sum -c baseline.sha256
./crypto_persistence check > after.pub
echo "check_exit=$?"
# 仅在 check_exit=0 时比较。
cmp before.pub after.pub && echo PERSISTENCE_PASS
```

- check 成功且公钥相同：原 TA 的 RSA 身份跨重启可用。
- OpenSession 成功、命令 6 返回 `0xffff0008`：原 TA 也未能恢复持久对象。
- OpenSession 返回 `0xffff000f`：先定位加载/会话失败，尚未测试到密钥读取。
- check 成功但公钥不同：身份发生改变，需要查其他程序是否生成密钥及启动环境。

## 恢复之前的 TA

停止测试及相关调用者，确认备份对应原来的已部署 TA，然后执行：

```bash
cd /home/zlg/vendor-ta-test
install -m 0644 installed-ta.before-test \
  /lib/optee_armtz/5319e0a0-0001-4e2a-9c01-0c34da100001.ta
sync
reboot
```

恢复 TA 文件不会恢复此前已丢失的私钥。
