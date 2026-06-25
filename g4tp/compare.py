"""Compare longitudinal shower stopping between two runs (e.g. DU vs W).

Reads two output.root files, builds the longitudinal energy-deposition profile
along the beam, and overlays:
  1. dE/dz per incident particle  (the shower profile)
  2. cumulative absorbed fraction vs depth  ("how much it stops the shower")

Depth is measured from the primary vertex along the beam, with the sign taken
from the primary's momentum, so it works for a +z or -z beam alike.

The profile is built by *streaming* the file in batches (uproot.iterate) and
reading only the two branches it needs (the depth axis + step_edep) plus a
handful of per-event scalars. Nothing else is materialized, so a 20 GB file
costs roughly one batch of RAM, not the whole tree -- loading the full file
with io.load_events() would build Event objects for every track/step and is
what made `g4tp compare` crawl on large outputs.
"""
import time
from pathlib import Path
import numpy as np

from . import io

# Fine accumulation grid: bin steps at this resolution [cm] via np.bincount,
# growing the array to whatever max depth appears, then rebin to `nbins` for
# plotting. Fine enough that the rebinned 140-bin profile is unaffected.
_W_FINE = 0.1


def _profile(path, axis="z", nbins=140, step_size="256 MB", verbose=True):
    """Stream `path` and return (centers_cm, dEdz, absorbed_fraction, stats)."""
    zkey = {"x": "step_x", "y": "step_y", "z": "step_z"}[axis]
    p0key = {"x": "primaryStartX", "y": "primaryStartY", "z": "primaryStartZ"}[axis]
    pzkey = {"x": "primaryStartPx", "y": "primaryStartPy", "z": "primaryStartPz"}[axis]

    t = io.open_tree(path)
    present = set(k.split(";")[0] for k in t.keys())
    if zkey not in present or "step_edep" not in present:
        raise ValueError(f"{path}: missing {zkey}/step_edep (was the sim run with step output?)")

    # Per-event scalars are tiny (one value per event) -- read them whole-file.
    def scalar_array(name):
        return t[name].array(library="np") if name in present else None

    z0arr, pzarr, E0arr = scalar_array(p0key), scalar_array(pzkey), scalar_array("primaryE")
    tEarr = scalar_array("totalEdep")
    n = int(t.num_entries)
    z0 = float(np.median(z0arr)) if z0arr is not None and len(z0arr) else 0.0
    sign = -1.0 if (pzarr is not None and len(pzarr) and np.median(pzarr) < 0) else 1.0
    if E0arr is not None and np.any(E0arr > 0):
        E0 = float(np.median(E0arr[E0arr > 0]))
    else:
        E0 = 1.0

    # Energy leakage from the scalar branches alone (no step data needed):
    # totalEdep is summed over every step of every track in the world, so
    # primaryE - totalEdep is the kinetic energy that escaped the world boundary
    # plus invisible energy (neutrons/neutrinos/nuclear breakup). Per event.
    if E0arr is not None and tEarr is not None:
        good = E0arr > 0
        pe = E0arr[good].astype(float)
        td = tEarr[good].astype(float)
        leak_frac = 1.0 - td / pe                  # fraction of beam energy not deposited
        leak_MeV = pe - td
    else:
        leak_frac = np.array([])
        leak_MeV = np.array([])

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

    import awkward as ak  # ships with uproot; flattens jagged step branches cheaply
    for batch in t.iterate([zkey, "step_edep"], step_size=step_size, library="ak"):
        seen += len(batch)
        z = np.asarray(ak.flatten(batch[zkey]), dtype=float)
        w = np.asarray(ak.flatten(batch["step_edep"]), dtype=float)
        depth = sign * (z - z0)
        keep = depth >= 0
        depth, w = depth[keep], w[keep]
        if not len(depth):
            if verbose:
                print(f"[g4tp]   {seen}/{n} events ({time.perf_counter() - t0:.1f}s)", flush=True)
            continue

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

    # Axis range: 99.9th percentile of step depths (count-weighted, like the
    # original) so a few far-flung secondaries don't stretch the plot.
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
    absorbed = cum / (n * E0)                                 # fraction of beam energy absorbed

    # Zero the axis at the absorber entry (first bin carrying real energy) so an
    # air standoff between the vertex and the face doesn't offset the curve.
    centers = 0.5 * (edges[:-1] + edges[1:])
    peak = dEdz.max() if len(dEdz) else 0.0
    if peak > 0:
        centers = centers - edges[int(np.argmax(dEdz > 0.01 * peak))]

    def depth_at(frac):
        i = np.searchsorted(absorbed, frac * absorbed[-1])
        return float(centers[min(i, len(centers) - 1)])

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
        "mean_contained_MeV": float(np.mean(E0arr[E0arr > 0].astype(float) - leak_MeV))
        if len(leak_MeV) else float("nan"),
    }
    if verbose:
        print(f"[g4tp] {Path(path).name}: done in {time.perf_counter() - t0:.1f}s", flush=True)
    return centers, dEdz, absorbed, stats


