#include "NeutrinoBiasMessenger.hh"

#include "G4UIdirectory.hh"
#include "G4UImanager.hh"
#include "G4UIcommandTree.hh"
#include "G4UIcommand.hh"
#include "G4UIparameter.hh"
#include "G4SystemOfUnits.hh"

#include <sstream>

NeutrinoBiasMessenger::NeutrinoBiasMessenger(NeutrinoPhysics* nuPhysics)
    : fNuPhysics(nuPhysics)
{
    auto* top = new G4UIdirectory("/gdmltp/");
    top->SetGuidance("GDMLTargetPractice engine controls.");
    fDirs.push_back(top);

    auto* nuDir = new G4UIdirectory("/gdmltp/nu/");
    nuDir->SetGuidance(
        "Every biasing term Geant4's neutrino processes expose, one command per "
        "term. All PreInit-only. Run /gdmltp/nu/list to see resolved values.");
    fDirs.push_back(nuDir);

    fListCmd = new G4UIcommand("/gdmltp/nu/list", this);
    fListCmd->SetGuidance("Print the resolved neutrino biasing knobs.");
    fListCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    // The four interaction families are independent process objects in Geant4,
    // so each gets its own group; the last two are convenience aliases.
    AddGroup("electron",   tElectron,   "neutrino-electron scattering");
    AddGroup("nucleusE",   tNucleusE,   "nu_e / anti-nu_e on nuclei");
    AddGroup("nucleusMu",  tNucleusMu,  "nu_mu / anti-nu_mu on nuclei");
    AddGroup("nucleusTau", tNucleusTau, "nu_tau / anti-nu_tau on nuclei");
    AddGroup("nucleus",    tNucleus,    "all three neutrino-nucleus families at once");
    AddGroup("all",        tAll,        "all four interaction families at once");

    auto* oscDir = new G4UIdirectory("/gdmltp/nu/oscillation/");
    oscDir->SetGuidance(
        "Geant4's vacuum-oscillation process (G4NuVacOscProcess). Geant4 "
        "enables it by DEFAULT and offers no /physics_lists/nu/ command to "
        "switch it off -- these do.");
    fDirs.push_back(oscDir);
    Add("/gdmltp/nu/oscillation/enable", kEnable, tOsc, 'b',
        "Register the vacuum-oscillation process at all (default: true).");
    Add("/gdmltp/nu/oscillation/region", kRegion, tOsc, 's',
        "G4Region in which distanceBias shortens the oscillation length. "
        "Default \"0\" matches nothing, i.e. unbiased oscillation everywhere.");
    Add("/gdmltp/nu/oscillation/distanceBias", kMfpBias, tOsc, 'd',
        "Divide the oscillation length by this inside `region`, so flavour "
        "change happens over a short baseline. Geant4 IGNORES values <= 1.");
    Add("/gdmltp/nu/oscillation/lowestEnergy", kLowestEnergy, tOsc, 'e',
        "Below this kinetic energy the oscillation process does nothing "
        "(Geant4 default 1 eV).");

    // ---- composite shortcuts (kept: they are what most macros want) -------
    fBiasCmd = new G4UIcommand("/gdmltp/neutrinoBias", this);
    fBiasCmd->SetGuidance(
        "Shortcut for the common 'make the neutrino interact in the target' "
        "case. Args: ccBias ncBias nucleusBias [region]. Sets the "
        "nu-electron cc/nc pair, the mean-free-path bias of all three "
        "nu-nucleus families to nucleusBias, and the region of all four "
        "families. Use the /gdmltp/nu/<group>/ commands for finer control.");
    for (const char* name : {"ccBias", "ncBias", "nucleusBias"}) {
        auto* p = new G4UIparameter(name, 'd', false);
        const std::string range = std::string(name) + " >= 1.";
        p->SetParameterRange(range.c_str());
        fBiasCmd->SetParameter(p);
    }
    fBiasCmd->SetParameter(new G4UIparameter("region", 's', true));
    fBiasCmd->AvailableForStates(G4State_PreInit);

    fOscCmd = new G4UIcommand("/gdmltp/neutrinoOscillation", this);
    fOscCmd->SetGuidance(
        "Shortcut: enable regionName distanceBias -- the same three knobs as "
        "/gdmltp/nu/oscillation/{enable,region,distanceBias}.");
    fOscCmd->SetParameter(new G4UIparameter("enable", 'b', false));
    auto* orn = new G4UIparameter("regionName", 's', true);
    orn->SetDefaultValue("0");
    fOscCmd->SetParameter(orn);
    auto* db = new G4UIparameter("distanceBias", 'd', true);
    db->SetParameterRange("distanceBias > 0.");
    db->SetDefaultValue(1.0);
    fOscCmd->SetParameter(db);
    fOscCmd->AvailableForStates(G4State_PreInit);

    // ---- upstream /physics_lists/nu/ compatibility -------------------------
    // g4sim registers NeutrinoPhysics instead of G4NeutrinoPhysics, so the
    // upstream messenger does not exist and macros using its commands would
    // abort ("command not found" is fatal in batch mode regardless of
    // /control/suppressAbortion). Re-register the same eight paths here and
    // translate them. Skipped if something else already owns them.
    auto* tree = G4UImanager::GetUIpointer()->GetTree();
    if (tree == nullptr || tree->FindPath("/physics_lists/nu/NuDetectorName") == nullptr) {
        auto* plDir = new G4UIdirectory("/physics_lists/nu/");
        plDir->SetGuidance(
            "Compatibility layer for macros written against Geant4's own "
            "G4NeutrinoPhysics. Translated onto /gdmltp/nu/ -- see "
            "/control/manual /gdmltp/nu for the full knob set.");
        fDirs.push_back(plDir);
        struct Up { const char* path; char type; const char* help; };
        const Up ups[] = {
            {"/physics_lists/nu/NeutrinoActivation", 'b',
             "Enable the neutrino-nucleus processes. NOTE: upstream Geant4 "
             "registers this command but its messenger ignores it -- here it "
             "really does switch the three nucleus families on/off."},
            {"/physics_lists/nu/NuETotXscActivation", 'b',
             "Upstream this gates the nucleus bias AND collapses "
             "NuEleCcBias/NuEleNcBias into one max(cc,nc) factor. Here both "
             "apply independently, so this command is accepted and reported "
             "but changes nothing."},
            {"/physics_lists/nu/NuEleCcBias", 'd',
             "-> /gdmltp/nu/electron/ccBias"},
            {"/physics_lists/nu/NuEleNcBias", 'd',
             "-> /gdmltp/nu/electron/ncBias"},
            {"/physics_lists/nu/NuNucleusBias", 'd',
             "-> /gdmltp/nu/nucleus/mfpBias (all three flavours at once; use "
             "/gdmltp/nu/nucleusMu/mfpBias etc. for one flavour)"},
            {"/physics_lists/nu/NuOscDistanceBias", 'd',
             "-> /gdmltp/nu/oscillation/distanceBias"},
            {"/physics_lists/nu/NuDetectorName", 's',
             "-> /gdmltp/nu/all/region (a G4Region name)"},
            {"/physics_lists/nu/NuOscDistanceName", 's',
             "-> /gdmltp/nu/oscillation/region (a G4Region name)"},
        };
        for (const auto& u : ups) {
            auto* cmd = new G4UIcommand(u.path, this);
            cmd->SetGuidance(u.help);
            cmd->SetParameter(new G4UIparameter("value", u.type, false));
            cmd->AvailableForStates(G4State_PreInit);
            fUpstream.push_back(cmd);
        }
    }
}

