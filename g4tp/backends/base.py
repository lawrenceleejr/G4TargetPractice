"""Backend abstraction: one code path, (later) several generators.

A `Backend` turns a validated `RunConfig` into something a container can execute.
The host does all the rendering (into the run directory); the container just runs
the engine (and, for GENIE, a converter). Every backend must ultimately produce
`output.root` in the schema `g4tp/io.py` declares -- that shared ntuple is the
contract that lets analyze/compare/display/info work regardless of generator.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Prepared:
    """What a backend hands back to the orchestrator.

    argv    -- the in-container command (appended after the image name).
    env     -- extra environment variables (docker `-e`, or the local env).
    image   -- the container image to run (backends encode their own default).
    output  -- the file the engine writes; the orchestrator renames it to the
               user-requested run.output when they differ.
    """
    argv: list
    image: str
    env: dict = field(default_factory=dict)
    output: str = "output.root"


class Backend:
    name: str = ""

    #: base image the CLI runs when the user does not pass --image
    default_image: str = ""

    def image_for(self, cfg) -> str:
        """Image to run for this config (may vary on backend-specific options)."""
        return self.default_image

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        """Render backend inputs into `outdir` and return a Prepared plan.

        Implementations must not mutate anything outside `outdir`.
        """
        raise NotImplementedError
