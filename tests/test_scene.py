import numpy as np

from g4tp import io, scene


def _first_event(path):
    return io.load_events(path, entry_start=0, entry_stop=1)[0]


def test_build_scene(synth_root):
    ev = _first_event(synth_root)
    sc = scene.build_scene([], ev)
    assert len(sc.tracks) > 0
    for t in sc.tracks:
        assert t.polyline.ndim == 2 and t.polyline.shape[1] == 3
        assert len(t.times) == len(t.polyline)
        assert t.name and t.color.startswith("#")
    assert np.all(np.isfinite(sc.bbox_min)) and np.all(np.isfinite(sc.bbox_max))
    assert sc.radius > 0
    assert sc.meta["primaryPDG"] == 11


def test_max_tracks_cap_keeps_primaries(synth_root):
    ev = _first_event(synth_root)
    sc = scene.build_scene([], ev, max_tracks=5)
    assert len(sc.tracks) <= 5
    # the primary (parent 0) must survive the cap
    assert any(t.parent_id == 0 for t in sc.tracks)


def test_polyline_step_points_grouped(synth_root):
    """Each track's polyline points must come from its own steps only."""
    ev = _first_event(synth_root)
    sc = scene.build_scene([], ev, max_tracks=2000)
    sid = np.asarray(ev.step["step_trackID"])
    for t in sc.tracks[:5]:
        n_own = int(np.sum(sid == t.track_id))
        # polyline = start + own steps + end
        assert len(t.polyline) == n_own + 2


def test_scene_with_geometry(synth_root, repo_root):
    from g4tp import geometry
    prims = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml")
    ev = _first_event(synth_root)
    sc = scene.build_scene(prims, ev)
    assert sc.primitives
