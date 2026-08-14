#!/usr/bin/env python3
"""Fail if a built distribution carries anything it should not.

Run it before publishing, and in CI on every push:

    python scripts/check_package.py

Why this exists: 0.4.0 was built carrying local tooling state with
machine paths in it, and nothing noticed. The cause was an exclude list,
which ships whatever nobody thought to name, combined with hatchling
reading only this repo's .gitignore and knowing nothing about a
machine-level ignore file. pyproject now uses an allowlist, but an
allowlist is still a claim about the build, and this script is what
checks the claim actually held.

It reads the built artifacts rather than the config, so it catches the
case the config was meant to prevent even if the config itself is wrong.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

#: Everything under the package itself is fine — a new module or
#: subpackage must not need this file edited.
ALLOWED_PREFIXES = ("productspy/",)

#: Exact top-level members a distribution may carry besides the package.
ALLOWED_FILES = {
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "PKG-INFO",          # generated into the sdist by the backend
    # hatchling puts this in the sdist itself regardless of `include`.
    # Allowed rather than fought: it is already public in the repo, so it
    # leaks nothing, and this guard exists to stop private files escaping,
    # not to enforce a minimal tarball.
    ".gitignore",
}

#: Nothing else is listed. An allowlist needs no matching denylist: any
#: dotfile, editor directory or local settings blob that appears is
#: already unexpected, and naming candidates would only invite the
#: assumption that unnamed ones are fine.


def members(path: Path) -> list[str]:
    """Archive members with the version prefix stripped."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        # productspy-0.5.0.dist-info/ is the backend's own metadata.
        return [n for n in names if ".dist-info/" not in n]
    with tarfile.open(path) as tf:
        names = [m.name for m in tf.getmembers() if m.isfile()]
    # sdist wraps everything in productspy-<version>/
    return ["/".join(n.split("/")[1:]) for n in names]


def check(path: Path) -> list[str]:
    problems = []
    for name in members(path):
        if not name:
            continue
        if name.startswith(ALLOWED_PREFIXES) or name in ALLOWED_FILES:
            continue
        problems.append(f"{path.name}: unexpected member {name}")
    return problems


def main() -> int:
    if "--no-build" not in sys.argv:
        for stale in list(DIST.glob("*.tar.gz")) + list(DIST.glob("*.whl")):
            stale.unlink()
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(DIST), str(ROOT)],
            check=True,
        )

    artifacts = sorted(DIST.glob("*.tar.gz")) + sorted(DIST.glob("*.whl"))
    if not artifacts:
        print("no artifacts in dist/ — nothing to check", file=sys.stderr)
        return 1

    problems: list[str] = []
    for art in artifacts:
        found = check(art)
        problems += found
        print(f"{'FAIL' if found else 'ok  '}  {art.name}"
              f"  ({len(members(art))} members)")

    if problems:
        print("\nProblems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nContents:", file=sys.stderr)
        for art in artifacts:
            for name in sorted(members(art)):
                print(f"  {art.name}: {name}", file=sys.stderr)
        return 1

    print("\nAll distributions carry only the package and its metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
