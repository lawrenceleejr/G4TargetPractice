#!/usr/bin/env python3
"""Plot (and sanity-check) a run's output ntuple -- the CI docker-run tests' payload.

Deliberately independent of `gdmltp`: it reads `output.root` with uproot/awkward
only, so it checks the *published image's* ntuple against the documented schema
rather than re-using the library that wrote it. `gdmltp analyze` (run alongside
in the same CI job) is the library path; this is the second opinion, and its
PDFs are what the job preserves as artifacts.

  python3 ci_ntuple_plots.py out/output.root -o out/plots --label "150 MeV p -> water"
                             [--require-steps] [--require-nu] [--min-events N]

One panel per PDF, no chartjunk (Tufte); exit code 0 = every requirement met.
"""
import argparse
import sys
from pathlib import Path

import awkward as ak
import numpy as np
import uproot

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Tufte-style rc, inlined so the script is self-contained inside any of the
# published images (cmr10 ships with matplotlib; no LaTeX needed).
RC = {
    "figure.figsize": (4, 3), "figure.dpi": 150, "savefig.bbox": "tight",
    "pdf.fonttype": 42, "font.family": "serif",
    "font.serif": ["cmr10", "Latin Modern Roman", "CMU Serif", "DejaVu Serif"],
    "mathtext.fontset": "cm", "axes.formatter.use_mathtext": True,
    "axes.unicode_minus": False, "font.size": 10, "axes.titlesize": 11,
    "axes.labelsize": 10, "axes.grid": False,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "333333", "axes.linewidth": 0.6,
    "legend.frameon": False, "xtick.direction": "out", "ytick.direction": "out",
    "xtick.major.size": 3, "ytick.major.size": 3,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.color": "333333", "ytick.color": "333333",
    "lines.linewidth": 1.2, "lines.markersize": 4,
}
INK = "#1f1f1f"


def save(fig, ax, path):
    """Range frames (spines spanning the data only), then one panel -> one PDF."""
    for side, lim, ticks in (("bottom", ax.get_xlim(), ax.get_xticks()),
                             ("left", ax.get_ylim(), ax.get_yticks())):
        inside = [t for t in ticks if lim[0] <= t <= lim[1]]
        if inside:
            ax.spines[side].set_bounds(min(inside), max(inside))
    fig.savefig(path, format="pdf")
    plt.close(fig)
    print(f"[ci-plots] wrote {path}")


def hist(values, xlabel, title, path, bins=40, logy=False):
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        print(f"[ci-plots] skipping {Path(path).name}: no entries")
        return False
    if v.min() == v.max():
        # a monoenergetic beam IS the interesting result here (every primary at
        # the requested energy), so draw the delta rather than skip the panel
        c = v.min()
        pad = abs(c) * 0.01 or 0.5
        bins = np.linspace(c - pad, c + pad, 21)
    fig, ax = plt.subplots()
    ax.hist(v, bins=bins, histtype="step", color=INK)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("events")
    ax.set_title(title)
    if logy:
        ax.set_yscale("log")
    save(fig, ax, path)
    return True


