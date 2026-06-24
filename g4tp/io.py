"""Load output.root (TTree 'tree') with uproot. No ROOT required."""
from dataclasses import dataclass, field
import numpy as np

# Branch groups mirroring g4sim/RunAction.hh exactly.
SCALAR_BRANCHES = [
    "eventID", "primaryPDG", "primaryE",
    "primaryStartX", "primaryStartY", "primaryStartZ",
    "primaryStartPx", "primaryStartPy", "primaryStartPz",
    "primaryEndE", "primaryEndX", "primaryEndY", "primaryEndZ",
    "primaryEndPx", "primaryEndPy", "primaryEndPz",
    "totalEdep", "nSteps", "nTracks",
]
TRK_BRANCHES = [
    "trk_id", "trk_parentID", "trk_pdg",
    "trk_startX", "trk_startY", "trk_startZ", "trk_startE",
    "trk_endX", "trk_endY", "trk_endZ", "trk_endE",
    "trk_edep", "trk_length", "trk_creatorProcess",
]
STEP_BRANCHES = [
    "step_trackID", "step_pdg", "step_x", "step_y", "step_z",
    "step_kinE", "step_edep", "step_length", "step_time", "step_process",
]
NU_BRANCHES = [
    "nu_isCC", "nu_isNC", "nu_interactionProcess",
    "nu_vertexX", "nu_vertexY", "nu_vertexZ", "nu_vertexT",
    "nu_targetZ", "nu_targetA",
    "nu_outLeptonPDG", "nu_outLeptonE",
    "nu_outLeptonPx", "nu_outLeptonPy", "nu_outLeptonPz",
    "nu_Q2", "nu_W", "nu_x", "nu_y", "nu_q0",
]


@dataclass
class Event:
    """One event: scalar fields + per-track and per-step dicts of numpy arrays."""
    index: int
    scalars: dict = field(default_factory=dict)
    trk: dict = field(default_factory=dict)
    step: dict = field(default_factory=dict)
    nu: dict = field(default_factory=dict)

    @property
    def has_nu(self):
        return bool(self.nu)


def open_tree(path, tree="tree"):
    import uproot
    f = uproot.open(path)
    if tree not in f:
        # take the first TTree-like object
        keys = [k.split(";")[0] for k in f.keys()]
        if not keys:
            raise ValueError(f"No objects in {path}")
        tree = keys[0]
    return f[tree]


def available_branches(path, tree="tree"):
    t = open_tree(path, tree)
    return [k.split(";")[0] for k in t.keys()]


def num_events(path, tree="tree"):
    """Entry count without materializing any branch (lets callers load a slice)."""
    return open_tree(path, tree).num_entries


def load_events(path, tree="tree", entry_start=None, entry_stop=None):
    """Return a list[Event]. Reads only branches that exist (nu_* optional)."""
    t = open_tree(path, tree)
    present = set(k.split(";")[0] for k in t.keys())

    def read(names):
        # Read each branch separately: a single multi-branch np conversion fails
        # on jagged/string branches (it tries to build one structured array).
        out = {}
        for n in names:
            if n not in present:
                continue
            arr = t[n].array(library="np", entry_start=entry_start, entry_stop=entry_stop)
            out[n] = arr
        return out

    sc = read(SCALAR_BRANCHES)
    trk = read(TRK_BRANCHES)
    step = read(STEP_BRANCHES)
    nu = read(NU_BRANCHES)

    n = t.num_entries if (entry_start is None and entry_stop is None) else (
        (entry_stop or t.num_entries) - (entry_start or 0))
    # number actually read
    any_arr = next((v for v in {**sc, **trk, **step}.values()), None)
    n = len(any_arr) if any_arr is not None else 0

    events = []
    for i in range(n):
        ev = Event(index=i)
        ev.scalars = {k: _scalar(v[i]) for k, v in sc.items()}
        ev.trk = {k: np.asarray(v[i]) for k, v in trk.items()}
        ev.step = {k: np.asarray(v[i]) for k, v in step.items()}
        ev.nu = {k: _scalar(v[i]) for k, v in nu.items()}
        events.append(ev)
    return events


def _scalar(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    if isinstance(v, np.generic):
        return v.item()
    return v
