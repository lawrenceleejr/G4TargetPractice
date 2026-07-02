"""Quick analysis: a text summary + standard plots, streamed from output.root.

Everything here reads the file in one of two cheap ways:
  - per-event scalars via io.read_scalars (tiny, whole-file)
  - jagged step/track branches via io.iterate_flat (batched, memory-bounded)
so a multi-GB output analyzes in bounded memory. Positions in the ntuple are
mm (Geant4 internal units); plots and reported depths are in cm.
"""
from pathlib import Path
from collections import Counter
import time
import numpy as np

from . import io, particles

# Fine accumulation grid for longitudinal profiles: bin steps at this
# resolution [cm] via np.bincount, growing the array to whatever max depth
# appears, then rebin to the requested nbins for plotting.
_W_FINE = 0.1


def leakage(E0arr, tEarr):
    """Per-event energy leakage from the scalar branches alone.

    totalEdep is summed over every step of every track in the world, so
    primaryE - totalEdep is the kinetic energy that escaped the world boundary
    plus invisible energy (neutrons/neutrinos/nuclear breakup). Returns
    (leak_fraction, leak_MeV) arrays; empty when either branch is absent.
    """
    if E0arr is None or tEarr is None:
        return np.array([]), np.array([])
    good = np.asarray(E0arr) > 0
    pe = np.asarray(E0arr)[good].astype(float)
    td = np.asarray(tEarr)[good].astype(float)
    return 1.0 - td / pe, pe - td


