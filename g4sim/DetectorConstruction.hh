#ifndef DetectorConstruction_h
#define DetectorConstruction_h 1

#include "G4VUserDetectorConstruction.hh"
#include "G4GDMLParser.hh"
#include "G4VPhysicalVolume.hh"
#include "G4MagneticField.hh"
#include "G4ThreeVector.hh"

class DetectorMessenger;   // Forward declaration

class DetectorConstruction : public G4VUserDetectorConstruction {
public:
    DetectorConstruction();
    virtual ~DetectorConstruction();

    virtual G4VPhysicalVolume* Construct();

    void ReadGDML(const G4String& filename);
    void SetGlobalField(const G4ThreeVector& fieldValue);

    // Which logical volumes join the neutrino regions (substring match on the
    // volume name). Empty target pattern = every non-world volume, which is
    // what makes /physics_lists/nu/NuDetectorName target work out of the box.
    // Empty osc pattern = no oscillation region.
    void SetTargetRegionPattern(const G4String& p) { fTargetRegionPattern = p; }
    void SetOscRegionPattern(const G4String& p)    { fOscRegionPattern = p; }

private:
    G4GDMLParser       fParser;
    G4VPhysicalVolume* fWorld = nullptr;
    G4String fTargetRegionPattern = "";   // "" = all non-world volumes
    G4String fOscRegionPattern = "";      // "" = no oscillation region
    DetectorMessenger* fMessenger;
    G4MagneticField*   fGlobalField = nullptr;
};

#endif
