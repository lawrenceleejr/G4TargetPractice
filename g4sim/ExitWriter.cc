#include "ExitWriter.hh"

#include "G4SystemOfUnits.hh"
#include "G4Exception.hh"
#include "CLHEP/Units/PhysicalConstants.h"

#include "HepMC3/WriterAscii.h"
#include "HepMC3/GenEvent.h"
#include "HepMC3/GenParticle.h"
#include "HepMC3/GenVertex.h"
#include "HepMC3/Attribute.h"
#include "HepMC3/Units.h"

ExitWriter::ExitWriter() = default;

ExitWriter::~ExitWriter() { EndRun(); }

void ExitWriter::BeginRun()
{
    if (!fEnabled) return;
    fWriter = std::make_unique<HepMC3::WriterAscii>(fPath);
    if (fWriter->failed()) {
        G4Exception("ExitWriter::BeginRun", "NoOutputFile", FatalException,
                    ("Could not open HepMC3 output file: " + fPath).c_str());
        return;
    }
    fWritten = 0;
    fEvents = 0;
    G4cout << "Exit HepMC3: recording particles leaving "
           << (fVolume.empty() ? G4String("the world") : fVolume)
           << " to " << fPath
           << " (min KE " << fMinKE / MeV << " MeV"
           << (fKill ? ", killing them at the boundary" : "")
           << ")." << G4endl;
}

void ExitWriter::EndRun()
{
    if (!fWriter) return;
    fWriter->close();
    fWriter.reset();
    G4cout << "Exit HepMC3: wrote " << fWritten << " particle(s) over "
           << fEvents << " event(s) to " << fPath << G4endl;
}

void ExitWriter::EndEvent(int eventID, int primaryPDG, double primaryEnergy,
                          double primaryMass, const G4ThreeVector& primaryMomentum)
{
    if (!fWriter) return;

    HepMC3::GenEvent evt(HepMC3::Units::MEV, HepMC3::Units::MM);
    evt.set_event_number(eventID);

    for (const auto& c : fCrossings) {
        // HepMC3 stores the vertex time as a length (x0 = c*t); the reader
        // divides by c to recover ns (see PrimaryGenerator::LoadEventFile).
        auto vtx = std::make_shared<HepMC3::GenVertex>(
            HepMC3::FourVector(c.position.x() / mm, c.position.y() / mm,
                               c.position.z() / mm,
                               (c.time * CLHEP::c_light) / mm));

        // Every vertex needs an incoming particle: HepMC3's ASCII READER
        // rejects a vertex written with an empty incoming list ("too few
        // particles were parsed"), so a bare outgoing-only vertex would produce
        // a file nothing can read back -- including our own /gun/hepmcFile.
        // The incoming leg is the primary that started the event (status 4),
        // which is also the provenance and matches the hand-off writer's shape.
        auto beam = std::make_shared<HepMC3::GenParticle>(
            HepMC3::FourVector(primaryMomentum.x() / MeV, primaryMomentum.y() / MeV,
                               primaryMomentum.z() / MeV,
                               (primaryEnergy + primaryMass) / MeV),
            primaryPDG, 4);
        beam->set_generated_mass(primaryMass / MeV);
        vtx->add_particle_in(beam);

        auto p = std::make_shared<HepMC3::GenParticle>(
            HepMC3::FourVector(c.px / MeV, c.py / MeV, c.pz / MeV, c.energy / MeV),
            c.pdg, 1);
        p->set_generated_mass(c.mass / MeV);
        vtx->add_particle_out(p);
        evt.add_vertex(vtx);
        ++fWritten;
    }

    // Provenance as attributes: the primary that produced these crossings and
    // the surface they crossed. Attributes, not invented particles/vertices --
    // the beam is not the mother of a crossing in any HepMC sense.
    evt.add_attribute("gdmltp_primary_pdg",
                      std::make_shared<HepMC3::IntAttribute>(primaryPDG));
    evt.add_attribute("gdmltp_primary_ke",
                      std::make_shared<HepMC3::DoubleAttribute>(primaryEnergy / MeV));
    evt.add_attribute("gdmltp_primary_px",
                      std::make_shared<HepMC3::DoubleAttribute>(primaryMomentum.x() / MeV));
    evt.add_attribute("gdmltp_primary_py",
                      std::make_shared<HepMC3::DoubleAttribute>(primaryMomentum.y() / MeV));
    evt.add_attribute("gdmltp_primary_pz",
                      std::make_shared<HepMC3::DoubleAttribute>(primaryMomentum.z() / MeV));
    evt.add_attribute("gdmltp_exit_volume",
                      std::make_shared<HepMC3::StringAttribute>(
                          fVolume.empty() ? std::string("World") : std::string(fVolume)));

    fWriter->write_event(evt);
    ++fEvents;
}
