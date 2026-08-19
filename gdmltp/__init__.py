"""gdmltp - user-friendly tooling for GDMLTargetPractice.

Define a GDML target + a projectile beam, pick a generator backend (geant4 or
genie), and run it in one line; then analyze/display the shared output.root.
Pure-Python (uproot/numpy/matplotlib); no ROOT required. Provides:
  - config:    the common YAML/flag run configuration (RunConfig)
  - backends:  geant4 / genie backends behind one interface
  - io:        load output.root into Event objects
  - geometry:  parse a GDML file into placed primitives (mm)
  - scene:     build an event-display Scene (geometry + tracks + vertices)
  - render_web/png/blender: WebGL HTML, PNG stills, animated Blender scenes
  - analyze:   quick summary report + plots
  - run:       run a simulation via Docker (or a local engine)

The package was formerly named `g4tp`; that name still imports as a deprecated
alias.
"""

__version__ = "0.3.0"

from . import io, geometry, scene, particles  # noqa: F401
