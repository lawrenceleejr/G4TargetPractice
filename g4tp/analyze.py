"""Quick analysis: a text summary + standard plots, all from output.root via uproot."""
from pathlib import Path
from collections import Counter
import numpy as np

from . import io, particles


def summarize(path, outdir="g4tp_analysis", make_plots=True, depth_axis="z"):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    events = io.load_events(path)
    n = len(events)
    lines = [f"g4tp analyze: {path}", f"events: {n}"]
    if n == 0:
        (outdir / "summary.txt").write_text("\n".join(lines) + "\n")
        return outdir

    primE = np.array([e.scalars.get("primaryE", 0.0) for e in events], float)
    edep = np.array([e.scalars.get("totalEdep", 0.0) for e in events], float)
    nsteps = np.array([e.scalars.get("nSteps", 0) for e in events], float)
    pdg0 = events[0].scalars.get("primaryPDG", 0)
    lines += [
        f"primary: {particles.name_for(pdg0)} (PDG {pdg0})",
        f"primary E [MeV]: mean {primE.mean():.3f}  min {primE.min():.3f}  max {primE.max():.3f}",
        f"totalEdep [MeV]: mean {edep.mean():.3f}  max {edep.max():.3f}",
        f"nSteps/event: mean {nsteps.mean():.1f}",
    ]
    sec = Counter()
    for e in events:
        for pdg in e.trk.get("trk_pdg", []):
            sec[particles.name_for(int(pdg))] += 1
    if sec:
        lines.append("particles (all tracks, summed): " +
                     ", ".join(f"{k}={v}" for k, v in sec.most_common(15)))
    if events[0].has_nu:
        cc = sum(1 for e in events if e.nu.get("nu_isCC"))
        lines.append(f"neutrino: CC={cc}/{n} ({100*cc/n:.0f}%)")

    (outdir / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    if make_plots:
        _plots(events, outdir, depth_axis)
    return outdir


def _plots(events, outdir, depth_axis):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    primE = np.array([e.scalars.get("primaryE", 0.0) for e in events], float)
    edep = np.array([e.scalars.get("totalEdep", 0.0) for e in events], float)

    for arr, title, fname in [(primE, "primary energy [MeV]", "primary_energy.png"),
                              (edep, "total Edep [MeV]", "total_edep.png")]:
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.hist(arr, bins=min(50, max(5, len(arr))))
        ax.set_xlabel(title); ax.set_ylabel("events"); ax.set_title(title)
        fig.tight_layout(); fig.savefig(outdir / fname, dpi=130); plt.close(fig)

    # depth-dose: step_edep vs step depth axis, summed over events
    axkey = {"x": "step_x", "y": "step_y", "z": "step_z"}[depth_axis]
    depths, weights = [], []
    for e in events:
        if axkey in e.step and len(e.step[axkey]):
            depths.append(np.asarray(e.step[axkey], float))
            weights.append(np.asarray(e.step["step_edep"], float))
    if depths:
        d = np.concatenate(depths); w = np.concatenate(weights)
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.hist(d, bins=100, weights=w)
        ax.set_xlabel(f"{depth_axis} [mm]"); ax.set_ylabel("Edep [MeV]")
        ax.set_title("depth-dose"); fig.tight_layout()
        fig.savefig(outdir / "depth_dose.png", dpi=130); plt.close(fig)
