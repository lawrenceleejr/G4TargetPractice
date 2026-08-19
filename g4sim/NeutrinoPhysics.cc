#include "NeutrinoPhysics.hh"

#include "G4SystemOfUnits.hh"
#include "G4ParticleDefinition.hh"
#include "G4ProcessManager.hh"

#include "G4Electron.hh"
#include "G4AntiNeutrinoE.hh"
#include "G4NeutrinoE.hh"
#include "G4AntiNeutrinoMu.hh"
#include "G4NeutrinoMu.hh"
#include "G4AntiNeutrinoTau.hh"
#include "G4NeutrinoTau.hh"

#include "G4NeutrinoElectronProcess.hh"
#include "G4NeutrinoElectronTotXsc.hh"
#include "G4NeutrinoElectronCcModel.hh"
#include "G4NeutrinoElectronNcModel.hh"

#include "G4MuNeutrinoNucleusProcess.hh"
#include "G4TauNeutrinoNucleusProcess.hh"
#include "G4ElNeutrinoNucleusProcess.hh"
#include "G4NuVacOscProcess.hh"

#include "G4MuNeutrinoNucleusTotXsc.hh"
#include "G4TauNeutrinoNucleusTotXsc.hh"
#include "G4ElNeutrinoNucleusTotXsc.hh"

#include "G4NuMuNucleusCcModel.hh"
#include "G4NuMuNucleusNcModel.hh"
#include "G4ANuMuNucleusCcModel.hh"
#include "G4ANuMuNucleusNcModel.hh"

#include "G4NuTauNucleusCcModel.hh"
#include "G4NuTauNucleusNcModel.hh"
#include "G4ANuTauNucleusCcModel.hh"
#include "G4ANuTauNucleusNcModel.hh"

#include "G4NuElNucleusCcModel.hh"
#include "G4NuElNucleusNcModel.hh"
#include "G4ANuElNucleusCcModel.hh"
#include "G4ANuElNucleusNcModel.hh"

#include <iomanip>

NeutrinoPhysics::NeutrinoPhysics(G4int ver)
    : G4VPhysicsConstructor("NeutrinoPhys"), fVerbose(ver)
{
    // G4NuVacOscProcess treats its envelope name purely as "the region in which
    // the oscillation length is divided by the bias factor". "0" is the sentinel
    // G4NeutrinoPhysics uses: it matches no real region, so oscillation runs
    // unbiased everywhere -- which is the physical default.
    fOsc.region = "0";
}

const char* NeutrinoPhysics::FamilyName(Family f)
{
    switch (f) {
        case kElectron:   return "nu+e- (G4NeutrinoElectronProcess)";
        case kNucleusE:   return "nu_e+A (G4ElNeutrinoNucleusProcess)";
        case kNucleusMu:  return "nu_mu+A (G4MuNeutrinoNucleusProcess)";
        case kNucleusTau: return "nu_tau+A (G4TauNeutrinoNucleusProcess)";
        default:          return "?";
    }
}

void NeutrinoPhysics::ConstructParticle()
{
    G4Electron::Electron();
    G4AntiNeutrinoE::AntiNeutrinoE();
    G4NeutrinoE::NeutrinoE();
    G4AntiNeutrinoMu::AntiNeutrinoMu();
    G4NeutrinoMu::NeutrinoMu();
    G4AntiNeutrinoTau::AntiNeutrinoTau();
    G4NeutrinoTau::NeutrinoTau();
}

void NeutrinoPhysics::Print() const
{
    G4cout << "\n=== Geant4 neutrino biasing knobs ===\n"
           << "  (mfpBias: region-scoped mean-free-path scale, needs >1;"
           << " cc/ncBias: process factor max(cc,nc) + uniform vertex spread"
           << " when >1, and the real CC/NC split for nu+e-;"
           << " xsecBias: scales the tabulated cross section everywhere)\n";
    for (G4int i = 0; i < kNFamilies; ++i) {
        const Knobs& k = fKnobs[i];
        G4cout << "  " << std::left << std::setw(38)
               << FamilyName(static_cast<Family>(i))
               << (k.enable ? " ON " : " OFF")
               << "  region=" << k.region
               << "  mfpBias=" << k.mfpBias
               << "  ccBias=" << k.ccBias
               << "  ncBias=" << k.ncBias
               << "  xsecBias=" << k.xsecBias;
        if (k.lowestEnergy >= 0.)
            G4cout << "  lowestEnergy=" << k.lowestEnergy / CLHEP::MeV << " MeV";
        G4cout << G4endl;
    }
    G4cout << "  " << std::left << std::setw(38) << "vacuum oscillation (G4NuVacOscProcess)"
           << (fOsc.enable ? " ON " : " OFF")
           << "  region=" << fOsc.region
           << "  distanceBias=" << fOsc.mfpBias;
    if (fOsc.lowestEnergy >= 0.)
        G4cout << "  lowestEnergy=" << fOsc.lowestEnergy / CLHEP::MeV << " MeV";
    G4cout << "\n=====================================\n" << G4endl;
}

