"""Loud, actionable warnings for run configurations that are physically weak.

These are banners, not log lines: the cases here (a neutrino beam fired into
Geant4's own thin neutrino physics; a generator run that stops before Geant4)
produce a file that LOOKS fine and quietly is not what the user wanted, so the
message has to be impossible to scroll past. Set GDMLTP_NO_WARNINGS=1 to mute
them -- they are advice, never errors, and the run continues either way.
"""
import os
import sys
import textwrap

WIDTH = 78                     # frame width; body text wraps to WIDTH - 6
_INNER = WIDTH - 6
NEUTRINO_PDGS = {12, -12, 14, -14, 16, -16}


def muted():
    return os.environ.get("GDMLTP_NO_WARNINGS", "").strip() not in ("", "0", "false")


def _bold(text, stream):
    """ANSI bold-yellow on a terminal; plain text in a log or a pipe."""
    try:
        tty = stream.isatty()
    except Exception:                                  # pragma: no cover
        tty = False
    return f"\033[1;33m{text}\033[0m" if tty else text


def _row(content=""):
    if len(content) > _INNER:                          # verbatim line too long:
        return "!! " + content                         # keep it, drop the border
    return "!! " + content.ljust(_INNER) + " !!"


def _blocks(body):
    """Split the body into blank-line-separated blocks, keeping indented ones
    (commands, YAML) verbatim and re-flowing prose so it fills the frame."""
    for chunk in body.strip("\n").split("\n\n"):
        lines = chunk.split("\n")
        if all(l.startswith("  ") or not l.strip() for l in lines):
            yield [l.rstrip() for l in lines]
        else:
            yield textwrap.wrap(" ".join(l.strip() for l in lines), _INNER)


def banner(title, body, stream=None):
    """Print a boxed, unmissable warning to stderr (advice, not an error)."""
    if muted():
        return
    stream = stream or sys.stderr
    bar = "!" * WIDTH
    out = [bar, _row(title.upper()), bar]
    for i, block in enumerate(_blocks(body)):
        if i:
            out.append(_row())
        out += [_row(line) for line in block]
    out.append(bar)
    print(_bold("\n".join(out), stream), file=stream, flush=True)


def neutrino_on_geant4(particle, generator="geant4"):
    """A neutrino beam on the geant4 backend: Geant4 transports superbly, but
    its neutrino INTERACTION physics is thin -- send the user to a generator."""
    banner(
        f"NEUTRINO BEAM ({particle}) ON THE BARE GEANT4 BACKEND",
        f"""
You are firing {particle} into the geometry with GEANT4'S OWN neutrino
interactions. Geant4 is a transport engine: its neutrino cross sections are so
small that gdmltp has to bias them by ~1e12 for anything to interact at all,
and what comes out is not event-generator quality -- no nuclear initial state,
no tuned resonance/DIS model set, no intranuclear cascade. Treat any
interaction physics from this run as a transport artefact, not as neutrino
physics.

USE A NEUTRINO EVENT GENERATOR INSTEAD. You lose nothing by doing so: the
generator makes the interaction, Geant4 still propagates every final-state
particle through the same geometry, and one output.root carries both records.

  generator: genie       # reference generator; examples/nu_argon.yaml
  generator: achilles    # theory-driven lepton-nucleus, FSI cascade
  generator: pythia      # TeV DIS off a free nucleon, no splines

  gdmltp run --config examples/nu_argon.yaml -o out

The Geant4 backend is still the right tool for what it is good at: propagating
neutrinos to a detector, flux and geometry studies, and the deliberate
contrast against a generator described in docs/neutrino.md.

Continuing with Geant4 anyway. Mute with GDMLTP_NO_WARNINGS=1.
""")


def generator_without_transport(generator):
    """`transport: false` is legal and sometimes wanted, but it is the one way
    to end up with a generator run that never reaches Geant4."""
    banner(
        f"{generator.upper()} RUN WITH TRANSPORT DISABLED -- NO GEANT4 IN THIS RUN",
        f"""
{generator}: {{transport: false}} is set, so this run stops at the interaction
vertex: nothing is propagated through the geometry. The output carries the
nu_* interaction record and the final-state momenta, but no step_*, no
totalEdep, and no detector response at all.

That is a fine thing to want (cross sections, kinematics, generator
comparisons). If it is not what you meant, delete the transport key -- Geant4
transport is the default for every generator:

  {generator}:               # no transport key = generator + Geant4 transport
    tune: ...

Continuing vertex-level. Mute with GDMLTP_NO_WARNINGS=1.
""")
