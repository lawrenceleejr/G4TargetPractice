"""Matplotlib PNG stills: XY/XZ/YZ projections + an isometric 3D view.

Automatic limits from the scene bounding box. No interactivity; for the
interactive view use render_web (WebGL).
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle


def _box_corners(p):
    pm = p.params
    h = np.array([pm.get("sx", 0) / 2, pm.get("sy", 0) / 2, pm.get("sz", 0) / 2])
    c = p.transform[:3, 3]
    return c, h


def _draw_geo_2d(ax, prims, ax_i, ax_j, include_world):
    for p in prims:
        if p.is_world and not include_world:
            continue
        if p.transform is None:
            continue
        c = p.transform[:3, 3]
        if p.type in ("box", "bbox", "trd"):
            pm = p.params
            sx = [pm.get("sx", pm.get("x1", 0)), pm.get("sy", pm.get("y1", 0)), pm.get("sz", 0)]
            w, hgt = sx[ax_i], sx[ax_j]
            ls = "--" if p.type == "bbox" else "-"
            ax.add_patch(Rectangle((c[ax_i] - w / 2, c[ax_j] - hgt / 2), w, hgt,
                                   fill=False, edgecolor="0.4", lw=0.8, ls=ls))
        elif p.type == "orb":
            ax.add_patch(Circle((c[ax_i], c[ax_j]), p.params.get("r", 0),
                                fill=False, edgecolor="0.4", lw=0.8))
        elif p.type == "tube":
            r = p.params.get("rmax", 0)
            ax.add_patch(Circle((c[ax_i], c[ax_j]), r, fill=False, edgecolor="0.4", lw=0.8))


def _proj(ax, scene, ax_i, ax_j, labels, include_world):
    _draw_geo_2d(ax, scene.primitives, ax_i, ax_j, include_world)
    for t in scene.tracks:
        ax.plot(t.polyline[:, ax_i], t.polyline[:, ax_j], color=t.color, lw=0.7, alpha=0.85)
    for v in scene.vertices:
        ax.plot(v.pos[ax_i], v.pos[ax_j], marker="s", ms=2.5, color="black", alpha=0.6)
    lo, hi = scene.bbox_min, scene.bbox_max
    pad = 0.05 * (hi - lo + 1e-9)
    ax.set_xlim(lo[ax_i] - pad[ax_i], hi[ax_i] + pad[ax_i])
    ax.set_ylim(lo[ax_j] - pad[ax_j], hi[ax_j] + pad[ax_j])
    ax.set_xlabel(f"{labels[0]} [mm]")
    ax.set_ylabel(f"{labels[1]} [mm]")
    ax.set_aspect("equal", "box")
    ax.set_title(f"{labels[0]}{labels[1]} projection")


def render_png(scene, out_prefix, include_world=False, dpi=150):
    from pathlib import Path
    out_prefix = str(out_prefix)
    paths = []
    for (i, j, labels, suffix) in [(0, 1, ("x", "y"), "xy"),
                                   (0, 2, ("x", "z"), "xz"),
                                   (1, 2, ("y", "z"), "yz")]:
        fig, ax = plt.subplots(figsize=(6, 6))
        _proj(ax, scene, i, j, labels, include_world)
        _legend(ax, scene)
        fig.tight_layout()
        out = f"{out_prefix}_{suffix}.png"
        fig.savefig(out, dpi=dpi)
        plt.close(fig)
        paths.append(Path(out))

    # isometric 3D
    fig = plt.figure(figsize=(7, 6))
    ax = fig.add_subplot(111, projection="3d")
    _draw_geo_3d(ax, scene, include_world)
    for t in scene.tracks:
        ax.plot(t.polyline[:, 0], t.polyline[:, 1], t.polyline[:, 2],
                color=t.color, lw=0.6, alpha=0.85)
    lo, hi = scene.bbox_min, scene.bbox_max
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
    try:
        ax.set_box_aspect(hi - lo + 1e-9)
    except Exception:
        pass
    ax.set_xlabel("x [mm]"); ax.set_ylabel("y [mm]"); ax.set_zlabel("z [mm]")
    ax.view_init(elev=20, azim=-60)
    ax.set_title(f"event {scene.event_id}")
    out = f"{out_prefix}_iso.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    paths.append(Path(out))
    return paths


def _draw_geo_3d(ax, scene, include_world):
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    segs = []
    for p in scene.primitives:
        if (p.is_world and not include_world) or p.transform is None:
            continue
        if p.type in ("box", "bbox"):
            c, h = _box_corners(p)
            segs += _cube_edges(c, h)
    if segs:
        ax.add_collection3d(Line3DCollection(segs, colors="0.6", linewidths=0.5))


def _cube_edges(c, h):
    import itertools
    corners = []
    for sx, sy, sz in itertools.product((-1, 1), (-1, 1), (-1, 1)):
        corners.append(c + np.array([sx * h[0], sy * h[1], sz * h[2]]))
    edges_idx = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
                 (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
    return [(corners[a], corners[b]) for a, b in edges_idx]


def _legend(ax, scene):
    seen = {}
    for t in scene.tracks:
        seen.setdefault(t.name, t.color)
    if not seen:
        return
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], color=col, lw=1.5, label=name) for name, col in seen.items()]
    ax.legend(handles=handles, fontsize=6, loc="upper right", framealpha=0.6)