def profile(z_mm, edep_mev, n_events, xlabel, title, path, bins=40):
    """Energy deposited per unit depth along the beam, per incident particle."""
    z = np.asarray(ak.to_numpy(ak.flatten(z_mm)), float) / 10.0        # mm -> cm
    e = np.asarray(ak.to_numpy(ak.flatten(edep_mev)), float)
    keep = np.isfinite(z) & np.isfinite(e) & (e > 0)
    z, e = z[keep], e[keep]
    if z.size == 0 or z.min() == z.max():
        print(f"[ci-plots] skipping {Path(path).name}: no depositing steps")
        return False
    edges = np.linspace(z.min(), z.max(), bins + 1)
    dedz = np.histogram(z, bins=edges, weights=e)[0] / np.diff(edges) / max(n_events, 1)
    fig, ax = plt.subplots()
    ax.step(0.5 * (edges[1:] + edges[:-1]), dedz, where="mid", color=INK)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("dE/dz per incident particle [MeV/cm]")
    ax.set_title(title)
    save(fig, ax, path)
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("root", help="output.root from any backend")
    p.add_argument("-o", "--outdir", default="ci_plots")
    p.add_argument("--label", default="",
                   help="title suffix (what was simulated); '->' becomes an arrow "
                        "(the Computer Modern text font has no '<'/'>' glyphs)")
    p.add_argument("--min-events", type=int, default=1)
    p.add_argument("--require-steps", action="store_true",
                   help="fail unless the file carries a Geant4 transport record")
    p.add_argument("--require-nu", action="store_true",
                   help="fail unless the file carries a neutrino interaction block")
    a = p.parse_args(argv)

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(RC)
    # Computer Modern text maps '<'/'>' to inverted punctuation, so spell an
    # arrow in mathtext instead of feeding it raw.
    label = a.label.replace("->", r"$\rightarrow$")
    tag = f" ({label})" if label else ""

    t = uproot.open(a.root)["tree"]
    have = {k.split(";")[0] for k in t.keys()}
    n = t.num_entries
    lines = [f"file:     {a.root}",
             f"events:   {n}",
             f"branches: {len(have)}"]

    prim_e = t["primaryE"].array(library="np") if "primaryE" in have else np.array([])
    edep = t["totalEdep"].array(library="np") if "totalEdep" in have else np.array([])
    n_steps = t["nSteps"].array(library="np") if "nSteps" in have else np.array([])
    if prim_e.size:
        lines.append(f"primaryE: mean {prim_e.mean():.3f} MeV "
                     f"[{prim_e.min():.3f}, {prim_e.max():.3f}]")
    if edep.size:
        lines.append(f"totalEdep: mean {edep.mean():.3f} MeV, "
                     f"events with Edep > 0: {int((edep > 0).sum())}/{n}")
    if n_steps.size:
        lines.append(f"steps: total {int(n_steps.sum())}, max/event {int(n_steps.max())}")

    hist(prim_e, "primary energy [MeV]", f"primary energy{tag}",
         outdir / "primary_energy.pdf")
    hist(edep, "total energy deposit [MeV]", f"energy deposit{tag}",
         outdir / "total_edep.pdf")
    if "nTracks" in have:
        hist(t["nTracks"].array(library="np"), "tracks per event",
             f"track multiplicity{tag}", outdir / "track_multiplicity.pdf")

    if "step_z" in have and "step_edep" in have:
        profile(t["step_z"].array(), t["step_edep"].array(), n,
                "depth along beam z [cm]", f"depth-dose{tag}",
                outdir / "edep_vs_depth.pdf")

    nu = {}
    if "nu_isCC" in have:
        for br in ("nu_isCC", "nu_isNC", "nu_Q2", "nu_W", "nu_y", "nu_x"):
            if br in have:
                nu[br] = t[br].array(library="np")
        acted = np.asarray(nu["nu_isCC"], bool) | np.asarray(nu.get("nu_isNC", nu["nu_isCC"]), bool)
        cc = int(np.asarray(nu["nu_isCC"], bool).sum())
        lines.append(f"nu block: interacting {int(acted.sum())}/{n}, CC {cc}")
        if "nu_Q2" in nu:
            hist(np.asarray(nu["nu_Q2"], float)[acted], r"$Q^2$ [GeV$^2$]",
                 f"momentum transfer{tag}", outdir / "nu_Q2.pdf")
        if "nu_y" in nu:
            hist(np.asarray(nu["nu_y"], float)[acted], "inelasticity $y$",
                 f"inelasticity{tag}", outdir / "nu_y.pdf")
        if "nu_W" in nu:
            hist(np.asarray(nu["nu_W"], float)[acted], "$W$ [GeV]",
                 f"hadronic invariant mass{tag}", outdir / "nu_W.pdf")

    summary = "\n".join(lines) + "\n"
    (outdir / "summary.txt").write_text(summary)
    print(summary)

    # --- requirements: what this CI job claims the docker run produced ------- #
    fails = []
    if n < a.min_events:
        fails.append(f"only {n} events (need >= {a.min_events})")
    if edep.size and not (edep > 0).any():
        fails.append("no event deposited any energy")
    if a.require_steps and not (n_steps.size and n_steps.sum() > 0):
        fails.append("no Geant4 transport record (step_*/nSteps empty)")
    if a.require_nu:
        if not nu:
            fails.append("no nu_* interaction block")
        elif not acted.any():
            fails.append("nu_* block present but no event interacted")
    if fails:
        print("[ci-plots] FAIL: " + "; ".join(fails), file=sys.stderr)
        return 1
    print("[ci-plots] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
