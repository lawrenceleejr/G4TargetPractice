"""Host-side decay generator for long-lived BSM projectiles (HNLs, dark
photons, ALPs, dark scalars -- anything defined by a mass, a proper decay
length, and decay channels).

The `decay` backend flies the parent along rays sampled by the common beam
machinery (spectra, distributions, Twiss), decays it in flight, and writes a
vertex-level `output.root` in the common schema -- exactly like the GENIE /
Achilles backends, except the "engine" is this module running on the host.
`decay.transport: true` then pushes the daughters through the GDML detector
with Geant4 via the existing hand-off, giving the full detector response of a
displaced decay.

Physics content and its honest limits:
  * Decay position: exponential in flight length with lab decay length
    lambda = beta*gamma*c*tau = (|p|/M)*ctau. A fiducial window (in z or in
    path length) forces the decay inside it via the truncated exponential and
    records the true occupation probability per event in `eventWeight`.
  * Decay time `decayT` = flight length / (beta c), carried into the Geant4
    hand-off so daughter timing is right.
  * Daughter kinematics: exact two-body; N-body via the Raubold-Lynch (GENBOD)
    phase-space algorithm with accept-reject unweighting. Three-body channels
    may request the V-A matrix element `model: vA`, defined (for an
    UNPOLARIZED parent) as |M|^2 propto (p_parent . p_2)(p_1 . p_3) with the
    daughters listed [1, 2, 3] -- the muon-decay pairing: for
    mu- -> [e-, anti-nu_e, nu_mu] this reproduces the Michel spectrum.
    Parent polarization and channel-specific form factors are NOT modeled.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from . import masses
from .beam import _len_mm
from .config import ConfigError

C_MM_PER_NS = 299.792458

# Optional event scalars this backend adds on top of the common schema (also
# grafted onto the transported file by the hand-off).
OPTIONAL_SCALAR_BRANCHES = ["eventWeight", "decayT"]


# --------------------------------------------------------------------------- #
# Channel spec
# --------------------------------------------------------------------------- #
@dataclass
class Channel:
    pdgs: list                 # daughter PDG ids
    br: float                  # branching ratio (normalized across channels)
    model: str = "phase_space"  # phase_space | vA (3-body only)
    masses: list = field(default_factory=list)  # resolved daughter masses [MeV]


def _resolve_channels(decay_cfg, parent_mass_mev):
    """Turn decay.channels into Channel objects with resolved masses; enforce
    energy conservation and normalize branching ratios."""
    channels = []
    for i, ch in enumerate(decay_cfg["channels"]):
        pdgs = [int(p) for p in ch["to"]]
        ms = []
        for p in pdgs:
            m = masses.mass_mev(p)
            if m == 0.0 and abs(p) not in (12, 14, 16, 22):
                raise ConfigError(
                    f"decay.channels[{i}]: no rest mass known for PDG {p}; "
                    f"only particles in gdmltp.masses (or massless nu/gamma) "
                    f"can be decay daughters")
            ms.append(m)
        if sum(ms) >= parent_mass_mev:
            raise ConfigError(
                f"decay.channels[{i}] ({pdgs}): daughter masses sum to "
                f"{sum(ms):.1f} MeV >= parent mass {parent_mass_mev:.1f} MeV")
        channels.append(Channel(pdgs=pdgs, br=float(ch.get("br", 1.0)),
                                model=ch.get("model", "phase_space"), masses=ms))
    total = sum(c.br for c in channels)
    for c in channels:
        c.br /= total
    return channels


def _ctau_mm(decay_cfg, parent_mass_mev):
    """Proper decay length in mm, from decay.ctau or decay.lifetime."""
    if decay_cfg.get("ctau"):
        return _len_mm(decay_cfg["ctau"])
    # lifetime given as "<value> <unit>" in time units
    parts = str(decay_cfg["lifetime"]).split()
    val = float(parts[0])
    unit = (parts[1] if len(parts) > 1 else "ns").lower()
    to_ns = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}
    if unit not in to_ns:
        raise ConfigError(f"unknown lifetime unit {unit!r}")
    return val * to_ns[unit] * C_MM_PER_NS


# --------------------------------------------------------------------------- #
# Rest-frame kinematics
# --------------------------------------------------------------------------- #
def two_body(M, m1, m2, n, rng):
    """Exact isotropic two-body decay in the parent rest frame.
    Returns (n, 2, 4) arrays of four-momenta [E, px, py, pz] in MeV."""
    p = math.sqrt(max(0.0, (M**2 - (m1 + m2)**2) * (M**2 - (m1 - m2)**2))) / (2 * M)
    cos_t = rng.uniform(-1.0, 1.0, n)
    phi = rng.uniform(0.0, 2 * math.pi, n)
    sin_t = np.sqrt(1.0 - cos_t**2)
    d = np.stack([sin_t * np.cos(phi), sin_t * np.sin(phi), cos_t], axis=1)
    e1 = math.sqrt(p * p + m1 * m1)
    e2 = math.sqrt(p * p + m2 * m2)
    out = np.empty((n, 2, 4))
    out[:, 0, 0] = e1
    out[:, 0, 1:] = p * d
    out[:, 1, 0] = e2
    out[:, 1, 1:] = -p * d
    return out


def _two_body_p(M, m1, m2):
    return math.sqrt(max(0.0, (M**2 - (m1 + m2)**2) * (M**2 - (m1 - m2)**2))) / (2 * M)


def _genbod_batch(M, ms, n, rng):
    """One batch of Raubold-Lynch phase-space configurations in the parent rest
    frame. Returns (momenta (n, k, 4), weights (n,)). Weights are the standard
    GENBOD event weights (product of two-body momenta over the chain)."""
    k = len(ms)
    ms = np.asarray(ms, float)
    t_kin = M - ms.sum()

    # Ordered intermediate invariant masses: M_1 = m_1, M_k = M, and
    # M_j = sum(m_1..m_j) + (sorted uniform fractions of the kinetic energy).
    u = np.sort(rng.random((n, k - 2)), axis=1) if k > 2 else np.zeros((n, 0))
    frac = np.concatenate([np.zeros((n, 1)), u, np.ones((n, 1))], axis=1)  # (n, k)
    csum = np.concatenate([np.zeros(1), np.cumsum(ms)])                    # (k+1,)
    inv = csum[1:][None, :] + frac * t_kin                                 # (n, k) M_j

    # Two-body momentum q_j of {M_{j-1} system, m_j} in the M_j rest frame.
    weights = np.ones(n)
    momenta = np.zeros((n, k, 4))

    for j in range(1, k):
        Mj = inv[:, j]
        Mprev = inv[:, j - 1]
        mj = ms[j]
        q = np.sqrt(np.maximum(0.0,
            (Mj**2 - (Mprev + mj)**2) * (Mj**2 - (Mprev - mj)**2))) / (2 * Mj)
        weights *= q

        # emit m_j back-to-back with the (1..j-1) system, isotropically in the
        # M_j rest frame
        cos_t = rng.uniform(-1.0, 1.0, n)
        phi = rng.uniform(0.0, 2 * math.pi, n)
        sin_t = np.sqrt(1.0 - cos_t**2)
        d = np.stack([sin_t * np.cos(phi), sin_t * np.sin(phi), cos_t], axis=1)

        pj = q[:, None] * d
        ej = np.sqrt(q**2 + mj**2)
        esys = np.sqrt(q**2 + Mprev**2)

        if j == 1:
            # the "system" is bare particle 0: place it directly (boosting its
            # rest four-vector breaks down when m_0 = 0)
            momenta[:, 0, 0] = esys
            momenta[:, 0, 1:] = -pj
        else:
            # boost the accumulated system: the (0..j-1) composite of mass
            # M_{j-1} moves with velocity -pj/esys in the M_j frame
            beta = -pj / esys[:, None]
            momenta[:, :j] = _boost_rows(momenta[:, :j], beta)
        momenta[:, j, 0] = ej
        momenta[:, j, 1:] = pj

    return momenta, weights


def _boost_rows(p4, beta):
    """Boost four-momenta p4 (n, k, 4) by per-event velocity beta (n, 3)."""
    b2 = np.sum(beta**2, axis=1)
    gamma = 1.0 / np.sqrt(np.maximum(1e-30, 1.0 - b2))
    bp = np.einsum("nkj,nj->nk", p4[:, :, 1:], beta)
    gain = np.where(b2 > 0, (gamma - 1.0) / np.maximum(b2, 1e-30), 0.0)
    out = np.empty_like(p4)
    out[:, :, 0] = gamma[:, None] * (p4[:, :, 0] + bp)
    out[:, :, 1:] = (p4[:, :, 1:]
                     + beta[:, None, :] * (gain[:, None] * bp
                                           + gamma[:, None] * p4[:, :, 0])[:, :, None])
    return out


def _me_weight(model, p4, M):
    """Matrix-element weight per event on rest-frame configurations p4
    (n, 3, 4). vA: |M|^2 propto (P.p2)(p1.p3) = M*E2 * (p1.p3)."""
    if model == "phase_space":
        return np.ones(len(p4))
    e2 = p4[:, 1, 0]
    dot13 = (p4[:, 0, 0] * p4[:, 2, 0]
             - np.einsum("nj,nj->n", p4[:, 0, 1:], p4[:, 2, 1:]))
    return M * e2 * dot13


def rest_frame_decay(M, channel, n, rng):
    """n unweighted decays of a parent of mass M via `channel`, in the parent
    rest frame. Returns (n, k, 4) four-momenta [MeV]."""
    ms = channel.masses
    if len(ms) == 2:
        return two_body(M, ms[0], ms[1], n, rng)

    # accept-reject: GENBOD weight x matrix element, max estimated on a pilot
    # batch and padded; re-estimated upward if exceeded (keeps correctness).
    pilot, wp = _genbod_batch(M, ms, max(2000, n), rng)
    wp = wp * _me_weight(channel.model, pilot, M)
    wmax = float(wp.max()) * 1.25

    out = np.empty((n, len(ms), 4))
    got = 0
    while got < n:
        batch = max(1000, 2 * (n - got))
        p4, w = _genbod_batch(M, ms, batch, rng)
        w = w * _me_weight(channel.model, p4, M)
        if w.max() > wmax:
            # a raised ceiling invalidates earlier acceptances -- start over
            wmax = float(w.max()) * 1.25
            got = 0
            continue
        keep = p4[rng.random(batch) < w / wmax]
        take = min(len(keep), n - got)
        out[got:got + take] = keep[:take]
        got += take
    return out


# --------------------------------------------------------------------------- #
# Flight + vertex sampling
# --------------------------------------------------------------------------- #
def sample_flight(pos, mom, mass, ctau_mm, fiducial, rng):
    """Decay point along each ray. Returns (vertex (n,3) mm, t_ns (n,),
    weight (n,)). Free decay -> weight 1; a fiducial window forces the decay
    inside via the truncated exponential and weight = P(decay in window)."""
    n = len(pos)
    pmag = np.linalg.norm(mom, axis=1)
    if np.any(pmag <= 0):
        raise ConfigError("decay backend: zero-momentum parent (check beam)")
    lam = (pmag / mass) * ctau_mm                     # beta*gamma * ctau
    dirs = mom / pmag[:, None]

    if fiducial:
        smin, smax = _fiducial_window(pos, dirs, fiducial)
        bad = smax <= smin
        if bad.any():
            raise ConfigError(
                f"decay.fiducial: {int(bad.sum())}/{n} rays never cross the "
                f"fiducial window (check beam direction vs the z range)")
        a = np.exp(-smin / lam)
        b = np.exp(-smax / lam)
        weight = a - b
        s = -lam * np.log(a - rng.random(n) * (a - b))
    else:
        weight = np.ones(n)
        s = rng.exponential(1.0, n) * lam

    vertex = pos + dirs * s[:, None]
    beta = pmag / np.sqrt(pmag**2 + mass**2)
    t_ns = s / (beta * C_MM_PER_NS)
    return vertex, t_ns, weight


def _fiducial_window(pos, dirs, fiducial):
    """Per-ray [smin, smax] flight-length window from decay.fiducial."""
    n = len(pos)
    smin = np.zeros(n)
    smax = np.full(n, np.inf)
    if "path" in fiducial:
        smin = np.maximum(smin, _len_mm(str(fiducial["path"][0])))
        smax = np.minimum(smax, _len_mm(str(fiducial["path"][1])))
    if "z" in fiducial:
        z0, z1 = (_len_mm(str(v)) for v in fiducial["z"])
        dz = dirs[:, 2]
        if np.any(np.abs(dz) < 1e-12):
            raise ConfigError("decay.fiducial.z needs a beam with a z component; "
                              "use fiducial.path for transverse beams")
        s0 = (z0 - pos[:, 2]) / dz
        s1 = (z1 - pos[:, 2]) / dz
        smin = np.maximum(smin, np.minimum(s0, s1))
        smax = np.minimum(smax, np.maximum(s0, s1))
    smin = np.maximum(smin, 0.0)
    return smin, smax


# --------------------------------------------------------------------------- #
# Event generation -> schema output
# --------------------------------------------------------------------------- #
def generate(cfg, n, seed=None):
    """Generate n decays of the configured parent. Returns a dict of arrays
    ready for the schema writer (see write_output)."""
    from . import beam as beammod

    rng = np.random.default_rng(seed)
    parent_pdg = cfg.beam.pdg_code()
    if parent_pdg is None:
        raise ConfigError("the decay backend needs the projectile as a PDG id "
                          "(beam.pdg or a numeric beam.particle)")
    mass = beammod._mass_mev(cfg.beam)
    if mass <= 0:
        raise ConfigError(
            f"no rest mass for PDG {parent_pdg}: set beam.mass (e.g. \"1.0 GeV\") "
            f"for BSM projectiles")

    channels = _resolve_channels(cfg.decay, mass)
    ctau = _ctau_mm(cfg.decay, mass)

    # production kinematics from the common beam machinery
    sample = beammod.sample(cfg, n, seed=seed)
    pos, mom = sample.pos, sample.mom

    vertex, t_ns, weight = sample_flight(pos, mom, mass, ctau,
                                         cfg.decay.get("fiducial"), rng)

    # Channel choice per event, then rest-frame decay + boost to the lab.
    # The rest-frame configurations are isotropic (unpolarized parent) and the
    # vA weight is rotation-invariant, so boosting by the parent's lab
    # velocity vector directly is exact -- no separate rotation needed.
    idx = rng.choice(len(channels), size=n, p=[c.br for c in channels])
    pdg_out, p_out = [], []
    e_parent = np.sqrt(np.linalg.norm(mom, axis=1) ** 2 + mass**2)
    for ci, ch in enumerate(channels):
        sel = np.where(idx == ci)[0]
        if not len(sel):
            continue
        p4 = rest_frame_decay(mass, ch, len(sel), rng)          # (m, k, 4) rest
        beta_lab = mom[sel] / e_parent[sel, None]               # (m, 3)
        lab = _boost_rows(p4, beta_lab)
        for row, evi in enumerate(sel):
            pdg_out.append((evi, ch.pdgs))
            p_out.append((evi, lab[row]))

    # reassemble per-event (jagged) daughter lists in event order
    pdg_out.sort(key=lambda t: t[0])
    p_out.sort(key=lambda t: t[0])
    daughters_pdg = [t[1] for t in pdg_out]
    daughters_p4 = [t[1] for t in p_out]

    return {
        "parent_pdg": parent_pdg, "mass": mass,
        "pos": pos, "mom": mom, "e_parent": e_parent,
        "vertex": vertex, "t_ns": t_ns, "weight": weight,
        "daughters_pdg": daughters_pdg, "daughters_p4": daughters_p4,
    }


def write_output(ev, out_path, tree="tree"):
    """Write generated decays as a vertex-level schema output.root (the same
    shape genie_convert/achilles_convert emit, plus eventWeight/decayT)."""
    import awkward as ak
    import uproot

    n = len(ev["vertex"])
    counts = np.array([len(p) for p in ev["daughters_pdg"]], np.int64)
    flat_pdg = np.array([p for row in ev["daughters_pdg"] for p in row], np.int64)
    flat_p4 = np.vstack([p4 for p4 in ev["daughters_p4"]]) if n else np.zeros((0, 4))
    flat_mass = np.array([masses.mass_mev(p) for p in flat_pdg])
    flat_kin = np.maximum(0.0, flat_p4[:, 0] - flat_mass)

    vx, vy, vz = ev["vertex"].T
    j = lambda flat: ak.unflatten(flat, counts)
    zeros_j = j(np.zeros(int(counts.sum())))

    data = {
        "eventID": np.arange(n, dtype=np.int32),
        "primaryPDG": np.full(n, ev["parent_pdg"], np.int32),
        "primaryE": ev["e_parent"],
        "primaryStartX": ev["pos"][:, 0], "primaryStartY": ev["pos"][:, 1],
        "primaryStartZ": ev["pos"][:, 2],
        "primaryStartPx": ev["mom"][:, 0], "primaryStartPy": ev["mom"][:, 1],
        "primaryStartPz": ev["mom"][:, 2],
        "primaryEndE": np.zeros(n),
        "primaryEndX": vx, "primaryEndY": vy, "primaryEndZ": vz,
        "primaryEndPx": np.zeros(n), "primaryEndPy": np.zeros(n),
        "primaryEndPz": np.zeros(n),
        "totalEdep": np.zeros(n),
        "nSteps": np.zeros(n, np.int32),
        "nTracks": counts.astype(np.int32),
        "eventWeight": np.asarray(ev["weight"], float),
        "decayT": np.asarray(ev["t_ns"], float),
        "trk_id": j(np.concatenate([np.arange(1, c + 1) for c in counts])
                    .astype(np.int32) if counts.sum() else
                    np.array([], np.int32)),
        "trk_parentID": ak.values_astype(zeros_j, np.int32),
        "trk_pdg": j(flat_pdg.astype(np.int32)),
        "trk_startX": j(np.repeat(vx, counts)),
        "trk_startY": j(np.repeat(vy, counts)),
        "trk_startZ": j(np.repeat(vz, counts)),
        "trk_startE": j(flat_kin),
        "trk_endX": j(np.repeat(vx, counts)),
        "trk_endY": j(np.repeat(vy, counts)),
        "trk_endZ": j(np.repeat(vz, counts)),
        "trk_endE": zeros_j,
        "trk_edep": zeros_j, "trk_length": zeros_j,
        "trk_creatorProcess": j(np.array(["Decay"] * int(counts.sum()))),
        "trk_px": j(flat_p4[:, 1]), "trk_py": j(flat_p4[:, 2]),
        "trk_pz": j(flat_p4[:, 3]),
        "step_trackID": _empty(n, np.int32), "step_pdg": _empty(n, np.int32),
        "step_x": _empty(n), "step_y": _empty(n), "step_z": _empty(n),
        "step_kinE": _empty(n), "step_edep": _empty(n),
        "step_length": _empty(n), "step_time": _empty(n),
        "step_process": _empty_str(n),
    }
    with uproot.recreate(out_path) as f:
        f[tree] = data
    return str(out_path)


def _empty(n, dtype=np.float64):
    import awkward as ak
    return ak.unflatten(np.array([], dtype), np.zeros(n, np.int64))


def _empty_str(n):
    import awkward as ak
    return ak.unflatten(np.array([], dtype=str), np.zeros(n, np.int64))
