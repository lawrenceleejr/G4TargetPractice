"""Orchestration for the `decay` backend: long-lived BSM projectiles decayed
by GEANT4, not by this framework.

This module contains NO event generation. It renders `/bsm/define` +
`/bsm/channel` macro commands (see g4sim/BSMPhysics.cc) that hand the particle
definition -- mass, charge, proper decay length, decay channels -- to Geant4,
whose own G4Decay process decays it in flight (exponential decay with time
dilation) with daughters from Geant4's G4PhaseSpaceDecayChannel, transported
through the GDML detector in the same run. What remains here is bookkeeping:

  * config resolution (parent mass/ctau, channel PDG ids, early error checks);
  * lifetime importance sampling: Geant4 generates with `decay.ctau_sample`
    (pick it ~ the detector scale so decays actually land inside), and
    `postprocess` reweights each event to the TRUE `decay.ctau` analytically
    from the recorded flight length -- the standard LLP trick, done as
    arithmetic on Geant4's output, not as generation;
  * derived per-event scalars: `decayT` (flight time) and `eventWeight`.

For decay distributions beyond phase space (V-A three-body, form factors,
polarization), generate the events with a real generator (Pythia8, MadGraph)
and feed them in through the `external` backend instead.
"""
import numpy as np

from . import io, masses
from .beam import _len_mm
from .config import ConfigError

C_MM_PER_NS = 299.792458

# Optional event scalars this backend adds on top of the common schema.
OPTIONAL_SCALAR_BRANCHES = ["eventWeight", "decayT"]


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #
def parent_mass_mev(cfg):
    beam = cfg.beam
    if beam.mass is not None:
        from .beam import _ene_mev
        return _ene_mev(beam.mass)
    pdg = beam.pdg_code()
    m = masses.mass_mev(pdg) if pdg is not None else 0.0
    if m <= 0:
        raise ConfigError(
            f"no rest mass for {beam.identifier()!r}: set beam.mass "
            f"(e.g. \"1.0 GeV\") for BSM projectiles")
    return m


def ctau_mm(decay_cfg, key="ctau"):
    """Proper decay length in mm from decay.<key> or (key='ctau' only) the
    decay.lifetime alternative."""
    if decay_cfg.get(key):
        return _len_mm(str(decay_cfg[key]))
    if key == "ctau" and decay_cfg.get("lifetime"):
        parts = str(decay_cfg["lifetime"]).split()
        val = float(parts[0])
        unit = (parts[1] if len(parts) > 1 else "ns").lower()
        to_ns = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}
        if unit not in to_ns:
            raise ConfigError(f"unknown lifetime unit {unit!r}")
        return val * to_ns[unit] * C_MM_PER_NS
    raise ConfigError(f"decay.{key} is not set")


def resolve_channels(decay_cfg, parent_mass):
    """[(pdgs, br)] with normalized branching ratios; early energy-conservation
    check where the daughter masses are known (Geant4 re-checks at decay)."""
    out = []
    for i, ch in enumerate(decay_cfg["channels"]):
        pdgs = [int(p) for p in ch["to"]]
        msum = sum(masses.mass_mev(p) for p in pdgs)
        if msum >= parent_mass:
            raise ConfigError(
                f"decay.channels[{i}] ({pdgs}): daughter masses sum to "
                f"{msum:.1f} MeV >= parent mass {parent_mass:.1f} MeV")
        out.append((pdgs, float(ch.get("br", 1.0))))
    total = sum(br for _, br in out)
    return [(pdgs, br / total) for pdgs, br in out]


# --------------------------------------------------------------------------- #
# Macro rendering (the hand-off to Geant4)
# --------------------------------------------------------------------------- #
def bsm_macro_lines(cfg):
    """The /bsm/* PreInit commands defining the particle to Geant4."""
    pdg = cfg.beam.pdg_code()
    if pdg is None:
        raise ConfigError("the decay backend needs the projectile as a PDG id "
                          "(beam.pdg or a numeric beam.particle)")
    mass = parent_mass_mev(cfg)
    charge = float(cfg.decay.get("charge", 0.0))
    ctau_gen = sampling_ctau_mm(cfg)
    name = str(cfg.decay.get("name", f"bsm{pdg}"))
    lines = [f"/bsm/define {name} {pdg} {mass:g} {charge:g} {ctau_gen:g}"]
    for pdgs, br in resolve_channels(cfg.decay, mass):
        lines.append(f"/bsm/channel {br:g} " + " ".join(str(p) for p in pdgs))
    return lines


