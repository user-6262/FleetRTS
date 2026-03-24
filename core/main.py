"""Entry point: launches the FleetRTS engine."""
from pathlib import Path
import sys


def main() -> None:
    core_dir = str(Path(__file__).resolve().parent)
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)
    from engine import main as run_engine

    run_engine()


if __name__ == "__main__":
    main()
