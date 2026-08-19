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

private:
    G4GDMLParser       fParser;
    G4VPhysicalVolume* fWorld = nullptr;
    DetectorMessenger* fMessenger;
    G4MagneticField*   fGlobalField = nullptr;
};

#endif
