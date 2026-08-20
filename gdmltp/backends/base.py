"""Backend abstraction: one code path, (later) several generators.

A `Backend` turns a validated `RunConfig` into something a container can execute.
The host does all the rendering (into the run directory); the container just runs
the engine (and, for GENIE, a converter). Every backend must ultimately produce
`output.root` in the schema `gdmltp/io.py` declares -- that shared ntuple is the
contract that lets analyze/compare/display/info work regardless of generator.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


def image_override(name: str):
    """`GDMLTP_IMAGE_<BACKEND>` -- pin the image a backend runs, for every stage.

    `run --image` only sets the FIRST stage's image, so a two-stage run (a
    generator vertex plus the Geant4 transport of `transport: true`) has no other
    way to name the Geant4 image; CI uses this to test a freshly built pair of
    images against each other instead of the published `:main` defaults.
    """
    val = os.environ.get(f"GDMLTP_IMAGE_{name.upper()}", "").strip()
    return val or None


@dataclass
class Prepared:
    """What a backend hands back to the orchestrator.

    argv    -- the in-container command (appended after the image name).
    env     -- extra environment variables (docker `-e`, or the local env).
    image   -- the container image to run (backends encode their own default).
    output  -- the file the engine writes; the orchestrator renames it to the
               user-requested run.output when they differ.
    post    -- optional callable run after a successful (non-dry) stage, for
               derived bookkeeping on the produced file (e.g. the decay
               backend's decayT/eventWeight).
    """
    argv: list
    image: str
    env: dict = field(default_factory=dict)
    output: str = "output.root"
    post: Optional[object] = None


class Backend:
    name: str = ""

    #: base image the CLI runs when the user does not pass --image
    default_image: str = ""

    #: True for backends that generate on the host in prepare() and need no
    #: container stage of their own (e.g. the decay backend)
    host: bool = False

    def image_for(self, cfg) -> str:
        """Image to run for this config (may vary on backend-specific options)."""
        return image_override(self.name) or self.default_image

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        """Render backend inputs into `outdir` and return a Prepared plan.

        Implementations must not mutate anything outside `outdir`.
        """
        raise NotImplementedError
