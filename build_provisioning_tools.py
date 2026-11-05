#!/usr/bin/env python3
"""Build portable Python zipapps containing code only, never keys or device data."""
import argparse
from pathlib import Path
import shutil
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parent


def build(output):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    for entry, source, modules in (
        ('ca_manager', 'ca_manager', ('__init__','common','ca','passwords','password_ui','ui')),
        ('device_deploy', 'device_deploy', ('__init__','common','device','ssh_agent','ssh_device','deployment_record','ui')),
        ('device_agent', 'device_local', ('__init__','common','device','ui')),
    ):
        with tempfile.TemporaryDirectory(prefix='lc400-build-') as temporary:
            stage = Path(temporary); package = stage/'provisioning'; package.mkdir()
            for name in modules:
                shutil.copyfile(ROOT/'provisioning'/(name+'.py'), package/(name+'.py'))
            shutil.copyfile(ROOT/(source+'.py'), stage/'__main__.py')
            zipapp.create_archive(stage, output/(entry+'.pyz'), interpreter='/usr/bin/env python3')
    print('Code-only tools: ' + str(output))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(ROOT/'provisioning/build-output'))
    build(parser.parse_args().out)
