"""Simple logging setup shared by all modules. Logs go to stdout, which
GitHub Actions captures automatically in the workflow run log - that's
your troubleshooting log, no extra setup needed."""

import logging
import sys


def setup_logging(level=logging.INFO):
    root = logging.getLogger("digest_bot")
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    return root