def longitudinal_profile(path, axis="z", nbins=140, step_size="256 MB", verbose=True):
    """Longitudinal energy-deposition profile along the beam, streamed.

    Returns (centers_cm, dEdz, absorbed_fraction, stats). Depth is measured
    from the primary vertex along the beam (sign taken from the primary's
    momentum, so +z and -z beams both work), then re-zeroed at the absorber
    entry so an air standoff doesn't offset the curve. stats includes peak
    depth, d90/d95/d99 containment depths, and whole-event energy leakage
    (primaryE - totalEdep: energy escaping the world or invisible).
    """
    zkey = {"x": "step_x", "y": "step_y", "z": "step_z"}[axis]
    p0key = {"x": "primaryStartX", "y": "primaryStartY", "z": "primaryStartZ"}[axis]
    pzkey = {"x": "primaryStartPx", "y": "primaryStartPy", "z": "primaryStartPz"}[axis]

    # Per-event scalars are tiny (one value per event) -- read them whole-file.
    sc = io.read_scalars(path, [p0key, pzkey, "primaryE", "totalEdep"])
    z0arr, pzarr = sc.get(p0key), sc.get(pzkey)
    E0arr, tEarr = sc.get("primaryE"), sc.get("totalEdep")
    n = int(io.num_events(path))
    z0 = (float(np.median(z0arr)) if z0arr is not None and len(z0arr) else 0.0) / io.MM_PER_CM
    sign = -1.0 if (pzarr is not None and len(pzarr) and np.median(pzarr) < 0) else 1.0
    # Total beam energy = sum over events, so the absorbed fraction is right
    # for spectrum beams too (a median would misnormalize e.g. an exponential
    # spectrum by tens of percent). E0 is reported as the per-event mean.
    if E0arr is not None and np.any(E0arr > 0):
        beam_MeV = float(E0arr[E0arr > 0].sum())
        E0 = beam_MeV / int(np.count_nonzero(E0arr > 0))
    else:
        beam_MeV = float(n) or 1.0
        E0 = 1.0

    leak_frac, leak_MeV = leakage(E0arr, tEarr)

    if verbose:
        print(f"[g4tp] {Path(path).name}: {n} events, beam {axis}{'+' if sign > 0 else '-'} "
              f"from {z0:.1f} cm, E0={E0/1000:.1f} GeV; streaming step data ...", flush=True)

    # Online histograms on a fixed-width grid anchored at depth 0 (np.bincount):
    # depth>=0 always (we clip), so the bin index is floor(depth / w_fine) and
    # arrays simply grow to the largest depth encountered across all batches.
    e_hist = np.zeros(0, dtype=float)        # energy-weighted  -> dE/dz
    c_hist = np.zeros(0, dtype=np.int64)     # step counts       -> robust axis range
    inv_w = 1.0 / _W_FINE
    seen = 0
    t0 = time.perf_counter()

    for n_batch, cols in io.iterate_flat(path, [zkey, "step_edep"], step_size=step_size):
        seen += n_batch
        z = np.asarray(cols[zkey], float) / io.MM_PER_CM        # mm -> cm
        w = np.asarray(cols["step_edep"], float)
        depth = sign * (z - z0)
        keep = depth >= 0
        depth, w = depth[keep], w[keep]
        if len(depth):
            idx = np.floor(depth * inv_w).astype(np.int64)
            mx = int(idx.max()) + 1
            eb = np.bincount(idx, weights=w, minlength=mx)
            cb = np.bincount(idx, minlength=mx)
            if len(eb) > len(e_hist):
                e_hist = np.pad(e_hist, (0, len(eb) - len(e_hist)))
                c_hist = np.pad(c_hist, (0, len(cb) - len(c_hist)))
            e_hist[:len(eb)] += eb
            c_hist[:len(cb)] += cb
        if verbose:
            print(f"[g4tp]   {seen}/{n} events ({time.perf_counter() - t0:.1f}s)", flush=True)

    if c_hist.sum() == 0:
        raise ValueError(f"{path}: no steps on the +{axis} side of the vertex")

    # Axis range: 99.9th percentile of step depths (count-weighted) so a few
    # far-flung secondaries don't stretch the plot.
    cum_c = np.cumsum(c_hist)
    i999 = int(np.searchsorted(cum_c, 0.999 * cum_c[-1]))
    dmax = max((i999 + 1) * _W_FINE, 2 * _W_FINE)

    # Rebin the fine energy grid to `nbins` over [0, dmax].
    edges = np.linspace(0.0, dmax, nbins + 1)
    binw = edges[1] - edges[0]
    fine_centers = (np.arange(len(e_hist)) + 0.5) * _W_FINE
    hist, _ = np.histogram(fine_centers, bins=edges, weights=e_hist)
    dEdz = hist / n / binw                                    # MeV/cm per incident particle
    cum = np.cumsum(hist)
    absorbed = cum / beam_MeV                                 # fraction of beam energy absorbed

    # Zero the axis at the absorber entry (first bin carrying real energy) so an
    # air standoff between the vertex and the face doesn't offset the curve.
    centers = 0.5 * (edges[:-1] + edges[1:])
    peak = dEdz.max() if len(dEdz) else 0.0
    shift = edges[int(np.argmax(dEdz > 0.01 * peak))] if peak > 0 else 0.0
    centers = centers - shift

    def depth_at(frac):
        # Depth containing `frac` of the RECORDED deposited energy. absorbed[i]
        # is cumulative through bin i, so the answer is that bin's right edge.
        i = min(int(np.searchsorted(absorbed, frac * absorbed[-1])), len(edges) - 2)
        return float(edges[i + 1] - shift)

    stats = {
        "n_events": n, "E0_MeV": E0,
        "edep_per_event_MeV": float(hist.sum() / n),
        "absorbed_fraction": float(absorbed[-1]),
        "peak_depth_cm": float(centers[int(np.argmax(dEdz))]),
        "d90_cm": depth_at(0.90), "d95_cm": depth_at(0.95), "d99_cm": depth_at(0.99),
        # leakage (whole-event energy balance, independent of the profile window)
        "leak_frac": leak_frac,                                       # per-event array
        "mean_leak_frac": float(np.mean(leak_frac)) if len(leak_frac) else float("nan"),
        "std_leak_frac": float(np.std(leak_frac)) if len(leak_frac) else float("nan"),
        "mean_leak_MeV": float(np.mean(leak_MeV)) if len(leak_MeV) else float("nan"),
    }
    if verbose:
        print(f"[g4tp] {Path(path).name}: done in {time.perf_counter() - t0:.1f}s", flush=True)
    return centers, dEdz, absorbed, stats


