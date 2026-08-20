"""Container image names.

These guard a failure mode that is invisible at runtime: if the code's image
names and the ones CI publishes drift apart, `docker pull` still succeeds and
silently serves a stale engine. That is exactly what a GitHub repository rename
did -- CI moved to `gdmltargetpractice*` while the code still asked for
`g4targetpractice*`, which GHCR kept as separate frozen packages, so runs got a
months-old g4sim with no `/gun/hepmcFile` and the generator hand-off broke.

The repository-name half of the check lives in CI (it needs
`${{ github.repository }}`); what is checkable here is that every image shares
one stem and tag, i.e. that a rename was applied everywhere or nowhere.
"""
import pytest

from gdmltp import images
from gdmltp.backends import achilles, geant4, genie, pythia


ALL_DEFAULTS = {
    "geant4": geant4.DEFAULT_IMAGE,
    "genie": genie.GENIE_IMAGE,
    "achilles": achilles.ACHILLES_IMAGE,
    "pythia": pythia.PYTHIA_IMAGE,
}


def test_every_backend_default_comes_from_the_one_stem():
    for generator, img in ALL_DEFAULTS.items():
        assert img == images.image(generator), generator
        repo, _, tag = img.rpartition(":")
        assert repo.startswith(images.STEM), f"{generator}: {img}"
        assert tag == images.DEFAULT_TAG, f"{generator}: {img}"


def test_the_stem_carries_no_trace_of_the_old_name():
    """A half-applied rename is the bug this file exists for."""
    for generator, img in ALL_DEFAULTS.items():
        assert "g4targetpractice" not in img, generator


def test_suffixes_are_distinct_and_geant4_has_none():
    assert images.SUFFIXES["geant4"] == ""
    others = [v for k, v in images.SUFFIXES.items() if k != "geant4"]
    assert len(set(others)) == len(others)
    assert all(v.startswith("-") for v in others)


def test_unknown_generator_is_an_error_not_a_silent_bad_name():
    with pytest.raises(ValueError) as exc:
        images.image("fluka")
    assert "fluka" in str(exc.value)


def test_sibling_derivation_covers_every_generator_suffix():
    """The transport stage derives the engine image from the generator image, so
    every published generator suffix must be recognized -- a missed one silently
    falls back to the default tag, which may be older than the hand-off."""
    from gdmltp.config import RunConfig
    cfg = RunConfig(gdml="g.gdml")
    g4 = geant4.Geant4Backend()
    for generator, img in ALL_DEFAULTS.items():
        if generator == "geant4":
            continue
        derived = g4.image_for(cfg, generator_image=f"{images.STEM}{images.SUFFIXES[generator]}:brnch")
        assert derived == f"{images.STEM}:brnch", generator


@pytest.mark.parametrize("img", [
    "ghcr.io/lawrenceleejr/g4targetpractice:main",
    "ghcr.io/lawrenceleejr/g4targetpractice-genie:main",
    "ghcr.io/lawrenceleejr/g4targetpractice-achilles:some-branch",
    "ghcr.io/lawrenceleejr/g4targetpractice",
])
def test_retired_repos_are_flagged_with_the_replacement(img):
    """Pinning a retired repository SUCCEEDS and hands back a frozen engine, so
    the only defense is saying so out loud."""
    msg = images.retired_repo_warning(img)
    assert msg is not None, img
    assert "RETIRED" in msg
    assert images.REPO in msg          # the message names the replacement


@pytest.mark.parametrize("img", [
    None, "",
    "ghcr.io/lawrenceleejr/gdmltargetpractice:main",
    "ghcr.io/lawrenceleejr/gdmltargetpractice-genie:main",
    "my/local-build:latest",
    # a repo that merely CONTAINS the retired name is not the retired repo
    "ghcr.io/someone/not-g4targetpractice:main",
])
def test_current_and_unrelated_images_are_not_flagged(img):
    assert images.retired_repo_warning(img) is None, img