void NeutrinoBiasMessenger::AddGroup(const G4String& group, G4int targets,
                                     const G4String& what)
{
    const G4String base = "/gdmltp/nu/" + group + "/";
    auto* dir = new G4UIdirectory(base);
    const G4String dirGuidance = "Biasing terms for " + what + ".";
    dir->SetGuidance(dirGuidance.c_str());
    fDirs.push_back(dir);

    Add(base + "enable", kEnable, targets, 'b',
        "Register this process family at all (default: true).");
    Add(base + "region", kRegion, targets, 's',
        "G4Region NAME (not a logical-volume name) the process is confined to: "
        "outside it the process never interacts. g4sim builds a region called "
        "\"target\" from every non-world volume; the Geant4-wide default is "
        "\"DefaultRegionForTheWorld\".");
    Add(base + "mfpBias", kMfpBias, targets, 'd',
        "Scale the mean free path inside `region` (G4*Process::"
        "SetBiasingFactor). The 'guarantee an interaction here' knob. Geant4 "
        "IGNORES values <= 1, and it does not change the tabulated cross "
        "section -- only how often the process fires in that region.");
    Add(base + "ccBias", kCcBias, targets, 'd',
        "Charged-current bias (G4*Process::SetBiasingFactors). Two effects: the "
        "process factor becomes max(cc, nc), and cc > 1 also makes the vertex be "
        "sampled UNIFORMLY along the chord through the volume. It does NOT "
        "reweight CC against NC -- the CC fraction comes from the physics. For "
        "the electron family, xsecCcBias/xsecNcBias do reweight it.");
    Add(base + "ncBias", kNcBias, targets, 'd',
        "Neutral-current counterpart of ccBias -- same two effects.");
    Add(base + "xsecBias", kXsecBias, targets, 'd',
        "Scale the tabulated total cross section itself (the TotXsc data set's "
        "SetBiasingFactor), in EVERY region. Independent of mfpBias; "
        "G4NeutrinoPhysics never sets this one. On the electron family this can "
        "abort Geant4 -- see the guidance for /gdmltp/nu/electron/xsecCcBias.");
    Add(base + "lowestEnergy", kLowestEnergy, targets, 'e',
        "Below this kinetic energy the process does nothing (Geant4 default "
        "1 keV).");

    // Only G4NeutrinoElectronTotXsc has separate CC and NC cross-section
    // objects, so these two exist only where they mean something.
    if ((targets & tElectron) == 0) return;
    const G4String warn =
        " DANGER: G4NeutrinoElectronTotXsc implements no isotope-level cross "
        "section, so a bias large enough to make nu+e- actually interact aborts "
        "Geant4 in G4CrossSectionDataStore::GetIsoCrossSection. Bias nu+e- via "
        "mfpBias or ccBias/ncBias instead unless you specifically want to "
        "reweight the CC/NC ratio.";
    Add(base + "xsecCcBias", kXsecCcBias, tElectron, 'd',
        "Scale the CC nu-electron cross section (G4NeutrinoElectronTotXsc::"
        "SetBiasingFactors). The ONLY term in Geant4 that genuinely changes a "
        "CC/NC ratio." + warn);
    Add(base + "xsecNcBias", kXsecNcBias, tElectron, 'd',
        "NC counterpart of xsecCcBias." + warn);
}

