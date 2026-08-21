#!/usr/bin/env python3
"""Cut the interaction region out of the muon collider v0.8 lattice export.

    python3 gdml/mucoll_ip_extract.py            # rewrites mucoll_mdi_v0p8_ip.gdml

`mucoll_mdi_lattice_v0p8.gdml` is a FLUKA-derived export of the whole machine
(tunnel, arcs, rock, the machine-detector interface) and it cannot be tracked
as it stands -- see `examples/mucoll/README.md` for the full diagnosis. Two
facts drive this script:

  * its world is a 10 m cube at the origin, while the MDI it describes sits at
    (0, -30 m, +85 m) -- the interaction point is OUTSIDE the world volume, so
    Geant4 refuses to shoot anything at it;
  * the sub-assembly around the world origin (the beam-pipe/shielding zones
    BEAM_V*/BEAM_P*/BEAM_S*) is riddled with overlaps -- six vacuum cylinders
    share the beam axis, and tungsten shells share space with vacuum -- so
    navigation there is undefined.

The MDI assembly itself is clean: exclusive zones, exactly one volume at every
point tested. This script extracts THAT and nothing else, mechanically:

  1. keep the seven MDI volumes (below), drop the other 303 placements;
  2. translate each kept placement by -(IP) so the interaction point lands on
     the origin -- a rigid shift of whole daughters, so no solid is touched;
  3. size the world to the extracted assembly;
  4. drop the solids nothing references any more (the file goes ~835 kB -> tens
     of kB and Geant4 stops building 700+ unused boolean solids at load).

Materials are kept verbatim: they are small and cross-reference each other.
Nothing else about the kept volumes changes, so the output can be diffed
against the source.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "mucoll_mdi_lattice_v0p8.gdml"
OUTPUT = HERE / "mucoll_mdi_v0p8_ip.gdml"

# The interaction point in the source file's coordinates (mm): the centre of
# the beryllium beam chamber DET_CHAM, which the two nozzle tips point at.
IP_MM = (0.0, -30000.0, 85000.0)

# The MDI assembly, by physvol name. Everything a particle leaving the IP can
# hit within the detector cavern:
KEEP = {
    "DET_CHAM_pv",   # G4_Be    the beam chamber at the IP (r 24 mm, +-158 mm)
    "BP_VAC_pv",     # vacuum   the beam-pipe bore (r <= 23 mm)
    "LW_pv",         # INERM180 upstream tungsten-alloy nozzle
    "RW_pv",         # INERM180 downstream tungsten-alloy nozzle
    "LBb_pv",        # BORETH   borated-polyethylene liner, upstream nozzle
    "RBb_pv",        # BORETH   borated-polyethylene liner, downstream nozzle
    "DET_LAT_pv",    # vacuum   the detector cavern the nozzles sit in
}

# World half-sizes (mm) around the recentred assembly: DET_LAT is a r = 6.774 m,
# +-5.95 m cylinder, so this clears it with room for the primary's start point.
WORLD_HALF = (8000.0, 8000.0, 7000.0)

PROVENANCE = """
  The interaction region of the muon collider v0.8 lattice, ready to track.

  Derived from mucoll_mdi_lattice_v0p8.gdml by gdml/mucoll_ip_extract.py:
  the MDI assembly (both nozzles with their borated liners, the beryllium
  beam chamber, the beam-pipe vacuum and the detector cavern) translated by
  (0, +30 m, -85 m) so the interaction point is at the origin, in a world
  sized to it. Solids and materials are otherwise untouched.

  Beam axis: z. Interaction point: (0, 0, 0). Regenerate with
      python3 gdml/mucoll_ip_extract.py
"""


def _tag(el):
    return el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag


def _solid_refs(el, solids, seen):
    """Every solid name reachable from `el` (booleans nest arbitrarily deep)."""
    for sub in el.iter():
        t = _tag(sub)
        if t in ("first", "second", "solid", "solidref"):
            name = sub.get("ref")
            if name and name not in seen and name in solids:
                seen.add(name)
                _solid_refs(solids[name], solids, seen)
    return seen


def main():
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    solids_el = root.find("solids")
    structure = root.find("structure")
    solids = {s.get("name"): s for s in solids_el}
    volumes = {v.get("name"): v for v in structure if _tag(v) == "volume"}
    world_name = root.find("setup").find("world").get("ref")
    world = volumes[world_name]

    # 1 + 2: keep the MDI placements, shifted so the IP is the origin
    kept_lvs = []
    for pv in list(world.findall("physvol")):
        if pv.get("name") not in KEEP:
            world.remove(pv)
            continue
        kept_lvs.append(pv.find("volumeref").get("ref"))
        pos = pv.find("position")
        if pos is None:
            pos = ET.SubElement(pv, "position")
            pos.set("name", f"{pv.get('name')}_pos")
            old = (0.0, 0.0, 0.0)
        else:
            assert pos.get("unit", "mm") == "mm", pos.get("unit")
            old = tuple(float(pos.get(a, 0.0)) for a in "xyz")
        pos.set("unit", "mm")
        for axis, was, ip in zip("xyz", old, IP_MM):
            pos.set(axis, repr(was - ip))
    missing = KEEP - {pv.get("name") for pv in world.findall("physvol")}
    if missing:
        raise SystemExit(f"{SOURCE.name}: placements not found: {sorted(missing)}")

    # 3: a world that fits what is left
    wsolid = solids[world.find("solidref").get("ref")]
    for axis, half in zip("xyz", WORLD_HALF):
        wsolid.set(axis, repr(2.0 * half))
    wsolid.set("lunit", "mm")

    # 4: drop every volume and solid nothing references any more
    for name, vol in list(volumes.items()):
        if name != world_name and name not in kept_lvs:
            structure.remove(vol)
    live = {wsolid.get("name")}
    _solid_refs(wsolid, solids, live)
    for name in kept_lvs:
        sref = volumes[name].find("solidref").get("ref")
        live.add(sref)
        _solid_refs(solids[sref], solids, live)
    for s in list(solids_el):
        if s.get("name") not in live:
            solids_el.remove(s)

    ET.indent(tree, space="\t")
    root.insert(0, ET.Comment(PROVENANCE))
    tree.write(OUTPUT, encoding="unicode", xml_declaration=True)
    with open(OUTPUT, "a") as f:
        f.write("\n")
    print(f"{OUTPUT.relative_to(Path.cwd()) if OUTPUT.is_relative_to(Path.cwd()) else OUTPUT}: "
          f"{len(kept_lvs)} volume(s), {len(live)} solid(s), "
          f"{OUTPUT.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    main()
