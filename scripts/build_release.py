from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pinelib.distribution import build_zip  # noqa: E402
from pinelib.version import PACKAGE_VERSION  # noqa: E402

if __name__ == "__main__":
    output = ROOT / f"pinelib-{PACKAGE_VERSION}.zip"
    print(build_zip(ROOT, output))