void NeutrinoPhysics::ConstructProcess()
{
    // Index order matches G4NeutrinoPhysics so the per-flavour process
    // assignment below reads the same as upstream.
    const G4ParticleDefinition* p[6] = {
        G4AntiNeutrinoE::AntiNeutrinoE(),
        G4NeutrinoE::NeutrinoE(),
        G4AntiNeutrinoMu::AntiNeutrinoMu(),
        G4NeutrinoMu::NeutrinoMu(),
        G4AntiNeutrinoTau::AntiNeutrinoTau(),
        G4NeutrinoTau::NeutrinoTau()
    };

    if (fVerbose > 0) Print();

    // ---- vacuum oscillation (all six flavours share one process) ----------
    if (fOsc.enable) {
        auto osc = new G4NuVacOscProcess(fOsc.region);
        osc->SetBiasingFactor(fOsc.mfpBias);     // ignored unless > 1
        if (fOsc.lowestEnergy >= 0.) osc->SetLowestEnergy(fOsc.lowestEnergy);
        for (G4int i = 0; i < 6; ++i) {
            p[i]->GetProcessManager()->AddDiscreteProcess(osc);
        }
    }

    // ---- neutrino-electron scattering (all six flavours) -----------------
    {
        const Knobs& k = fKnobs[kElectron];
        if (k.enable) {
            auto proc = new G4NeutrinoElectronProcess(k.region);
            auto xsc = new G4NeutrinoElectronTotXsc();

            // Independent terms, applied independently -- unlike
            // G4NeutrinoPhysics, which picks ONE of these two paths.
            if (k.ccBias != 1.0 || k.ncBias != 1.0) {
                proc->SetBiasingFactors(k.ccBias, k.ncBias);
                // The only place in Geant4 where CC and NC are biased apart:
                // this reaches the separate CC and NC cross-section data sets.
                xsc->SetBiasingFactors(k.ccBias, k.ncBias);
            }
            if (k.mfpBias != 1.0) proc->SetBiasingFactor(k.mfpBias);
            if (k.xsecBias != 1.0) xsc->SetBiasingFactor(k.xsecBias);
            if (k.lowestEnergy >= 0.) proc->SetLowestEnergy(k.lowestEnergy);

            proc->AddDataSet(xsc);
            proc->RegisterMe(new G4NeutrinoElectronCcModel());
            proc->RegisterMe(new G4NeutrinoElectronNcModel());
            for (G4int i = 0; i < 6; ++i) {
                p[i]->GetProcessManager()->AddDiscreteProcess(proc);
            }
        }
    }

    // ---- neutrino-nucleus, one process object per flavour ----------------
    // Each family owns its factors, so nu_mu can be biased 1e9 while nu_e and
    // nu_tau stay at 1 -- impossible through G4NeutrinoPhysics.
    {
        const Knobs& k = fKnobs[kNucleusE];
        if (k.enable) {
            auto proc = new G4ElNeutrinoNucleusProcess(k.region);
            auto xsc = new G4ElNeutrinoNucleusTotXsc();
            if (k.ccBias != 1.0 || k.ncBias != 1.0)
                proc->SetBiasingFactors(k.ccBias, k.ncBias);
            if (k.mfpBias != 1.0) proc->SetBiasingFactor(k.mfpBias);
            if (k.xsecBias != 1.0) xsc->SetBiasingFactor(k.xsecBias);
            if (k.lowestEnergy >= 0.) proc->SetLowestEnergy(k.lowestEnergy);
            proc->AddDataSet(xsc);
            // Model order is load-bearing: the process indexes
            // GetHadronicInteractionList() as [0]=nu CC, [1]=nu NC,
            // [2]=antinu CC, [3]=antinu NC.
            proc->RegisterMe(new G4NuElNucleusCcModel());
            proc->RegisterMe(new G4NuElNucleusNcModel());
            proc->RegisterMe(new G4ANuElNucleusCcModel());
            proc->RegisterMe(new G4ANuElNucleusNcModel());
            for (G4int i = 0; i <= 1; ++i)
                p[i]->GetProcessManager()->AddDiscreteProcess(proc);
        }
    }
    {
        const Knobs& k = fKnobs[kNucleusMu];
        if (k.enable) {
            auto proc = new G4MuNeutrinoNucleusProcess(k.region);
            auto xsc = new G4MuNeutrinoNucleusTotXsc();
            if (k.ccBias != 1.0 || k.ncBias != 1.0)
                proc->SetBiasingFactors(k.ccBias, k.ncBias);
            if (k.mfpBias != 1.0) proc->SetBiasingFactor(k.mfpBias);
            if (k.xsecBias != 1.0) xsc->SetBiasingFactor(k.xsecBias);
            if (k.lowestEnergy >= 0.) proc->SetLowestEnergy(k.lowestEnergy);
            proc->AddDataSet(xsc);
            proc->RegisterMe(new G4NuMuNucleusCcModel());
            proc->RegisterMe(new G4NuMuNucleusNcModel());
            proc->RegisterMe(new G4ANuMuNucleusCcModel());
            proc->RegisterMe(new G4ANuMuNucleusNcModel());
            for (G4int i = 2; i <= 3; ++i)
                p[i]->GetProcessManager()->AddDiscreteProcess(proc);
        }
    }
    {
        const Knobs& k = fKnobs[kNucleusTau];
        if (k.enable) {
            auto proc = new G4TauNeutrinoNucleusProcess(k.region);
            auto xsc = new G4TauNeutrinoNucleusTotXsc();
            if (k.ccBias != 1.0 || k.ncBias != 1.0)
                proc->SetBiasingFactors(k.ccBias, k.ncBias);
            if (k.mfpBias != 1.0) proc->SetBiasingFactor(k.mfpBias);
            if (k.xsecBias != 1.0) xsc->SetBiasingFactor(k.xsecBias);
            if (k.lowestEnergy >= 0.) proc->SetLowestEnergy(k.lowestEnergy);
            proc->AddDataSet(xsc);
            proc->RegisterMe(new G4NuTauNucleusCcModel());
            proc->RegisterMe(new G4NuTauNucleusNcModel());
            proc->RegisterMe(new G4ANuTauNucleusCcModel());
            proc->RegisterMe(new G4ANuTauNucleusNcModel());
            for (G4int i = 4; i <= 5; ++i)
                p[i]->GetProcessManager()->AddDiscreteProcess(proc);
        }
    }
}
