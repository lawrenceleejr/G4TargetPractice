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
# Optional per-track momentum at production (MeV/c). Written by the vertex-level
# generator converters (GENIE/Achilles) so displays can draw momentum rays for
# tracks that were never transported; g4sim does not (yet) write these.
TRK_OPTIONAL_BRANCHES = ["trk_px", "trk_py", "trk_pz"]
# Optional per-event scalars added by the decay backend's post-processing and
# the external converter (and grafted onto transported files): the lifetime
# importance weight / HepMC event weight, and the decay/vertex time [ns].
SCALAR_OPTIONAL_BRANCHES = ["eventWeight", "decayT"]
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


import os
from functools import lru_cache


#: Legend for branches whose strings are stored as integer codes (see
#: `write_tree`): one entry per (branch, code) -> value.
STRING_LEGEND_TREE = "gdmltp_strings"
_NO_VALUES = -1                     # legend row meaning "encoded, but no values"


def write_tree(path, data, tree="tree", title=""):
    """Write `data` (name -> array) as a **classic TTree** at `path`.

    Every ntuple this package writes goes through here, because the obvious
    spelling stopped meaning what the schema promises: as of uproot 5.7 the
    dict-like assignment `f["tree"] = data` writes an **RNTuple**, and a file
    holding one greets `root output.root` with

        Error in <TKey::ReadObj>: Unknown class ROOT::RNTuple

    on any ROOT older than that class -- while uproot itself reads it back
    happily, so nothing in our own tooling notices. `mktree` + `extend` is the
    explicit TTree path (and behaves the same on older uproot).

    uproot's TTree writer cannot express `std::vector<std::string>`, which is
    what g4sim writes for the per-track/per-step process names, so those
    branches are stored as jagged **int32 codes** plus a `gdmltp_strings`
    legend tree mapping (branch, code) -> value. `read_string_branch` /
    `load_events` decode them transparently, and a native g4sim file (real
    strings) reads the same way.
    """
    import uproot

    payload, legend = _encode_string_branches(data)
    n = _num_entries(payload)
    with uproot.recreate(str(path)) as f:
        # Declare the branches from the data's TYPES, then fill: handing mktree
        # the arrays themselves would write them once as a side effect and again
        # on extend (every event duplicated).
        f.mktree(tree, {k: _branch_type(v) for k, v in payload.items()},
                 title=title)
        if n:
            f[tree].extend(dict(payload))
        if legend:
            f.mktree(STRING_LEGEND_TREE,
                     {"branch": np.dtype(str), "code": np.dtype(np.int32),
                      "value": np.dtype(str)},
                     title="string branches stored as int codes")
            f[STRING_LEGEND_TREE].extend(legend)
    return str(path)


def _branch_type(v):
    """The type spec for one branch: a numpy dtype, or the awkward type of a
    jagged branch. An all-empty jagged branch types as `var * unknown`, which
    uproot cannot write, so it is pinned to float64 -- the schema's empty
    step_*/trk_* branches carry no values to lose."""
    import awkward as ak
    if isinstance(v, ak.Array):
        t = ak.type(v)
        if str(t).endswith("* unknown"):
            return ak.types.ArrayType(
                ak.types.ListType(ak.types.NumpyType("float64")), len(v))
        return t
    return np.asarray(v).dtype


def _num_entries(data):
    for v in data.values():
        try:
            return len(v)
        except TypeError:                     # a scalar: nothing to count
            continue
    return 0


def _is_jagged_string(v):
    """A `var * string` awkward array -- what uproot cannot put in a TTree.

    A FLAT string array (`N * string`) is fine: uproot writes those as a normal
    char branch, so only the nested case needs encoding. In awkward a string is
    itself a list of chars, so the two are told apart by depth, not by the
    innermost type.
    """
    import awkward as ak
    if not isinstance(v, ak.Array):
        return False
    tokens = str(ak.type(v)).split(" * ")
    return len(tokens) > 2 and tokens[-1] == "string"


