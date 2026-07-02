"""g4tp - user-friendly tooling for the G4TargetPractice Geant4 simulation.

Pure-Python (uproot/numpy/matplotlib); no ROOT required. Provides:
  - io:        load output.root into Event objects
  - geometry:  parse a GDML file into placed primitives (mm)
  - scene:     build an event-display Scene (geometry + tracks + vertices)
  - render_web/png/blender: WebGL HTML, PNG stills, animated Blender scenes
  - analyze:   quick summary report + plots
  - run:       run the simulation via Docker (or a local g4sim)
"""

__version__ = "0.2.0"

from . import io, geometry, scene, particles  # noqa: F401
