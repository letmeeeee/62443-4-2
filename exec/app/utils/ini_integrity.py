"""SHA-256 baseline verification for the Linux configuration."""
import hashlib
import hmac
import re
from pathlib import Path
from threading import Event, Thread

INI_FILE = Path('/home/zlg/lc_data_set.ini')
CHECKSUM_FILE = Path('/home/zlg/signature/lc_data_set.ini.sha256')


def verify_ini_checksum(ini_path=INI_FILE, checksum_path=CHECKSUM_FILE):
    try:
        expected = Path(checksum_path).read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
            return False, 'Invalid SHA-256 baseline format'
        contents = Path(ini_path).read_bytes()
        if not hmac.compare_digest(hashlib.sha256(contents).hexdigest(), expected.lower()):
            return False, 'SHA-256 mismatch: configuration differs from baseline'
        if Path(ini_path).read_bytes() != contents:
            return False, 'Configuration changed during verification'
        return True, 'Configuration SHA-256 verified'
    except (OSError, UnicodeError) as exc:
        return False, f'Integrity check unavailable: {exc}'


def monitor_ini_integrity(stop_event, log, interval=60):
    """Check immediately, then every interval; report failures without stopping service."""
    while not stop_event.is_set():
        valid, detail = verify_ini_checksum()
        log(f'[INI Integrity] {"PASS" if valid else "FAIL"}: {INI_FILE}: {detail}',
            level='INFO' if valid else 'ERROR')
        stop_event.wait(interval)


def start_ini_integrity_monitor(log, interval=60):
    if interval <= 0:
        raise ValueError('Integrity check interval must be positive')
    stop_event = Event()
    worker = Thread(target=monitor_ini_integrity, args=(stop_event, log, interval),
                    name='ini-integrity', daemon=True)
    worker.start()
    return stop_event
