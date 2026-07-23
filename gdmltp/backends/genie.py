"""GENIE backend: turn the common RunConfig into a GENIE job spec.

The host writes a `genie_job.json` describing the probe, target, flux and run;
the GENIE container's driver reads it, runs the generation + conversion pipeline
(gevgen -> gntpc gst -> genie_convert), and writes `output.root` in the shared
schema. GENIE is a neutrino generator, so the projectile must be a neutrino.
"""
import json
from pathlib import Path

from .base import Backend, Prepared
from ..config import ConfigError

GENIE_IMAGE = "ghcr.io/lawrenceleejr/g4targetpractice-genie:main"
JOB_FILE = "genie_job.json"

# Geant4 particle names -> PDG (neutrinos only; GENIE is a neutrino generator).
_PROBE_PDG = {
    "nu_e": 12, "anti_nu_e": -12,
    "nu_mu": 14, "anti_nu_mu": -14,
    "nu_tau": 16, "anti_nu_tau": -16,
}

# Coarse material-name -> struck-nucleus PDG map for target inference. Users can
# always override with genie.target; molecular targets (e.g. water) collapse to
# their dominant heavy nucleus here and should be given explicitly for accuracy.
_MATERIAL_NUCLEUS = [
    ("lar", 1000180400), ("argon", 1000180400),
    ("water", 1000080160),                        # O-16 (free H ignored)
    ("graphite", 1000060120), ("carbon", 1000060120), ("_c", 1000060120),
    ("silicon", 1000140280), ("_si", 1000140280),
    ("iron", 1000260560), ("steel", 1000260560),
    ("hydrogen", 1000010010),
]


_UNIT_TO_GEV = {"ev": 1e-9, "kev": 1e-6, "mev": 1e-3, "gev": 1.0, "tev": 1e3}


def parse_energy_gev(s) -> float:
    """'2.0 GeV' -> 2.0 (GeV). A bare number is assumed to be GeV."""
    parts = str(s).split()
    val = float(parts[0])
    if len(parts) > 1:
        val *= _UNIT_TO_GEV.get(parts[1].lower(), 1.0)
    return val


def flux_gevgen_args(flux: dict):
    """Map the common energy spec to gevgen -e/-f arguments.

    v1 maps `mono` (single energy) and `exp` (functional spectrum over a range).
    `gauss`/`arb` are approximated by their nominal energy (a faithful histogram
    flux driver is a documented follow-up); the second return value flags whether
    the mapping is approximate so the caller can warn.
    """
    mode = flux.get("mode", "mono")
    if mode == "mono":
        return ["-e", f"{parse_energy_gev(flux['value']):g}"], False
    if mode == "exp":
        e0 = parse_energy_gev(flux["value"])
        emin = parse_energy_gev(flux["min"]); emax = parse_energy_gev(flux["max"])
        return ["-e", f"{emin:g},{emax:g}", "-f", f"exp(-x/{e0:g})"], False
    return ["-e", f"{parse_energy_gev(flux['value']):g}"], True


def probe_pdg(particle: str) -> int:
    try:
        return _PROBE_PDG[particle]
    except KeyError:
        raise ConfigError(
            f"the genie backend only supports neutrino projectiles, got {particle!r} "
            f"(one of: {', '.join(sorted(_PROBE_PDG))})")


def _nucleus_for_material(mat: str):
    m = (mat or "").lower()
    for needle, pdg in _MATERIAL_NUCLEUS:
        if needle in m:
            return pdg
    return None


def _primitive_size(p):
    """A crude volume proxy (product of the numeric params) to pick the target
    volume over small structural pieces like windows/vessels."""
    vals = [abs(float(v)) for v in p.params.values()
            if isinstance(v, (int, float))]
    size = 1.0
    for v in vals:
        if v > 0:
            size *= v
    return size


def infer_target(gdml_path) -> int:
    """Infer the struck nucleus from the largest recognized non-world volume."""
    from .. import geometry
    prims = geometry.parse_gdml(str(gdml_path), include_world=True)
    candidates = []
    for p in prims:
        if getattr(p, "is_world", False):
            continue
        nucleus = _nucleus_for_material(getattr(p, "material", ""))
        if nucleus is not None:
            candidates.append((_primitive_size(p), nucleus, p.material))
    if not candidates:
        raise ConfigError(
            "could not infer a GENIE target nucleus from the geometry; "
            "set genie.target explicitly (e.g. 1000180400 for Ar-40)")
    candidates.sort(reverse=True)
    return candidates[0][1]


class GenieBackend(Backend):
    name = "genie"
    default_image = GENIE_IMAGE

    def prepare(self, cfg, outdir, image=None) -> Prepared:
        if not cfg.gdml:
            raise ConfigError("the genie backend requires geometry.gdml")
        outdir = Path(outdir)

        target = cfg.genie.get("target")
        if target in (None, "", "auto"):
            target = infer_target(cfg.gdml)

        e = cfg.beam.energy
        job = {
            "generator": "genie",
            "gdml": Path(cfg.gdml).name,
            "probe": probe_pdg(cfg.beam.particle),
            "target": int(target),
            "flux": {
                "mode": e.mode,
                "value": e.value,
                "min": e.min,
                "max": e.max,
                "bins": e.bins,
            },
            "position": cfg.beam.position,
            "direction": cfg.beam.direction,
            "events": int(cfg.run.events),
            "output": cfg.run.output,
            "tune": cfg.genie.get("tune", "G18_10a_00_000"),
            "cross_sections": cfg.genie.get("cross_sections", "auto"),
            "event_generator_list": cfg.genie.get("event_generator_list", "Default"),
            "length_units": cfg.genie.get("length_units", "cm"),
            "seed": cfg.run.seed,
        }
        (outdir / JOB_FILE).write_text(json.dumps(job, indent=2) + "\n")

        return Prepared(argv=[JOB_FILE],
                        image=image or self.image_for(cfg),
                        env={}, output=cfg.run.output)