def sampling_ctau_mm(cfg):
    """The ctau Geant4 generates with: decay.ctau_sample if given (lifetime
    importance sampling), else the true decay.ctau."""
    if cfg.decay.get("ctau_sample"):
        return ctau_mm(cfg.decay, "ctau_sample")
    return ctau_mm(cfg.decay)


# --------------------------------------------------------------------------- #
# Post-run bookkeeping on Geant4's output
# --------------------------------------------------------------------------- #
def postprocess(root_path, cfg, tree="tree"):
    """Add decayT and eventWeight to a decay run's output.root.

    Everything is derived from what Geant4 recorded: flight length s =
    |primaryEnd - primaryStart| (the primary is neutral with only Decay +
    Transportation, so its track ends at the decay OR the world boundary),
    beta*gamma from the gun momentum and the configured mass. When generation
    used ctau_sample != ctau, each event gets the exact importance weight

        decayed at s:  w = (lam_g / lam_t) * exp(s/lam_g - s/lam_t)
        exited at s:   w = exp(s/lam_g - s/lam_t)        (censored: survival ratio)

    with lam = beta*gamma*ctau per event; otherwise every weight is 1.
    """
    import awkward as ak
    import uproot

    with uproot.open(str(root_path)) as f:
        t = f[tree]
        names = [k.split(";")[0] for k in t.keys()]
        data = {name: t[name].array() for name in names}

    # creator processes are strings in a g4sim file and int codes + legend in
    # one written here (uproot cannot put vector<string> in a TTree); decode so
    # the Decay test below reads the same either way, including on a re-run
    if "trk_creatorProcess" in data:
        data["trk_creatorProcess"] = io.read_string_branch(
            root_path, "trk_creatorProcess", tree)

    sx = np.asarray(data["primaryStartX"], float)
    sy = np.asarray(data["primaryStartY"], float)
    sz = np.asarray(data["primaryStartZ"], float)
    ex = np.asarray(data["primaryEndX"], float)
    ey = np.asarray(data["primaryEndY"], float)
    ez = np.asarray(data["primaryEndZ"], float)
    px = np.asarray(data["primaryStartPx"], float)
    py = np.asarray(data["primaryStartPy"], float)
    pz = np.asarray(data["primaryStartPz"], float)

    s = np.sqrt((ex - sx) ** 2 + (ey - sy) ** 2 + (ez - sz) ** 2)
    p = np.sqrt(px**2 + py**2 + pz**2)
    mass = parent_mass_mev(cfg)
    beta = p / np.sqrt(p**2 + mass**2)
    betagamma = p / mass

    data["decayT"] = s / np.maximum(beta * C_MM_PER_NS, 1e-30)

    ctau_true = ctau_mm(cfg.decay)
    ctau_gen = sampling_ctau_mm(cfg)
    if ctau_gen != ctau_true:
        lam_t = betagamma * ctau_true
        lam_g = betagamma * ctau_gen
        decayed = _decayed_mask(data)
        w = np.exp(s / lam_g - s / lam_t)
        w = np.where(decayed, (lam_g / lam_t) * w, w)
        data["eventWeight"] = w
    else:
        data["eventWeight"] = np.ones(len(s))

    io.write_tree(root_path, data, tree=tree)
    return str(root_path)


def _decayed_mask(data):
    """Per-event: did the primary decay (vs leave the world)? True when any
    track is a direct daughter of the primary created by the Decay process."""
    import awkward as ak
    parent = data["trk_parentID"]
    proc = data["trk_creatorProcess"]
    return np.asarray(ak.any((parent == 1) & (proc == "Decay"), axis=1))
