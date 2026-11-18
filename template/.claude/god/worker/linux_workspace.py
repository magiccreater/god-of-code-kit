"""Check the backing filesystem, including Windows drives mounted at custom paths."""
from pathlib import Path
import subprocess
import sys


def require_linux_workspace(path):
    if "microsoft" not in Path("/proc/sys/kernel/osrelease").read_text().lower():
        raise ValueError("Run this command inside WSL.")
    location = Path(path).resolve(strict=True)
    fs = subprocess.check_output(["findmnt", "-n", "-o", "FSTYPE", "-T", str(location)], text=True).strip()
    if fs in {"9p", "drvfs", "ntfs", "ntfs3", "cifs", "fuseblk"}:
        raise ValueError("Use a repository on the WSL Linux filesystem, for example ~/code/project.")


if __name__ == "__main__":
    try:
        require_linux_workspace(sys.argv[1])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
