#include "DetectorConstruction.hh"
#include "DetectorMessenger.hh"

#include "G4Exception.hh"
#include "G4RunManager.hh"
#include "G4GDMLParser.hh"
#include "G4SystemOfUnits.hh"
#include "G4Region.hh"
#include "G4RegionStore.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4UserLimits.hh"
#include "G4NistManager.hh"
#include "G4UniformMagField.hh"
#include "G4FieldManager.hh"
#include "G4TransportationManager.hh"
#include "G4Box.hh"
#include "G4LogicalVolume.hh"
#include "G4PVPlacement.hh"
#include "G4ThreeVector.hh"


DetectorConstruction::DetectorConstruction()
{
    fMessenger = new DetectorMessenger(this);

    // Build a minimal air-filled world so Construct() always has a valid
    // world volume even before any GDML file is loaded via /detector/readGDML.
    G4Material* air = G4NistManager::Instance()->FindOrBuildMaterial("G4_AIR");
    G4Box*           worldSolid = new G4Box("DefaultWorld", 5.*m, 5.*m, 5.*m);
    G4LogicalVolume* worldLV    = new G4LogicalVolume(worldSolid, air, "DefaultWorld");
    fWorld = new G4PVPlacement(nullptr, G4ThreeVector(), worldLV,
                               "DefaultWorld", nullptr, false, 0);

    G4cout << "DetectorConstruction: default stub world created. "
           << "Use /detector/readGDML <file> in your macro to load a geometry."
           << G4endl;
}

DetectorConstruction::~DetectorConstruction()
{
    delete fMessenger;
}

// Allows macro-based GDML reloading
void DetectorConstruction::ReadGDML(const G4String& filename)
{
    G4cout << "Reading GDML file: " << filename << G4endl;

    fParser.Read(filename, false);  // false disables schema validation

    fWorld = fParser.GetWorldVolume();
    if (!fWorld) {
        G4cerr << "GDML read, but world volume is NULL!" << G4endl;
        G4cerr << "Check that your GDML defines a <world> and all solids/materials." << G4endl;

        G4Exception("DetectorConstruction::ReadGDML",
                    "NoGDML",
                    FatalException,
                    "World volume is NULL after reading GDML.");
    }

    G4cout << "GDML loaded successfully. World volume: "
           << fWorld->GetName() << G4endl;

    // Reinitialize geometry after macro reload
    G4RunManager::GetRunManager()->ReinitializeGeometry();
}

// Set (or clear, with a zero vector) a uniform magnetic field over the
// whole geometry, e.g. a solenoid channel along z for muon capture.
void DetectorConstruction::SetGlobalField(const G4ThreeVector& fieldValue)
{
    auto* fieldMgr =
        G4TransportationManager::GetTransportationManager()->GetFieldManager();

    G4MagneticField* oldField = fGlobalField;
    if (fieldValue.mag2() > 0.) {
        fGlobalField = new G4UniformMagField(fieldValue);
        fieldMgr->SetDetectorField(fGlobalField);
        fieldMgr->CreateChordFinder(static_cast<G4MagneticField*>(fGlobalField));
        G4cout << "Global uniform magnetic field set: "
               << fieldValue / tesla << " T" << G4endl;
#ifdef USE_CELERITAS
        G4cout << "WARNING: the Celeritas offload in this build assumes zero "
                  "magnetic field for e-/e+/gamma transport.\n"
                  "Set CELER_DISABLE=1 when running with a field." << G4endl;
#endif
    } else {
        fGlobalField = nullptr;
        fieldMgr->SetDetectorField(nullptr);
        G4cout << "Global magnetic field disabled." << G4endl;
    }
    delete oldField;
}

