#include "SteppingAction.hh"
#include "RunAction.hh"
#include "EventAction.hh"
#include "G4Track.hh"
#include "G4Step.hh"
#include "G4VProcess.hh"
#include "G4HadronicProcess.hh"
#include "G4Nucleus.hh"
#include "G4Ions.hh"
#include "G4SystemOfUnits.hh"
#include <cmath>

SteppingAction::SteppingAction(EventAction* eventAction, RunAction* runAction)
: fEventAction(eventAction), fRunAction(runAction) {}

void SteppingAction::UserSteppingAction(const G4Step* step)
{
    if (!fRunAction || !fEventAction) return;

    auto track = step->GetTrack();
    auto particle = track->GetDefinition();

    fEventAction->AddEdep(step->GetTotalEnergyDeposit());
    fEventAction->IncrementStep();

    // Skip malformed nuclei (Z<=0 or A<=0)
    if (particle->GetParticleType() == "nucleus") {
        auto ion = dynamic_cast<const G4Ions*>(particle);
        if (ion && (ion->GetAtomicNumber() <= 0 || ion->GetAtomicMass() <= 0)) return;
    }

    const G4VProcess* stepProcess = step->GetPostStepPoint()->GetProcessDefinedStep();
    const G4VProcess* creatorProcess = track->GetCreatorProcess();

    // -----------------------------
    // Primary particle (parentID == 0)
    // -----------------------------
    if (track->GetParentID() == 0) {
        if (track->GetCurrentStepNumber() == 1) {  // initial state
            fEventAction->primaryTrackID = track->GetTrackID();
            fEventAction->E  = track->GetKineticEnergy();
            fEventAction->x  = track->GetPosition().x();
            fEventAction->y  = track->GetPosition().y();
            fEventAction->z  = track->GetPosition().z();
            fEventAction->px = track->GetMomentum().x();
            fEventAction->py = track->GetMomentum().y();
            fEventAction->pz = track->GetMomentum().z();
        }

        // Neutrino interaction vertex (feeds the nu_* branches; harmless when
        // neutrino mode is off as those branches are simply not written).
        int pdg = particle->GetPDGEncoding();
        bool isPrimaryNeutrino =
            std::abs(pdg) == 12 || std::abs(pdg) == 14 || std::abs(pdg) == 16;

        if (isPrimaryNeutrino && stepProcess && !fEventAction->interactionRecorded) {
            G4String procName = stepProcess->GetProcessName();
            if (procName != "Transportation") {
                fEventAction->nuInteractionProcess = procName;
                auto vpos = step->GetPostStepPoint()->GetPosition();
                fEventAction->vertexX = vpos.x();
                fEventAction->vertexY = vpos.y();
                fEventAction->vertexZ = vpos.z();
                fEventAction->vertexT = step->GetPostStepPoint()->GetGlobalTime();

                // Struck nucleus, if this is a hadronic (neutrino-nucleus) process
                if (auto hadProc = dynamic_cast<const G4HadronicProcess*>(stepProcess)) {
                    if (const G4Nucleus* tgt = hadProc->GetTargetNucleus()) {
                        fEventAction->nuTargetZ = tgt->GetZ_asInt();
                        fEventAction->nuTargetA = tgt->GetA_asInt();
                    }
                }

                int expectedLepton = 0;
                if (std::abs(pdg) == 12) expectedLepton = (pdg > 0) ? 11 : -11;
                if (std::abs(pdg) == 14) expectedLepton = (pdg > 0) ? 13 : -13;
                if (std::abs(pdg) == 16) expectedLepton = (pdg > 0) ? 15 : -15;

                for (auto sec : *step->GetSecondaryInCurrentStep()) {
                    int secPDG = sec->GetDefinition()->GetPDGEncoding();
                    if (secPDG == expectedLepton) {
                        fEventAction->isCC = true;
                        fEventAction->outgoingLeptonPDG = secPDG;
                        fEventAction->outgoingLeptonE =
                            sec->GetKineticEnergy() + sec->GetDefinition()->GetPDGMass();
                        auto lp = sec->GetMomentum();
                        fEventAction->outgoingLeptonPx = lp.x();
                        fEventAction->outgoingLeptonPy = lp.y();
                        fEventAction->outgoingLeptonPz = lp.z();
                    }
                }
                fEventAction->isNC = !fEventAction->isCC;
                fEventAction->interactionRecorded = true;
            }
        }

        // Final state (track end)
        if (track->GetTrackStatus() == fStopAndKill) {
            auto p = track->GetMomentum();
            fEventAction->finalE  = track->GetKineticEnergy();
            fEventAction->finalPx = p.x();
            fEventAction->finalPy = p.y();
            fEventAction->finalPz = p.z();
            fEventAction->finalX  = track->GetPosition().x();
            fEventAction->finalY  = track->GetPosition().y();
            fEventAction->finalZ  = track->GetPosition().z();
        }
    }

    // -----------------------------
    // Record this step (all tracks). The per-track table is built from these.
    // -----------------------------
    fEventAction->AddStepInfo(
        track->GetTrackID(),
        track->GetParentID(),
        particle->GetPDGEncoding(),
        step->GetPreStepPoint()->GetPosition(),
        step->GetPostStepPoint()->GetPosition(),
        step->GetPreStepPoint()->GetKineticEnergy(),
        step->GetPostStepPoint()->GetKineticEnergy(),
        step->GetTotalEnergyDeposit(),
        step->GetPreStepPoint()->GetGlobalTime(),
        step->GetStepLength(),
        stepProcess ? stepProcess->GetProcessName() : "None",
        creatorProcess ? creatorProcess->GetProcessName() : "Primary",
        track->GetVertexPosition(),
        track->GetVertexKineticEnergy());
}
