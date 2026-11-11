"""Verify the frozen package contents; never accesses hardware or the network."""
import hashlib
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
failures = []
count = 0
for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
    expected, name = line.split("  ", 1)
    path = root / name
    if not path.is_file():
        failures.append(f"MISSING {name}")
        continue
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        failures.append(f"CHANGED {name}")
    count += 1
if failures:
    print("\n".join(failures))
    sys.exit(1)
print(f"Verified {count} files against SHA256SUMS.")
