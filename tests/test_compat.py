"""The deprecated `g4tp` name must keep working as an alias for `gdmltp`."""
import warnings

import pytest


def test_import_g4tp_warns():
    # Fresh import in a subinterpreter-ish way is overkill; just assert the
    # module is importable and exposes the version. The warning is emitted at
    # first import (which pytest's collection already triggered), so we only
    # assert behavior here.
    import g4tp
    import gdmltp
    assert g4tp.__version__ == gdmltp.__version__


def test_g4tp_submodules_alias_gdmltp():
    import g4tp.io
    import gdmltp.io
    assert g4tp.io is gdmltp.io
    from g4tp.backends import genie_convert as gc_old
    from gdmltp.backends import genie_convert as gc_new
    assert gc_old is gc_new


def test_g4tp_cli_main_is_gdmltp_cli_main():
    from g4tp import cli as old_cli
    from gdmltp import cli as new_cli
    assert old_cli.main is new_cli.main


def test_g4tp_attribute_delegation():
    import g4tp
    # attribute access delegates to gdmltp (e.g. g4tp.config)
    assert g4tp.config.RunConfig().generator == "geant4"


def test_fresh_import_emits_deprecation_warning():
    """A first import of g4tp warns. We simulate 'fresh' by removing it from
    sys.modules and re-importing under a warning catcher."""
    import importlib
    import sys
    for name in [k for k in list(sys.modules) if k == "g4tp" or k.startswith("g4tp.")]:
        del sys.modules[name]
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        importlib.import_module("g4tp")
    assert any(issubclass(w.category, DeprecationWarning) for w in rec)