G4UIcommand* NeutrinoBiasMessenger::Add(const G4String& path, Knob knob,
                                        G4int targets, char type,
                                        const G4String& guidance)
{
    auto* cmd = new G4UIcommand(path, this);
    cmd->SetGuidance(guidance.c_str());
    if (type == 'e') {
        // dimensioned: value + unit, so "/... lowestEnergy 10 MeV" works
        cmd->SetParameter(new G4UIparameter("value", 'd', false));
        auto* u = new G4UIparameter("unit", 's', true);
        u->SetDefaultValue("MeV");
        cmd->SetParameter(u);
    } else {
        cmd->SetParameter(new G4UIparameter("value", type, false));
    }
    cmd->AvailableForStates(G4State_PreInit);
    fEntries.push_back({cmd, targets, knob});
    return cmd;
}

NeutrinoBiasMessenger::~NeutrinoBiasMessenger()
{
    for (auto& e : fEntries) delete e.cmd;
    for (auto* c : fUpstream) delete c;
    delete fListCmd;
    delete fBiasCmd;
    delete fOscCmd;
    for (auto* d : fDirs) delete d;
}

void NeutrinoBiasMessenger::Apply(const Entry& e, const G4String& value)
{
    for (G4int i = 0; i <= NeutrinoPhysics::kNFamilies; ++i) {
        if (!(e.targets & (1 << i))) continue;
        NeutrinoPhysics::Knobs& k =
            (i == NeutrinoPhysics::kNFamilies)
                ? fNuPhysics->Oscillation()
                : fNuPhysics->Get(static_cast<NeutrinoPhysics::Family>(i));
        switch (e.knob) {
            case kEnable:
                k.enable = G4UIcommand::ConvertToBool(value.c_str());
                break;
            case kRegion:
                k.region = value;
                break;
            case kMfpBias: {
                const G4double v = G4UIcommand::ConvertToDouble(value.c_str());
                if (v <= 1.0) {
                    G4cout << "*** WARNING: " << e.cmd->GetCommandPath()
                           << " " << v << " has NO effect -- Geant4 applies this "
                           << "bias only for values > 1." << G4endl;
                }
                k.mfpBias = v;
                break;
            }
            case kCcBias:
                k.ccBias = G4UIcommand::ConvertToDouble(value.c_str());
                break;
            case kNcBias:
                k.ncBias = G4UIcommand::ConvertToDouble(value.c_str());
                break;
            case kXsecBias:
                k.xsecBias = G4UIcommand::ConvertToDouble(value.c_str());
                break;
            case kXsecCcBias:
                k.xsecCcBias = G4UIcommand::ConvertToDouble(value.c_str());
                break;
            case kXsecNcBias:
                k.xsecNcBias = G4UIcommand::ConvertToDouble(value.c_str());
                break;
            case kLowestEnergy:
                k.lowestEnergy =
                    G4UIcommand::ConvertToDimensionedDouble(value.c_str());
                break;
        }
    }
}

void NeutrinoBiasMessenger::SetNewValue(G4UIcommand* command, G4String newValue)
{
    if (fNuPhysics == nullptr) return;
    if (command == fListCmd)  { fNuPhysics->Print(); return; }
    if (command == fBiasCmd)  { SetCompositeBias(newValue); return; }
    if (command == fOscCmd)   { SetCompositeOscillation(newValue); return; }
    for (const auto& e : fEntries) {
        if (e.cmd == command) { Apply(e, newValue); return; }
    }
    SetUpstreamValue(command, newValue);
}

