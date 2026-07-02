import numpy as np

from g4tp import scene


def test_build_scene(synth_event):
    sc = scene.build_scene([], synth_event)
    assert len(sc.tracks) > 0
    for t in sc.tracks:
        assert t.polyline.ndim == 2 and t.polyline.shape[1] == 3
        assert len(t.times) == len(t.polyline)
        assert t.name and t.color.startswith("#")
    assert np.all(np.isfinite(sc.bbox_min)) and np.all(np.isfinite(sc.bbox_max))
    assert sc.radius > 0
    assert sc.meta["primaryPDG"] == 11


def test_max_tracks_cap_keeps_primaries(synth_event):
    sc = scene.build_scene([], synth_event, max_tracks=5)
    assert len(sc.tracks) <= 5
    # the primary (parent 0) must survive the cap
    assert any(t.parent_id == 0 for t in sc.tracks)


def test_polyline_step_points_grouped(synth_event):
    """Each track's polyline points must come from its own steps only."""
    sc = scene.build_scene([], synth_event, max_tracks=2000)
    sid = np.asarray(synth_event.step["step_trackID"])
    for t in sc.tracks[:5]:
        n_own = int(np.sum(sid == t.track_id))
        # polyline = start + own steps + end
        assert len(t.polyline) == n_own + 2


def test_scene_with_geometry(synth_event, repo_root):
    from g4tp import geometry
    prims = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml")
    sc = scene.build_scene(prims, synth_event)
    assert sc.primitives
