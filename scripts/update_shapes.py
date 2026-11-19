"""Add the answers in diagnostics files to the known shapes: python scripts/update_shapes.py FILE..."""

import sys
from pathlib import Path

from aula_connect.shapes import main

main(sys.argv[1:], str(Path(__file__).parent.parent / "src" / "aula_connect" / "shapes.json"))
