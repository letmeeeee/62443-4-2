"""Linux host CPU utilization without additional dependencies."""
import time


def _read_cpu_times():
    with open('/proc/stat', encoding='ascii') as stream:
        fields = stream.readline().split()
    if not fields or fields[0] != 'cpu' or len(fields) < 5:
        raise ValueError('Invalid /proc/stat CPU counters')
    # guest and guest_nice are already included in user and nice.
    values = [int(value) for value in fields[1:9]]
    if any(value < 0 for value in values):
        raise ValueError('Negative CPU counter')
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_usage():
    """Measure aggregate CPU busy time over a short sampling interval."""
    total_before, idle_before = _read_cpu_times()
    started = time.monotonic()
    time.sleep(0.2)
    total_after, idle_after = _read_cpu_times()
    elapsed = time.monotonic() - started
    total = total_after - total_before
    idle = idle_after - idle_before
    if total <= 0 or idle < 0 or idle > total:
        raise ValueError('CPU counters did not advance consistently')
    return {
        'usedPercent': round((total - idle) / total * 100, 2),
        'sampleSeconds': round(elapsed, 3),
    }
