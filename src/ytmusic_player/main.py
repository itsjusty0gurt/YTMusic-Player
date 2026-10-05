from __future__ import annotations

import sys

from .application import run


def main() -> int:
    try:
        return run()
    except Exception:
        # Logging may not yet be configured if Qt initialization itself failed.
        import logging

        logging.exception("Fatal application error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
