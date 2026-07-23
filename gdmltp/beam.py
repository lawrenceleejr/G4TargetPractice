"""Host-side beam sampler: turn a beam spec (per-parameter distributions or a
Twiss phase-space) into N explicit primaries, written to a portable beam file
that each generator replays (one primary per event).

This is the shared, deterministic, unit-tested core of the distribution/Twiss
feature: the engines never sample these themselves. Output units match the
schema and the beam file: positions in mm, momenta in MeV/c.
"""
import math
from dataclasses import dataclass

import numpy as np

from . import masses, particles

# --- unit tables ----------------------------------------------------------- #
_LEN_MM = {"mm": 1.0, "millimeter": 1.0, "cm": 10.0, "centimeter": 10.0,
           "m": 1000.0, "meter": 1000.0, "um": 1e-3, "nm": 1e-6, "km": 1e6}
_ANG_RAD = {"rad": 1.0, "radian": 1.0, "mrad": 1e-3, "urad": 1e-6,
            "deg": math.pi / 180.0, "degree": math.pi / 180.0}
_ENE_MEV = {"ev": 1e-6, "kev": 1e-3, "mev": 1.0, "gev": 1e3, "tev": 1e6}


def _parse(s, table, default_unit, strip_c=False):
    """Parse a '<value> <unit>' string into the table's base unit. A bare number
    uses default_unit. Momentum units may carry a trailing '/c' (stripped)."""
    if s is None:
        raise ValueError("missing value")
    parts = str(s).split()
    val = float(parts[0])
    unit = parts[1] if len(parts) > 1 else default_unit
    if strip_c and unit.lower().endswith("/c"):
        unit = unit[:-2]
    factor = table.get(unit.lower())
    if factor is None:
        raise ValueError(f"unknown unit {unit!r}")
    return val * factor


def _len_mm(s):
    return _parse(s, _LEN_MM, "mm")


def _ang_rad(s):
    return _parse(s, _ANG_RAD, "rad")


def _ene_mev(s):
    return _parse(s, _ENE_MEV, "MeV")


def _mom_mev(s):
    return _parse(s, _ENE_MEV, "MeV", strip_c=True)


def _vec3(s, parser):
    parts = str(s).split()
    if len(parts) < 3:
        raise ValueError(f"expected 3 components, got {s!r}")
    # a shared trailing unit token applies to all three (e.g. "0 0 -20 cm")
    unit = parts[3] if len(parts) > 3 else ""
    return np.array([parser(f"{parts[i]} {unit}".strip()) for i in range(3)], float)


# --- distribution sampling ------------------------------------------------- #
@dataclass
class Sample:
    name: str
    pos: np.ndarray   # (n, 3) mm
    mom: np.ndarray   # (n, 3) MeV/c

    def __len__(self):
        return len(self.pos)


def _sample_dist(d, n, rng, parser):
    """Sample a config.Distribution into an (n,) array in the parser's base unit."""
    if d.kind == "fixed":
        return np.full(n, parser(d.value))
    if d.kind == "gauss":
        mean = parser(d.mean) if d.mean is not None else 0.0
        return rng.normal(mean, parser(d.sigma), n)
    if d.kind == "uniform":
        return rng.uniform(parser(d.min), parser(d.max), n)
    raise ValueError(f"unknown distribution kind {d.kind!r}")


def _sample_energy_mev(energy, n, rng):
    """Sample the existing energy modes (mono/gauss/exp/arb) into MeV, mirroring
    g4sim's PrimaryGenerator sampling so host and engine agree."""
    mode = energy.mode
    if mode == "mono":
        return np.full(n, _ene_mev(energy.value))
    if mode == "gauss":
        out = rng.normal(_ene_mev(energy.value), _ene_mev(energy.sigma), n)
        # resample non-positive energies (matches the gun's rejection)
        bad = out <= 0
        while bad.any():
            out[bad] = rng.normal(_ene_mev(energy.value), _ene_mev(energy.sigma), bad.sum())
            bad = out <= 0
        return out
    if mode == "exp":
        e0 = _ene_mev(energy.value); emin = _ene_mev(energy.min); emax = _ene_mev(energy.max)
        # inverse-CDF of exp(-E/E0) on [emin, emax]
        u = rng.random(n)
        a = math.exp(-emin / e0); b = math.exp(-emax / e0)
        return -e0 * np.log(a - u * (a - b))
    if mode == "arb":
        vals = np.array([_ene_mev(b["value"]) for b in energy.bins])
        w = np.array([float(b.get("weight", 1.0)) for b in energy.bins])
        w = w / w.sum()
        return rng.choice(vals, size=n, p=w)
    raise ValueError(f"unknown energy mode {energy.mode!r}")


def _mass_mev(name):
    pdg = particles.pdg_for(name)
    if pdg is None:
        raise ValueError(
            f"cannot convert energy->momentum for unknown particle {name!r}; "
            f"specify beam.momentum (|p|) instead")
    return masses.mass_mev(pdg)


# --- rotation (CLHEP rotateUz: map local +z onto axis u) ------------------- #
def rotate_uz(vecs, axis):
    """Rotate row-vectors so their local +z maps onto unit `axis` (like CLHEP
    Hep3Vector::rotateUz). vecs: (n,3); axis: (3,) unit. Returns (n,3)."""
    ux, uy, uz = axis
    up = ux * ux + uy * uy
    x, y, z = vecs[:, 0], vecs[:, 1], vecs[:, 2]
    if up > 0:
        up = math.sqrt(up)
        nx = (ux * uz * x - uy * y) / up + ux * z
        ny = (uy * uz * x + ux * y) / up + uy * z
        nz = -up * x + uz * z
        return np.column_stack([nx, ny, nz])
    if uz < 0:                       # axis = -z: flip x and z
        return np.column_stack([-x, y, -z])
    return vecs.copy()               # axis = +z: identity


