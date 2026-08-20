"""Container image names, in one place.

Every image is published by CI as `ghcr.io/<github repository>` (lowercased) with
a per-generator suffix, one tag per branch plus `main`. Keeping the stem here --
rather than a literal in each backend -- is what makes a rename a one-line change
instead of a hunt, and it lets `tests/test_images.py` + the CI check assert that
the stem still matches the repository CI actually pushes to.

That check exists because the drift is silent and expensive: renaming the GitHub
repository (G4TargetPractice -> GDMLTargetPractice) moved CI's pushes to
`gdmltargetpractice*`, while the code still pointed at `g4targetpractice*`.
GHCR left the old packages behind as separate, frozen repositories rather than
aliases, so `docker pull` kept working and silently served a months-old engine --
one with no `/gun/hepmcFile`, which broke the generator->Geant4 hand-off.
"""

REGISTRY = "ghcr.io"
OWNER = "lawrenceleejr"
# The GitHub repository name, lowercased -- CI publishes to
# ghcr.io/${{ github.repository }}, which docker/metadata-action lowercases.
REPO = "gdmltargetpractice"
DEFAULT_TAG = "main"

STEM = f"{REGISTRY}/{OWNER}/{REPO}"

# Suffix per generator; the Geant4 engine image has none. The Celeritas variant
# is a TAG suffix, not an image suffix (see Geant4Backend.image_for).
SUFFIXES = {
    "geant4": "",
    "genie": "-genie",
    "achilles": "-achilles",
    "pythia": "-pythia",
}


def image(generator, tag=DEFAULT_TAG):
    """`image("genie")` -> 'ghcr.io/lawrenceleejr/gdmltargetpractice-genie:main'."""
    try:
        suffix = SUFFIXES[generator]
    except KeyError:
        raise ValueError(
            f"no image for generator {generator!r}; "
            f"known: {', '.join(sorted(SUFFIXES))}") from None
    return f"{STEM}{suffix}:{tag}"


# The pre-rename image repositories. GHCR kept them as separate packages rather
# than aliases when the GitHub repository was renamed, so they are frozen at
# their last pre-rename push -- not just "an older tag", but a repository that
# will never move again.
RETIRED_REPOS = ("g4targetpractice",)


def retired_repo_warning(image):
    """A message if `image` names a retired, frozen repository, else None.

    Worth checking on every explicit --image: pulling one SUCCEEDS and yields a
    stale engine, so without this the only symptom is a run that behaves like an
    old version (e.g. rejecting /gun/hepmcFile and failing the hand-off).
    """
    if not image:
        return None
    repo = image.rpartition(":")[0] or image
    for retired in RETIRED_REPOS:
        # match the repo component, so "<retired>" and "<retired>-genie" both hit
        name = repo.rsplit("/", 1)[-1]
        if name == retired or name.startswith(retired + "-"):
            fixed = image.replace(retired, REPO, 1)
            return (f"the image repository {repo!r} was RETIRED when the GitHub "
                    f"repository was renamed to GDMLTargetPractice. It still "
                    f"pulls, but it is frozen at its last pre-rename build, so "
                    f"you are running a months-old engine. Use:\n    {fixed}")
    return None
