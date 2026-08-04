"""Marker so the editable YAML library ships inside the wheel as ``algametrix.data``.

The files next to this one — ``organisms.yaml``, ``systems.yaml``, ``parameters.yaml``
and the benchmark/reference sets — are the data the engine loads by default. They stay
at the repository root so they remain easy to find and edit; ``pyproject.toml`` maps
this directory onto ``algametrix/data`` in an installed distribution, and
:data:`algametrix.library.DEFAULT_DATA_DIR` resolves to whichever copy exists.

Nothing imports this module; it exists only so setuptools recognises the directory.
"""