def rotate_uz_rows(vecs, axes):
    """rotateUz applied per row: rotate vecs[i] so local +z maps onto axes[i].
    vecs, axes: (n,3); axes need not be normalized. Returns (n,3)."""
    out = np.empty_like(vecs, dtype=float)
    for i in range(len(vecs)):
        out[i] = rotate_uz(vecs[i:i + 1].astype(float), _unit(axes[i]))[0]
    return out


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else np.array([0.0, 0.0, 1.0])


# --- top-level -------------------------------------------------------------- #
def needs_sampling(cfg) -> bool:
    return cfg.beam.needs_sampling()


def sample(cfg, n, seed=None):
    """Sample n primaries from the beam spec. Returns a Sample (mm, MeV/c)."""
    rng = np.random.default_rng(seed)
    beam = cfg.beam
    if beam.twiss:
        return _sample_twiss(beam, n, rng)
    return _sample_independent(beam, n, rng)


def _sample_independent(beam, n, rng):
    # --- positions (mm) ---
    if beam.position_dist:
        x = _sample_dist(beam.position_dist["x"], n, rng, _len_mm)
        y = _sample_dist(beam.position_dist["y"], n, rng, _len_mm)
        z = _sample_dist(beam.position_dist["z"], n, rng, _len_mm)
        pos = np.column_stack([x, y, z])
    else:
        p0 = _vec3(beam.position, _len_mm)
        pos = np.tile(p0, (n, 1))

    # --- momentum magnitude (MeV/c) ---
    if beam.momentum is not None:
        pmag = _sample_dist(beam.momentum, n, rng, _mom_mev)
    else:
        ekin = _sample_energy_mev(beam.energy, n, rng)
        m = _mass_mev(beam.particle)
        pmag = np.sqrt(np.maximum(0.0, (ekin + m) ** 2 - m * m))

    # --- direction: local slopes then rotate onto the central direction ---
    if beam.direction_slopes:
        xp = _sample_dist(beam.direction_slopes["xprime"], n, rng, _ang_rad)
        yp = _sample_dist(beam.direction_slopes["yprime"], n, rng, _ang_rad)
    elif beam.angle_sigma:
        sig = _ang_rad(beam.angle_sigma)
        theta = rng.normal(0.0, sig, n)
        phi = rng.uniform(0.0, 2 * math.pi, n)
        xp = np.sin(theta) * np.cos(phi)
        yp = np.sin(theta) * np.sin(phi)
    else:
        xp = np.zeros(n); yp = np.zeros(n)

    pz_loc = np.sqrt(np.maximum(0.0, 1.0 - xp * xp - yp * yp))
    local = np.column_stack([xp, yp, pz_loc])
    d0 = _unit(np.array([float(v) for v in beam.direction.split()[:3]]))
    dirs = rotate_uz(local, d0)
    mom = dirs * pmag[:, None]
    return Sample(beam.particle, pos, mom)


def _beam_matrix(tp):
    """Twiss beam matrix in SI (m, rad): eps*[[beta,-alpha],[-alpha,gamma]].
    emittance is geometric mm.mrad -> m.rad = *1e-6; beta already in m."""
    eps = tp.emittance * 1e-6
    gamma = (1.0 + tp.alpha ** 2) / tp.beta
    return eps * np.array([[tp.beta, -tp.alpha], [-tp.alpha, gamma]])


def _sample_plane(tp, n, rng):
    """Returns (u_mm, uprime_rad) for one transverse plane."""
    cov = _beam_matrix(tp)
    draws = rng.multivariate_normal([0.0, 0.0], cov, n)
    u_m, uprime_rad = draws[:, 0], draws[:, 1]
    return u_m * 1000.0, uprime_rad          # m -> mm; slope stays rad


def _sample_twiss(beam, n, rng):
    tw = beam.twiss
    x_mm, xp = _sample_plane(tw.x, n, rng)
    y_mm, yp = _sample_plane(tw.y, n, rng)

    p0 = _mom_mev(tw.p0)
    delta = rng.normal(0.0, tw.dp_over_p, n) if tw.dp_over_p else np.zeros(n)
    pmag = p0 * (1.0 + delta)

    pz_loc = np.sqrt(np.maximum(0.0, 1.0 - xp * xp - yp * yp))
    mom_local = np.column_stack([xp, yp, pz_loc]) * pmag[:, None]
    pos_local = np.column_stack([x_mm, y_mm, np.zeros(n)])

    d0 = _unit(np.array([float(v) for v in tw.ref_direction.split()[:3]]))
    ref = _vec3(tw.ref_position, _len_mm)
    pos = rotate_uz(pos_local, d0) + ref
    mom = rotate_uz(mom_local, d0)
    return Sample(beam.particle, pos, mom)


# --- beam file I/O ---------------------------------------------------------- #
_HEADER = "# gdmltp beam file: name  x y z [mm]  px py pz [MeV/c]"


def write_beam_file(sample, path):
    lines = [_HEADER]
    for i in range(len(sample)):
        x, y, z = sample.pos[i]
        px, py, pz = sample.mom[i]
        lines.append(f"{sample.name} {x:.6g} {y:.6g} {z:.6g} {px:.6g} {py:.6g} {pz:.6g}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return str(path)


def read_beam_file(path):
    """Return a list of (name, (x,y,z) mm, (px,py,pz) MeV/c)."""
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t = line.split()
            out.append((t[0], tuple(float(v) for v in t[1:4]),
                        tuple(float(v) for v in t[4:7])))
    return out
