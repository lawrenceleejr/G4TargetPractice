#include "G4UImessenger.hh"
#include "G4UIcmdWithAString.hh"
#include "G4UIcmdWith3VectorAndUnit.hh"

class DetectorConstruction;

class DetectorMessenger : public G4UImessenger {
public:
    DetectorMessenger(DetectorConstruction*);
    ~DetectorMessenger();

    virtual void SetNewValue(G4UIcommand*, G4String);

private:
    DetectorConstruction* fDetector;

    G4UIcmdWithAString* fReadGDMLCmd;
    G4UIcmdWith3VectorAndUnit* fGlobalFieldCmd;
    G4UIcmdWithAString* fTargetRegionCmd;
    G4UIcmdWithAString* fOscRegionCmd;
};
