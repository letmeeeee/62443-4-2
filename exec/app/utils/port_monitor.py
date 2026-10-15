"""Linux Ethernet carrier polling and kernel USB hotplug event logging."""
import os
import select
import socket
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

LOG_PATH = Path('/mnt/nvme/zlog/USB.log')
NETWORK_PORTS = ('net1', 'net2', 'net3', 'net4')
DEFAULT_USB_PATHS = {'USB1': '3-1.3', 'USB2': '3-1.4'}


def append_event(message, path=LOG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec='milliseconds')
    with path.open('a', encoding='utf-8') as stream:
        stream.write(f'[{timestamp}] {message}\n')


def read_carrier(name, root=Path('/sys/class/net')):
    try:
        value = (root / name / 'carrier').read_text(encoding='ascii').strip()
        return {'1': True, '0': False}.get(value)
    except OSError:
        # Interface down/missing is not evidence of a cable removal.
        return None


def network_events(previous, current):
    messages = []
    for name, state in current.items():
        if name not in previous:
            label = 'CONNECTED' if state is True else 'DISCONNECTED' if state is False else 'UNKNOWN'
            messages.append(f'[NET] {name} INITIAL {label}')
        elif state is None and previous[name] is not None:
            messages.append(f'[NET] {name} STATE_UNAVAILABLE')
        elif state is not None and state != previous[name]:
            action = 'LINK_UP' if state else 'LINK_DOWN'
            messages.append(f'[NET] {name} {action}')
    return messages


def usb_event(payload, mapping=None):
    fields = {}
    for part in payload.decode('utf-8', errors='replace').split('\0'):
        key, separator, value = part.partition('=')
        if separator:
            fields[key] = value
    if fields.get('SUBSYSTEM') != 'usb' or fields.get('DEVTYPE') != 'usb_device':
        return None
    action = {'add': 'INSERTED', 'remove': 'REMOVED'}.get(fields.get('ACTION'))
    if not action:
        return None
    port = fields.get('DEVPATH', '').rsplit('/', 1)[-1]
    if not port or port.startswith('usb'):
        return None  # Exclude root hubs and USB interface-level duplicates.
    label = (mapping or {}).get(port, port)
    return f'[USB] {label} {action} sysfs={port}'


def monitor_ports(stop, report_error, interval=0.5):
    previous = {}
    receiver = None
    mapping = {value.strip(): label for label, default in DEFAULT_USB_PATHS.items()
               for value in os.environ.get(label + '_SYSFS_PATH', default).split(',')
               if value.strip()}
    try:
        append_event('[MONITOR] START')
        # Kernel uevents capture USB insert/remove even between network polls.
        receiver = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        receiver.bind((0, 1))
        receiver.setblocking(False)
        while not stop.is_set():
            current = {name: read_carrier(name) for name in NETWORK_PORTS}
            for message in network_events(previous, current):
                append_event(message)
            previous = current
            ready, _, _ = select.select([receiver], [], [], interval)
            if ready:
                payload, sender = receiver.recvfrom(65536)
                if sender[0] == 0:  # Only accept kernel-originated events.
                    message = usb_event(payload, mapping)
                    if message:
                        append_event(message)
    except (OSError, AttributeError) as exc:
        report_error(f'[Port Monitor] Monitoring interrupted: {exc}', level='ERROR')
    finally:
        if receiver is not None:
            receiver.close()


def start_port_monitor(report_error):
    stop = Event()

    def run():
        while not stop.is_set():
            monitor_ports(stop, report_error)
            stop.wait(5)  # Retry permission, disk and socket failures.

    Thread(target=run, name='port-monitor', daemon=True).start()
    return stop
