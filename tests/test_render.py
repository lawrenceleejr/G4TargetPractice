from gdmltp import scene, render_web, render_png


def test_render_html(synth_event, tmp_path):
    sc = scene.build_scene([], synth_event)
    out = render_web.render_html([sc], tmp_path / "event.html")
    html = out.read_text()
    assert len(html) > 1000
    assert "/*{{SCENE_JSON}}*/ []" not in html         # data was inlined
    assert '"event_id"' in html and '"tracks"' in html


def test_render_png(synth_event, tmp_path):
    sc = scene.build_scene([], synth_event)
    paths = render_png.render_png(sc, tmp_path / "event")
    assert len(paths) == 4                             # xy, xz, yz, iso
    for p in paths:
        assert p.exists() and p.stat().st_size > 5000, p


def test_render_geometry_only(repo_root, tmp_path):
    from gdmltp import geometry
    from gdmltp.scene import Scene, _fit
    prims = geometry.parse_gdml(repo_root / "gdml" / "bpe_slab.gdml")
    sc = Scene(primitives=prims, event_id=0)
    _fit(sc)
    paths = render_png.render_png(sc, tmp_path / "geo")
    assert all(p.exists() for p in paths)
    out = render_web.render_html([sc], tmp_path / "geo.html")
    assert out.exists()