G4bool NeutrinoBiasMessenger::SetUpstreamValue(G4UIcommand* cmd,
                                              const G4String& value)
{
    if (fUpstream.size() != 8) return false;
    const G4String path = cmd->GetCommandPath();
    auto& ele  = fNuPhysics->Get(NeutrinoPhysics::kElectron);
    const NeutrinoPhysics::Family nucl[3] = {
        NeutrinoPhysics::kNucleusE, NeutrinoPhysics::kNucleusMu,
        NeutrinoPhysics::kNucleusTau};

    if (path == "/physics_lists/nu/NeutrinoActivation") {
        const G4bool on = G4UIcommand::ConvertToBool(value.c_str());
        for (auto f : nucl) fNuPhysics->Get(f).enable = on;
    } else if (path == "/physics_lists/nu/NuETotXscActivation") {
        G4cout << "NuETotXscActivation " << value << ": accepted for macro "
               << "compatibility. In g4sim the nu-electron CC/NC pair and the "
               << "nu-nucleus bias apply independently, so nothing is gated on "
               << "it -- see /gdmltp/nu/ for the individual terms." << G4endl;
    } else if (path == "/physics_lists/nu/NuEleCcBias") {
        ele.ccBias = G4UIcommand::ConvertToDouble(value.c_str());
    } else if (path == "/physics_lists/nu/NuEleNcBias") {
        ele.ncBias = G4UIcommand::ConvertToDouble(value.c_str());
    } else if (path == "/physics_lists/nu/NuNucleusBias") {
        const G4double bf = G4UIcommand::ConvertToDouble(value.c_str());
        // mfpBias, not cc/nc: upstream's NuNucleusBias ends up in the process's
        // total factor, which is exactly what mfpBias sets.
        for (auto f : nucl) fNuPhysics->Get(f).mfpBias = bf;
    } else if (path == "/physics_lists/nu/NuOscDistanceBias") {
        fNuPhysics->Oscillation().mfpBias =
            G4UIcommand::ConvertToDouble(value.c_str());
    } else if (path == "/physics_lists/nu/NuDetectorName") {
        ele.region = value;
        for (auto f : nucl) fNuPhysics->Get(f).region = value;
    } else if (path == "/physics_lists/nu/NuOscDistanceName") {
        fNuPhysics->Oscillation().region = value;
    } else {
        return false;
    }
    return true;
}

void NeutrinoBiasMessenger::SetCompositeBias(const G4String& newValue)
{
    std::istringstream iss(newValue);
    G4double cc = 1.0, nc = 1.0, nuc = 1.0;
    G4String region = "DefaultRegionForTheWorld";
    iss >> cc >> nc >> nuc;
    if (iss >> region) { /* optional region token consumed */ }

    // nu-electron: the PROCESS cc/nc pair only. Deliberately not the
    // cross-section table (xsecCc/NcBias): that route makes nu+e- interact and
    // then aborts Geant4, because G4NeutrinoElectronTotXsc has no isotope-level
    // cross section. This shortcut must stay safe at any factor.
    auto& ele = fNuPhysics->Get(NeutrinoPhysics::kElectron);
    ele.ccBias = cc;
    ele.ncBias = nc;
    ele.region = region;
    // nu-nucleus: one mean-free-path bias per flavour. mfpBias, not cc/nc:
    // for the nucleus families cc/nc would only take max() and additionally
    // spread the vertex, while mfpBias is the term that makes the interaction
    // happen at all.
    for (auto f : {NeutrinoPhysics::kNucleusE, NeutrinoPhysics::kNucleusMu,
                   NeutrinoPhysics::kNucleusTau}) {
        auto& k = fNuPhysics->Get(f);
        k.mfpBias = nuc;
        k.region = region;
    }
    G4cout << "NeutrinoBiasMessenger: nu-e CC=" << cc << " NC=" << nc
           << ", nu-nucleus mean-free-path bias=" << nuc
           << ", region '" << region << "'." << G4endl;
}

void NeutrinoBiasMessenger::SetCompositeOscillation(const G4String& newValue)
{
    std::istringstream iss(newValue);
    G4String enable;
    G4String region = "0";      // G4NeutrinoPhysics' own "matches nothing" default
    G4double bias = 1.0;
    iss >> enable;
    const G4bool on = G4UIcommand::ConvertToBool(enable.c_str());
    if (iss >> region) { /* optional */ }
    if (!(iss >> bias)) bias = 1.0;

    auto& osc = fNuPhysics->Oscillation();
    osc.enable = on;
    osc.region = region;
    osc.mfpBias = bias;
    G4cout << "NeutrinoBiasMessenger: vacuum oscillation "
           << (on ? "ENABLED" : "disabled") << ", region '" << region
           << "', distance bias " << bias << "." << G4endl;
}
