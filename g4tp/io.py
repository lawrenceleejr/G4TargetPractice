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


from functools import lru_cache


@lru_cache(maxsize=8)
def open_tree(path, tree="tree"):
    """Open (and cache) the TTree. One CLI invocation touches the same file from
    several helpers (num_events, read_scalars, iterate_flat, load_events);
    caching the handle means one TFile/metadata parse per file, not one per
    helper -- on a multi-GB file each redundant open costs real time."""
    import uproot
    f = uproot.open(str(path))
    if tree not in f:
        # take the first TTree-like object
        keys = [k.split(";")[0] for k in f.keys()]
        if not keys:
            raise ValueError(f"No objects in {path}")
        tree = keys[0]
    return f[tree]


def branch_names(t):
    """Branch names of an open tree, with ROOT cycle suffixes stripped."""
    return [k.split(";")[0] for k in t.keys()]


def available_branches(path, tree="tree"):
    return branch_names(open_tree(str(path), tree))


def num_events(path, tree="tree"):
    """Entry count without materializing any branch (lets callers load a slice)."""
    return open_tree(str(path), tree).num_entries


# Positions/lengths in the ntuple are Geant4 internal units: mm (energies MeV,
# times ns). Plot-facing code converts to cm with this.
MM_PER_CM = 10.0


def read_scalars(path, names, tree="tree"):
    """Read per-event scalar branches (one value per event -- tiny even for a
    20 GB file) into a dict of numpy arrays. Missing branches are omitted."""
    t = open_tree(str(path), tree)
    present = set(branch_names(t))
    return {n: t[n].array(library="np") for n in names if n in present}


def iterate_flat(path, branches, tree="tree", step_size="256 MB"):
    """Stream numeric jagged branches in batches: yields (n_events, {name: flat array}).

    Reads ONLY `branches`; peak memory is bounded by step_size regardless of
    file size. This is how anything that scans numeric step_*/trk_* values over
    a whole run should read it -- load_events() materializes every branch as
    Python objects and is only for event displays of a few entries. Note the
    limits: string branches (step_process, trk_creatorProcess) and per-event
    scalars are not flattenable here -- use load_events / read_scalars.
    """
    import awkward as ak
    t = open_tree(str(path), tree)
    present = set(branch_names(t))
    missing = [b for b in branches if b not in present]
    if missing:
        raise ValueError(
            f"{path}: missing branch(es): {', '.join(missing)} "
            f"(available: {', '.join(sorted(present)[:12])}...)")
    for batch in t.iterate(list(branches), step_size=step_size, library="ak"):
        # native dtype: float64 comes out zero-copy, ints stay ints
        out = {b: np.asarray(ak.flatten(batch[b])) for b in branches}
        yield len(batch), out


def load_events(path, tree="tree", entry_start=None, entry_stop=None):
    """Return a list[Event]. Reads only branches that exist (nu_* optional)."""
    t = open_tree(str(path), tree)
    present = set(branch_names(t))

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