def _encode_string_branches(data):
    """Replace `var * string` branches with int32 codes; return (data, legend).

    The legend is a flat table (branch, code, value) -- itself TTree-writable.
    A branch with no values at all still gets one row, so a reader can tell an
    encoded-but-empty branch from a genuinely numeric one.
    """
    import awkward as ak

    out, branches, codes, values = {}, [], [], []
    for name, v in data.items():
        if not _is_jagged_string(v):
            out[name] = v
            continue
        flat = ak.to_numpy(ak.flatten(v, axis=1)).astype(str)
        vocab, encoded = np.unique(flat, return_inverse=True)
        out[name] = ak.unflatten(encoded.astype(np.int32), ak.to_numpy(ak.num(v)))
        if len(vocab) == 0:
            branches.append(name); codes.append(_NO_VALUES); values.append("")
            continue
        for code, value in enumerate(vocab):
            branches.append(name); codes.append(code); values.append(str(value))

    legend = None
    if branches:
        legend = {"branch": branches,
                  "code": np.asarray(codes, np.int32),
                  "value": values}
    return out, legend


def string_legend(path):
    """{branch: [value per code]} from a file's `gdmltp_strings` tree ({} if none)."""
    import uproot
    with uproot.open(str(path)) as f:
        if STRING_LEGEND_TREE not in [k.split(";")[0] for k in f.keys()]:
            return {}
        t = f[STRING_LEGEND_TREE]
        branch = [_as_str(x) for x in t["branch"].array(library="np")]
        code = t["code"].array(library="np")
        value = [_as_str(x) for x in t["value"].array(library="np")]
    out = {}
    for b, c, v in zip(branch, code, value):
        vals = out.setdefault(b, [])
        if int(c) == _NO_VALUES:
            continue
        if int(c) >= len(vals):
            vals.extend([""] * (int(c) + 1 - len(vals)))
        vals[int(c)] = v
    return out


def decode_string_branch(array, legend_values):
    """Jagged int codes -> jagged strings, using this branch's legend values."""
    import awkward as ak
    if legend_values is None:                 # already strings (a g4sim file)
        return array
    names = np.asarray(list(legend_values), dtype=object)
    flat = ak.to_numpy(ak.flatten(array)).astype(np.int64)
    decoded = names[flat] if len(names) and len(flat) else np.array([], dtype=object)
    return ak.unflatten(ak.Array(list(decoded)), ak.to_numpy(ak.num(array)))


def read_string_branch(path, name, tree="tree"):
    """Read a process-name branch as strings, whether the file stores them as
    `std::vector<std::string>` (g4sim) or as codes + legend (written here)."""
    t = open_tree(str(path), tree)
    arr = t[name].array()
    if _is_jagged_string(arr):
        return arr
    return decode_string_branch(arr, string_legend(path).get(name))


def _as_str(v):
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)


def open_tree(path, tree="tree"):
    """Open (and cache) the TTree. One CLI invocation touches the same file from
    several helpers (num_events, read_scalars, iterate_flat, load_events);
    caching the handle means one TFile/metadata parse per file, not one per
    helper -- on a multi-GB file each redundant open costs real time. The cache
    key includes mtime+size, so a file rewritten mid-session (e.g. re-running a
    sim from a notebook) is re-opened, never served stale."""
    st = os.stat(str(path))
    return _open_tree_cached(str(path), tree, st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=8)
def _open_tree_cached(path, tree, _mtime_ns, _size):
    import uproot
    f = uproot.open(path)
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

    # process-name branches are strings in a g4sim file and int codes + legend
    # in one we wrote; decode the latter so callers always see names
    legend = string_legend(path)

    def read(names):
        # Read each branch separately: a single multi-branch np conversion fails
        # on jagged/string branches (it tries to build one structured array).
        out = {}
        for n in names:
            if n not in present:
                continue
            if n in legend:
                arr = decode_string_branch(
                    t[n].array(entry_start=entry_start, entry_stop=entry_stop),
                    legend[n]).to_list()
                out[n] = np.array([np.asarray(x, dtype=object) for x in arr],
                                  dtype=object)
                continue
            arr = t[n].array(library="np", entry_start=entry_start, entry_stop=entry_stop)
            out[n] = arr
        return out

    sc = read(SCALAR_BRANCHES)
    trk = read(TRK_BRANCHES + TRK_OPTIONAL_BRANCHES)
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