def compare(path_a, path_b, labels=("A", "B"), outdir="g4tp_compare", axis="z"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    la, lb = labels

    ca, da, aa, sa = _profile(path_a, axis=axis)
    cb, db, ab, sb = _profile(path_b, axis=axis)

    lines = [f"g4tp compare: {la} ({path_a})  vs  {lb} ({path_b})", ""]
    for lab, s in ((la, sa), (lb, sb)):
        lines += [
            f"[{lab}] events={s['n_events']}  E0={s['E0_MeV']/1000:.1f} GeV  "
            f"Edep/evt={s['edep_per_event_MeV']/1000:.2f} GeV "
            f"({100*s['absorbed_fraction']:.1f}% of beam)",
            f"        shower max at {s['peak_depth_cm']:.2f} cm;  "
            f"90/95/99% absorbed by {s['d90_cm']:.2f} / {s['d95_cm']:.2f} / {s['d99_cm']:.2f} cm",
        ]
    # head-to-head: how much less material the second needs for 95%
    if sb["d95_cm"]:
        rel = 100 * (sa["d95_cm"] - sb["d95_cm"]) / sb["d95_cm"]
        lines.append("")
        lines.append(f"{la} needs {rel:+.1f}% {'more' if rel>0 else 'less'} depth than "
                     f"{lb} to absorb 95% of the shower.")

    # Energy leakage out of the geometry (whole-event energy balance).
    have_leak = len(sa["leak_frac"]) and len(sb["leak_frac"])
    if have_leak:
        lines += ["", "Energy leakage (primaryE - totalEdep = escaping + invisible):"]
        for lab, s in ((la, sa), (lb, sb)):
            lines.append(
                f"  [{lab}] leaks {100*s['mean_leak_frac']:.2f} +/- "
                f"{100*s['std_leak_frac']:.2f}% of the beam "
                f"({s['mean_leak_MeV']/1000:.3f} GeV/event escapes; "
                f"contains {100*(1-s['mean_leak_frac']):.2f}%)")
        dla, dlb = sa["mean_leak_frac"], sb["mean_leak_frac"]
        diff_pp = 100 * (dla - dlb)
        rel = (100 * (dla - dlb) / dlb) if dlb else float("nan")
        better = lb if dla > dlb else la
        lines.append(
            f"  -> {la} leaks {diff_pp:+.2f} percentage points vs {lb} "
            f"({rel:+.1f}% relative); {better} contains the shower better.")
    report = "\n".join(lines)
    (outdir / "summary.txt").write_text(report + "\n")
    print(report)

    # Plot 1: longitudinal shower profile
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(ca, da, label=la, lw=2)
    ax.plot(cb, db, label=lb, lw=2)
    ax.set_xlabel("depth into absorber [cm]")
    ax.set_ylabel("dE/dz per incident particle [MeV/cm]")
    ax.set_title("Longitudinal shower profile")
    ax.set_xlim(left=0)
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(outdir / "shower_profile.png", dpi=140); plt.close(fig)

    # Plot 2: cumulative absorbed fraction (the "stopping" curve)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(ca, 100 * aa, label=la, lw=2)
    ax.plot(cb, 100 * ab, label=lb, lw=2)
    for s, c in ((sa, "C0"), (sb, "C1")):
        ax.axvline(s["d95_cm"], color=c, ls="--", alpha=0.6)
    ax.set_xlabel("depth into absorber [cm]")
    ax.set_ylabel("cumulative energy absorbed [% of beam]")
    ax.set_title("Shower containment vs depth (dashed = 95%)")
    ax.set_xlim(left=0)
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(outdir / "containment.png", dpi=140); plt.close(fig)

    wrote = ["shower_profile.png", "containment.png"]

    # Plot 3: per-event energy leakage distribution
    if have_leak:
        fa, fb = 100 * sa["leak_frac"], 100 * sb["leak_frac"]
        lo, hi = 0.0, float(max(fa.max(), fb.max())) * 1.05 + 1e-6
        bins = np.linspace(lo, hi, 31)
        fig, ax = plt.subplots(figsize=(6, 4))
        for f, s, lab, c in ((fa, sa, la, "C0"), (fb, sb, lb, "C1")):
            ax.hist(f, bins=bins, histtype="step", lw=2, color=c,
                    label=f"{lab} (mean {100*s['mean_leak_frac']:.2f}%)")
            ax.axvline(100 * s["mean_leak_frac"], color=c, ls="--", alpha=0.7)
        ax.set_xlabel("energy leaked out of geometry [% of beam]")
        ax.set_ylabel("events")
        ax.set_title("Per-event leakage (primaryE - totalEdep)")
        ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
        fig.savefig(outdir / "leakage.png", dpi=140); plt.close(fig)
        wrote.append("leakage.png")

    print(f"\n[g4tp] wrote " + ", ".join(f"{outdir}/{w}" for w in wrote) + ", summary.txt")
    return outdir
