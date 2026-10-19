"""One-shot warehouse build: land raw -> dbt build (+ tests).

This is the whole analytical pipeline behind a single entrypoint. In Phase 2 a
Dagster job wraps exactly these two steps as assets with retries and a schedule.

Usage:
    python warehouse/build.py            # dev (DuckDB)
    python warehouse/build.py --target prod   # Databricks
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}  (cwd={cwd})")
    subprocess.run(cmd, cwd=cwd, check=True)


def main(argv: list[str]) -> int:
    target = "dev"
    if "--target" in argv:
        target = argv[argv.index("--target") + 1]

    py = sys.executable
    dbt = str(REPO / ".venv" / "bin" / "dbt")
    if not Path(dbt).exists():
        dbt = "dbt"  # fall back to PATH

    # 1. ingestion -> warehouse
    run([py, str(HERE / "load_raw.py")], cwd=REPO)
    # 2. install dbt package deps (dbt_utils). dbt_packages/ is gitignored, so a
    #    fresh checkout / container has none — deps must run before build.
    run([dbt, "deps"], cwd=HERE)
    # 3. transform + test
    run([dbt, "build", "--profiles-dir", ".", "--target", target], cwd=HERE)
    print("\nwarehouse build OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
