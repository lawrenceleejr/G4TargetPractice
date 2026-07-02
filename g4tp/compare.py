"""Compare shower stopping between two runs (e.g. depleted uranium vs tungsten).

Overlays, for two output.root files:
  1. dE/dz per incident particle       (the longitudinal shower profile)
  2. cumulative absorbed fraction      ("how much it stops the shower")
  3. per-event energy leakage          (primaryE - totalEdep: escaping + invisible)

Profiles are streamed (see analyze.longitudinal_profile), so arbitrarily large
files run in bounded memory. Positions in the ntuple are mm; everything shown
here is in cm.
"""
from pathlib import Path
import numpy as np

from .analyze import longitudinal_profile


def compare(path_a, path_b, labels=("A", "B"), outdir="g4tp_compare", axis="z"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    la, lb = labels

    ca, da, aa, sa = longitudinal_profile(path_a, axis=axis)
    cb, db, ab, sb = longitudinal_profile(path_b, axis=axis)

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
