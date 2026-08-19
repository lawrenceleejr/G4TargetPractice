#ifndef NeutrinoBiasMessenger_h
#define NeutrinoBiasMessenger_h 1

#include "G4UImessenger.hh"
#include "NeutrinoPhysics.hh"
#include "globals.hh"

#include <vector>

class G4UIdirectory;
class G4UIcommand;

/// UI surface for every biasing term Geant4's neutrino processes expose, one
/// command per term (see NeutrinoPhysics.hh for what each term actually does).
/// All commands are PreInit-only: the knobs are read in
/// NeutrinoPhysics::ConstructProcess(), i.e. at /run/initialize.
///
///   /gdmltp/nu/list                        print the resolved knob table
///   /gdmltp/nu/<group>/enable       <bool>
///   /gdmltp/nu/<group>/region       <G4Region name>
///   /gdmltp/nu/<group>/mfpBias      <double>   (needs > 1 to do anything)
///   /gdmltp/nu/<group>/ccBias       <double>
///   /gdmltp/nu/<group>/ncBias       <double>
///   /gdmltp/nu/<group>/xsecBias     <double>
///   /gdmltp/nu/<group>/lowestEnergy <double> <unit>
///
/// <group> is one of: electron, nucleusE, nucleusMu, nucleusTau (the four
/// independent process objects), nucleus (the three nucleus families at once),
/// or all (all four). Oscillation has its own directory:
///
///   /gdmltp/nu/oscillation/enable        <bool>
///   /gdmltp/nu/oscillation/region        <G4Region name>
///   /gdmltp/nu/oscillation/distanceBias  <double>   (needs > 1)
///   /gdmltp/nu/oscillation/lowestEnergy  <double> <unit>
///
/// For macros written against upstream G4NeutrinoPhysics, the eight
/// /physics_lists/nu/ commands are also accepted and translated onto the knobs
/// above (see SetUpstreamValue) -- g4sim no longer registers G4NeutrinoPhysics
/// itself, so without this layer those macros would abort on an unknown command.
///
/// Two composite shortcuts remain for the common "just make the neutrino
/// interact somewhere in the target" case:
///
///   /gdmltp/neutrinoBias <ccBias> <ncBias> <nucleusBias> [region]
///   /gdmltp/neutrinoOscillation <enable> [region] [distanceBias]
class NeutrinoBiasMessenger : public G4UImessenger {
public:
    explicit NeutrinoBiasMessenger(NeutrinoPhysics* nuPhysics);
    ~NeutrinoBiasMessenger() override;
    void SetNewValue(G4UIcommand* command, G4String newValue) override;

private:
    /// Which knob a command writes.
    enum Knob { kEnable, kRegion, kMfpBias, kCcBias, kNcBias, kXsecBias, kLowestEnergy };

    /// Bit per target: the four interaction families plus oscillation.
    enum Target {
        tElectron   = 1 << NeutrinoPhysics::kElectron,
        tNucleusE   = 1 << NeutrinoPhysics::kNucleusE,
        tNucleusMu  = 1 << NeutrinoPhysics::kNucleusMu,
        tNucleusTau = 1 << NeutrinoPhysics::kNucleusTau,
        tNucleus    = tNucleusE | tNucleusMu | tNucleusTau,
        tAll        = tElectron | tNucleus,
        tOsc        = 1 << NeutrinoPhysics::kNFamilies
    };

    struct Entry {
        G4UIcommand* cmd;
        G4int        targets;   // bitmask of Target
        Knob         knob;
    };

    void AddGroup(const G4String& group, G4int targets, const G4String& what);
    G4UIcommand* Add(const G4String& path, Knob knob, G4int targets,
                     char type, const G4String& guidance);
    void Apply(const Entry& e, const G4String& value);

    // the two legacy composites
    void SetCompositeBias(const G4String& value);
    void SetCompositeOscillation(const G4String& value);
    /// Translate one /physics_lists/nu/ command; returns false if `cmd` is not
    /// one of them.
    G4bool SetUpstreamValue(G4UIcommand* cmd, const G4String& value);

    NeutrinoPhysics*          fNuPhysics;
    std::vector<G4UIdirectory*> fDirs;
    std::vector<Entry>        fEntries;
    G4UIcommand*              fListCmd = nullptr;
    G4UIcommand*              fBiasCmd = nullptr;
    G4UIcommand*              fOscCmd = nullptr;
    // upstream /physics_lists/nu/ compatibility layer, in declaration order:
    // NeutrinoActivation, NuETotXscActivation, NuEleCcBias, NuEleNcBias,
    // NuNucleusBias, NuOscDistanceBias, NuDetectorName, NuOscDistanceName
    std::vector<G4UIcommand*>  fUpstream;
};

#endif
