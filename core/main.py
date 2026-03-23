"""Entry point: launches the playable prototype."""
from pathlib import Path
import sys


def main() -> None:
    # demo_game uses sibling imports (game_audio, …); keep cwd-independent entry.
    core_dir = str(Path(__file__).resolve().parent)
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)
    from demo_game import main as run_demo

    run_demo()


if __name__ == "__main__":
    main()
