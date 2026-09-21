#!/usr/bin/env python3
"""Read device certificate IPv4 addresses without importing device services."""
import configparser
import ipaddress
import sys


def read_device_ips(path):
    # Existing device INI files can contain duplicate settings in unrelated sections.
    config = configparser.ConfigParser(interpolation=None, strict=False)
    with open(path, encoding="utf-8-sig") as source:
        config.read_file(source)
    value = config.get("HTTPS", "device_ips", fallback="")
    addresses = value.replace(",", " ").split()
    if not addresses:
        raise ValueError("INI 缺少 [HTTPS] device_ips，需填写设备自身的 IPv4 地址")
    result = []
    for value in addresses:
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
            raise ValueError("无效的设备访问地址: " + value)
        result.append(str(address))
    return sorted(set(result), key=ipaddress.IPv4Address)


if __name__ == "__main__":
    try:
        print(" ".join(read_device_ips(sys.argv[1])))
    except (OSError, ValueError, configparser.Error) as exc:
        print("HTTPS 配置错误: " + str(exc), file=sys.stderr)
        sys.exit(1)
