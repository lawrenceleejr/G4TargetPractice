"""Matplotlib PNG stills: XY/XZ/YZ projections + an isometric 3D view.

Automatic limits from the scene bounding box. No interactivity; for the
interactive view use render_web (WebGL).
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle


def _pad_bbox(lo, hi, min_half=1.0):
    """Expand any axis whose extent is ~0 so plot limits are never identical."""
    lo = np.asarray(lo, float).copy()
    hi = np.asarray(hi, float).copy()
    flat = (hi - lo) < 1e-6
    lo[flat] -= min_half
    hi[flat] += min_half
    return lo, hi


def _box_corners(p):
    pm = p.params
    h = np.array([pm.get("sx", 0) / 2, pm.get("sy", 0) / 2, pm.get("sz", 0) / 2])
    c = p.transform[:3, 3]
    return c, h


# Total mesh triangles to draw across a still before falling back to bounding
# boxes (matplotlib's Python-side patch drawing is the limit, not the geometry).
_PNG_TRI_CAP = 60000


def _mesh_world_verts(p):
    R, t = p.transform[:3, :3], p.transform[:3, 3]
    return p.mesh.vertices @ R.T + t


def _tri_budget(prims, include_world):
    """How many mesh prims fit under the triangle cap (largest-first is not
    needed; draw in order and stop)."""
    ok = set()
    total = 0
    for k, p in enumerate(prims):
        if p.type == "mesh" and p.mesh is not None and not (p.is_world and not include_world):
            n = len(p.mesh.faces)
            if total + n > _PNG_TRI_CAP:
                continue
            total += n
            ok.add(k)
    return ok


def _draw_geo_2d(ax, prims, ax_i, ax_j, include_world):
    from matplotlib.collections import LineCollection
    budget = _tri_budget(prims, include_world)
    for k, p in enumerate(prims):
        if p.is_world and not include_world:
            continue
        if p.transform is None:
            continue
        c = p.transform[:3, 3]
        if p.type == "mesh" and p.mesh is not None:
            if k in budget:
                w = _mesh_world_verts(p)
                f = p.mesh.faces
                # unique triangle edges projected to (ax_i, ax_j)
                e = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
                e = np.unique(np.sort(e, axis=1), axis=0)
                segs = np.stack([w[e[:, 0]][:, [ax_i, ax_j]],
                                 w[e[:, 1]][:, [ax_i, ax_j]]], axis=1)
                ax.add_collection(LineCollection(segs, colors="0.45", linewidths=0.3, alpha=0.6))
            else:
                pm = p.params
                w2, h2 = pm.get("sx", 0), pm.get("sy", 0)
                off = np.array([pm.get("cx", 0), pm.get("cy", 0), pm.get("cz", 0)])
                cc = c + p.transform[:3, :3] @ off
                sz = [pm.get("sx", 0), pm.get("sy", 0), pm.get("sz", 0)]
                ax.add_patch(Rectangle((cc[ax_i] - sz[ax_i] / 2, cc[ax_j] - sz[ax_j] / 2),
                                       sz[ax_i], sz[ax_j], fill=False, edgecolor="0.6",
                                       lw=0.6, ls=":"))
            continue
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
    # pad any zero-width axis (a point-like single-vertex event) so matplotlib
    # doesn't warn about identical low/high limits
    lo, hi = _pad_bbox(lo, hi)
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
    from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection
    budget = _tri_budget(scene.primitives, include_world)
    segs = []
    tris = []
    for k, p in enumerate(scene.primitives):
        if (p.is_world and not include_world) or p.transform is None:
            continue
        if p.type == "mesh" and p.mesh is not None and k in budget:
            w = _mesh_world_verts(p)
            tris.extend(w[f] for f in p.mesh.faces)
        elif p.type in ("box", "bbox", "mesh"):
            c, h = _box_corners(p)
            segs += _cube_edges(c, h)
    if tris:
        pc = Poly3DCollection(tris, facecolor="#6688aa", edgecolor="#3a4a5a",
                              linewidths=0.15, alpha=0.28)
        ax.add_collection3d(pc)
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