def summarize(path, outdir="g4tp_analysis", make_plots=True, depth_axis="z"):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    n = int(io.num_events(path))
    lines = [f"g4tp analyze: {path}", f"events: {n}"]
    if n == 0:
        (outdir / "summary.txt").write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        return outdir

    sc = io.read_scalars(path, ["primaryE", "totalEdep", "nSteps", "primaryPDG", "nu_isCC"])
    # Report only branches actually present: a zeros placeholder would fabricate
    # statements like "totalEdep mean 0.000" / "leakage 100%" on trimmed files.
    primE = np.asarray(sc["primaryE"], float) if "primaryE" in sc else None
    edep = np.asarray(sc["totalEdep"], float) if "totalEdep" in sc else None
    if "primaryPDG" in sc and len(sc["primaryPDG"]):
        pdg0 = int(sc["primaryPDG"][0])
        lines.append(f"primary: {particles.name_for(pdg0)} (PDG {pdg0})")
    if primE is not None:
        lines.append(f"primary E [MeV]: mean {primE.mean():.3f}  "
                     f"min {primE.min():.3f}  max {primE.max():.3f}")
    if edep is not None:
        lines.append(f"totalEdep [MeV]: mean {edep.mean():.3f}  max {edep.max():.3f}")
    if "nSteps" in sc:
        lines.append(f"nSteps/event: mean {np.asarray(sc['nSteps'], float).mean():.1f}")
    leak, _ = leakage(primE, edep)
    if len(leak):
        lines.append(f"energy leakage (primaryE - totalEdep): mean {100*leak.mean():.2f}% "
                     f"+/- {100*leak.std():.2f}% of the beam")

    # Particle census, streamed from the (possibly huge) trk_pdg branch.
    sec = Counter()
    try:
        for _, cols in io.iterate_flat(path, ["trk_pdg"]):
            vals, cnts = np.unique(cols["trk_pdg"].astype(np.int64), return_counts=True)
            for v, c in zip(vals, cnts):
                sec[particles.name_for(int(v))] += int(c)
    except ValueError:
        pass  # no per-track block in this file
    if sec:
        lines.append("particles (all tracks, summed): " +
                     ", ".join(f"{k}={v}" for k, v in sec.most_common(15)))

    if "nu_isCC" in sc:
        cc = int(np.sum(np.asarray(sc["nu_isCC"], dtype=bool)))
        lines.append(f"neutrino: CC={cc}/{n} ({100*cc/n:.0f}%)")

    (outdir / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    wrote = ["summary.txt"]
    if make_plots:
        wrote += _plots(path, primE, edep, outdir, depth_axis)
    print(f"\n[g4tp] wrote {outdir}/: " + ", ".join(wrote))
    return outdir


def _plots(path, primE, edep, outdir, depth_axis):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    wrote = []
    for arr, title, fname in [(primE, "primary energy [MeV]", "primary_energy.png"),
                              (edep, "total Edep [MeV]", "total_edep.png")]:
        if arr is None:
            continue
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.hist(arr, bins=min(50, max(5, len(arr))))
        ax.set_xlabel(title); ax.set_ylabel("events"); ax.set_title(title)
        fig.tight_layout(); fig.savefig(outdir / fname, dpi=130); plt.close(fig)
        wrote.append(fname)

    # Depth-dose along the beam (streamed; skipped if there is no step data).
    try:
        centers, dEdz, _, _ = longitudinal_profile(path, axis=depth_axis, verbose=False)
    except ValueError as e:
        print(f"[g4tp] no depth-dose plot: {e}")
        return wrote
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(centers, dEdz, lw=2)
    ax.set_xlabel(f"depth along beam ({depth_axis}) [cm]")
    ax.set_ylabel("dE/dz per incident particle [MeV/cm]")
    ax.set_title("depth-dose")
    ax.set_xlim(left=0)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outdir / "depth_dose.png", dpi=130)
    plt.close(fig)
    wrote.append("depth_dose.png")
    return wrote
