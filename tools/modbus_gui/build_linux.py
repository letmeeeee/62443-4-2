"""Build a Linux x86_64 desktop directory with Python/Tk/crypto; code only."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from provisioning.portable_build import build_portable_ca
from build_provisioning_executables import archive, write_hashes


def main():
    root=Path(__file__).resolve().parents[2]
    output=root/'tools/modbus_gui/dist';output.mkdir(exist_ok=True)
    name='ModbusTLS_linux-'+platform.machine().lower()
    with tempfile.TemporaryDirectory(dir=output,prefix='.build-') as temp:
        stage=Path(temp)/name;stage.mkdir()
        build_portable_ca(root,stage,desktop='modbus')
        shutil.copy2(root/'tools/modbus_gui/README.md',stage/'README.md')
        subprocess.run([str(stage/'ModbusTLS'),'--help'],check=True)
        write_hashes(stage)
        destination=output/name
        if destination.exists():shutil.rmtree(destination)
        shutil.move(str(stage),destination)
    print(archive(destination))


if __name__=='__main__':main()
