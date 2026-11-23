#!/usr/bin/env python3
"""Project an APT simulation into a temporary status file; never write live status."""
import re
import sys
from pathlib import Path


def blocks(path):
    for raw in Path(path).read_text().split('\n\n'):
        if not raw.strip():
            continue
        fields = dict(line.split(': ', 1) for line in raw.splitlines()
                      if ': ' in line and not line[0].isspace())
        if 'Package' in fields:
            yield fields, raw


def installed(raw):
    lines = raw.splitlines()
    lines = [line for line in lines if not line.startswith('Status: ')]
    return '\n'.join(lines) + '\nStatus: install ok installed'


def main():
    live, index, plan, output = map(Path, sys.argv[1:])
    if output.resolve() == live.resolve() or output.resolve() == Path('/var/lib/dpkg/status'):
        raise ValueError('Refusing to overwrite live package status')
    state = {(f['Package'], f['Architecture']): raw for f, raw in blocks(live)}
    available = {f['Package']: (f, raw) for f, raw in blocks(index)}
    for line in plan.read_text().splitlines():
        words = line.split()
        if len(words) < 2 or words[0] not in ('Inst', 'Remv', 'Conf'):
            continue
        action, token = words[:2]
        name, _, arch = token.partition(':')
        if action == 'Remv':
            for key in list(state):
                if key[0] == name and (not arch or key[1] == arch):
                    del state[key]
        elif action == 'Inst':
            fields, raw = available[name]
            version = re.search(r'\((\S+)', line)
            if not version or version[1] != fields['Version']:
                raise ValueError('Plan/index candidate mismatch: ' + token)
            key = name, fields['Architecture']
            state[key] = installed(raw)
        else:
            for key in list(state):
                if key[0] == name and (not arch or key[1] == arch):
                    state[key] = installed(state[key])
    output.write_text(''.join(raw.rstrip() + '\n\n' for raw in state.values()))


if __name__ == '__main__':
    main()
