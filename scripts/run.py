"""Entry point: registers this project's agents with tau2, then hands over to the tau2 command line."""
import importlib
import pkgutil

import lineassist  # noqa: F401  (importing registers the agents)

for m in pkgutil.iter_modules(lineassist.__path__):
    importlib.import_module(f"lineassist.{m.name}")

from tau2.cli import main

if __name__ == "__main__":
    main()