G4VPhysicalVolume* DetectorConstruction::Construct()
{
    if (!fWorld) {
        G4Exception("DetectorConstruction::Construct()",
                    "NoGDML",
                    FatalException,
                    "World volume is NULL. Call /detector/readGDML before /run/initialize.");
    }

    G4LogicalVolume* worldLogical = fWorld->GetLogicalVolume();
    if (worldLogical) {
             G4double minStep = 1.0*mm;  // you can reduce if needed
      G4UserLimits* stepLimits = new G4UserLimits(minStep);
      worldLogical->SetUserLimits(stepLimits);
      G4double maxStep = 10*cm;  // limit max step to 10 cm
      worldLogical->SetUserLimits(new G4UserLimits(maxStep));
 
      G4cout << "Minimum step size set for world: " << minStep/mm << " mm" << G4endl;
    } else {
        G4cerr << "World logical volume not found!" << G4endl;
    }
    

    // -----------------------------------------------------------------
    // Neutrino physics regions.
    //
    // Geant4's G4NeutrinoPhysics applies its cross-section bias only inside
    // the G4Region named by /physics_lists/nu/NuDetectorName, and measures
    // oscillation distance in the region named by NuOscDistanceName. The name
    // is matched against a REGION, not a logical volume -- verified by
    // experiment: with NuDetectorName=DefaultRegionForTheWorld a 40 GeV nu_mu
    // at NuNucleusBias 1e12 interacted in 100/100 events (62 CC / 38 NC),
    // while the same run naming an EMPTY region gave 0/100.
    //
    // This used to add only volumes whose name contained "_sens", so for every
    // shipped geometry (LAr_vol, MAIA_*, ...) the "target" region came out
    // EMPTY and neutrino biasing silently did nothing. Default now: every
    // non-world volume joins "target". Narrow it with
    // /detector/targetRegionPattern, and opt into a separate oscillation
    // region with /detector/oscRegionPattern.
    // -----------------------------------------------------------------
    auto regionStore = G4RegionStore::GetInstance();
    // FindOrCreate, not new: Construct() runs again on /run/reinitializeGeometry
    // and a second G4Region with the same name would only warn and be ignored.
    auto targetRegion = regionStore->FindOrCreateRegion("target");
    // The oscillation region is created only when asked for: G4RunManagerKernel
    // complains about a region with no root logical volume.
    G4Region* oscRegion = fOscRegionPattern.empty()
                          ? nullptr
                          : regionStore->FindOrCreateRegion("tgtosc");

    auto lvStore = G4LogicalVolumeStore::GetInstance();
    G4int nTarget = 0, nOsc = 0;

    G4cout << "\n=== Assigning neutrino regions ===" << G4endl;
    for (auto lv : *lvStore) {
        if (lv == worldLogical) continue;              // never bias the world

        // Oscillation region wins when its pattern is set and matches, so a
        // volume is never in both (G4Region membership is exclusive).
        if (oscRegion &&
            lv->GetName().find(fOscRegionPattern) != std::string::npos) {
            oscRegion->AddRootLogicalVolume(lv);
            ++nOsc;
            G4cout << ">>> tgtosc (oscillation): " << lv->GetName() << G4endl;
            continue;
        }
        if (fTargetRegionPattern.empty() ||
            lv->GetName().find(fTargetRegionPattern) != std::string::npos) {
            targetRegion->AddRootLogicalVolume(lv);
            ++nTarget;
        }
    }
    G4cout << "target region: " << nTarget << " volume(s)"
           << (fTargetRegionPattern.empty()
               ? G4String(" (all non-world)")
               : G4String(" matching \"" + fTargetRegionPattern + "\""))
           << "; tgtosc region: " << nOsc << " volume(s)" << G4endl;
    if (nTarget == 0) {
        G4cout << "*** WARNING: the \"target\" region is EMPTY -- "
               << "/physics_lists/nu/NuDetectorName target will bias NOTHING "
               << "and no neutrino will interact. Check "
               << "/detector/targetRegionPattern." << G4endl;
    }
    G4cout << "===============================\n" << G4endl;

    return fWorld;
}
