#include "SteppingAction.hh"
#include "RunAction.hh"
#include "EventAction.hh"
#include "G4Track.hh"
#include "G4Step.hh"
#include "G4VPhysicalVolume.hh"
#include "G4LogicalVolume.hh"
#include "ExitWriter.hh"
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
            fEventAction->primaryMass = particle->GetPDGMass();
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
    // Exit export: this step ends on the boundary of the watched volume, so the
    // track is crossing OUT of it -- record the particle as it leaves (see
    // ExitWriter). Momentum/position/time come from the POST-step point: that
    // is the state at the crossing, which is what a downstream stage must start
    // from.
    // -----------------------------
    RecordExitCrossing(step);

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


namespace {

/// Does this volume answer to `name`? A GDML placement without an explicit
/// physvol name becomes "<logical>_PV", so a config naming the volume as it
/// appears in the GDML (the logical name) would otherwise never match.
bool VolumeMatches(const G4VPhysicalVolume* vol, const G4String& name)
{
    if (!vol) return false;
    if (vol->GetName() == name) return true;
    const auto* logical = vol->GetLogicalVolume();
    return logical && logical->GetName() == name;
}

}  // namespace

void SteppingAction::RecordExitCrossing(const G4Step* step)
{
    auto* writer = fRunAction->GetExitWriter();
    if (!writer->Enabled()) return;

    // Geant4 reports the two boundaries with DIFFERENT statuses: an inner
    // volume boundary is fGeomBoundary, but leaving the world is fWorldBoundary
    // -- checking only the former would silently record nothing for the default
    // World surface.
    const auto* post = step->GetPostStepPoint();
    const G4StepStatus status = post->GetStepStatus();
    if (status != fGeomBoundary && status != fWorldBoundary) return;
    if (post->GetKineticEnergy() < writer->MinKineticEnergy()) return;

    auto* track = step->GetTrack();

    // Which volume are we leaving? Past the world edge there is no post-step
    // volume at all, which (with fWorldBoundary above) is the world-exit signal.
    const auto* preVol = step->GetPreStepPoint()->GetPhysicalVolume();
    const auto* postVol = post->GetPhysicalVolume();
    const G4String& watched = writer->Volume();

    bool leaving = false;
    if (watched.empty() || watched == "World") {
        leaving = (postVol == nullptr);
    } else if (VolumeMatches(preVol, watched)) {
        leaving = !VolumeMatches(postVol, watched);
    }
    if (!leaving) return;

    auto* def = track->GetDefinition();
    ExitWriter::Crossing c;
    c.pdg = def->GetPDGEncoding();
    c.trackID = track->GetTrackID();
    c.parentID = track->GetParentID();
    const auto mom = post->GetMomentum();
    c.px = mom.x();
    c.py = mom.y();
    c.pz = mom.z();
    c.mass = def->GetPDGMass();
    c.energy = post->GetKineticEnergy() + c.mass;   // HepMC3 wants total energy
    c.position = post->GetPosition();
    c.time = post->GetGlobalTime();
    writer->Record(c);

    // Stop here when asked: for a staged run the next stage continues from this
    // surface, so transporting past it in THIS stage would double count.
    if (writer->KillAtBoundary()) track->SetTrackStatus(fStopAndKill);
}
