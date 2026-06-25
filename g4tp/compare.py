"""Compare longitudinal shower stopping between two runs (e.g. DU vs W).

Reads two output.root files, builds the longitudinal energy-deposition profile
along the beam, and overlays:
  1. dE/dz per incident particle  (the shower profile)
  2. cumulative absorbed fraction vs depth  ("how much it stops the shower")

Depth is measured from the primary vertex along the beam, with the sign taken
from the primary's momentum, so it works for a +z or -z beam alike.
"""
from pathlib import Path
import numpy as np

from . import io


def _profile(events, axis="z", nbins=140):
    """Return (depth_edges, dEdz_per_event, absorbed_fraction, stats)."""
    zkey = {"x": "step_x", "y": "step_y", "z": "step_z"}[axis]
    p0key = {"x": "primaryStartX", "y": "primaryStartY", "z": "primaryStartZ"}[axis]
    pzkey = {"x": "primaryStartPx", "y": "primaryStartPy", "z": "primaryStartPz"}[axis]

    depths, weights = [], []
    z0s, signs, E0s = [], [], []
    for e in events:
        z0s.append(float(e.scalars.get(p0key, 0.0)))
        signs.append(float(e.scalars.get(pzkey, 1.0)))
        E0s.append(float(e.scalars.get("primaryE", 0.0)))
        if zkey in e.step and len(e.step[zkey]):
            depths.append(np.asarray(e.step[zkey], float))
            weights.append(np.asarray(e.step["step_edep"], float))
    if not depths:
        raise ValueError("no step_* data in file (was the sim run with step output?)")

    n = len(events)
    z0 = float(np.median(z0s))
    sign = -1.0 if float(np.median(signs)) < 0 else 1.0  # beam travels -z -> depth = z0 - z
    E0 = float(np.median([e for e in E0s if e > 0]) or 1.0)

    z = np.concatenate(depths)
    w = np.concatenate(weights)
    depth = sign * (z - z0)               # 0 at the vertex, growing into the absorber
    depth = depth[depth >= 0]
    w = w[(sign * (z - z0)) >= 0]

    dmax = np.percentile(depth, 99.9) if len(depth) else 1.0
    edges = np.linspace(0.0, dmax, nbins + 1)
    binw = edges[1] - edges[0]
    hist, _ = np.histogram(depth, bins=edges, weights=w)     # MeV per bin, summed over events
    dEdz = hist / n / binw                                   # MeV/cm per incident particle
    cum = np.cumsum(hist)
    absorbed = cum / (n * E0)                                # fraction of incident energy absorbed

    # Zero the axis at the absorber entry (first bin carrying real energy) so any
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
    }
    return centers, dEdz, absorbed, stats


def compare(path_a, path_b, labels=("A", "B"), outdir="g4tp_compare", axis="z"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    la, lb = labels

    ca, da, aa, sa = _profile(io.load_events(path_a), axis=axis)
    cb, db, ab, sb = _profile(io.load_events(path_b), axis=axis)

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

    print(f"\n[g4tp] wrote {outdir}/shower_profile.png, {outdir}/containment.png, summary.txt")
    return outdir
