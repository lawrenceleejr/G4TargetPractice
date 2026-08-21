#ifndef EXITWRITER_H
#define EXITWRITER_H

#include "globals.hh"
#include "G4ThreeVector.hh"
#include <memory>
#include <string>
#include <vector>

namespace HepMC3 { class WriterAscii; }

/// Optional HepMC3 export of the particles LEAVING a volume -- the scoring
/// plane / phase-space file that lets one simulation feed the next.
///
/// g4sim already READS HepMC3 (`/gun/hepmcFile`), so writing it closes the
/// loop: transport a beamline, record everything crossing out of a volume, and
/// replay that file as the primaries of the next stage (a different geometry,
/// finer physics, whatever). It is also the interchange for any downstream tool
/// that speaks HepMC3, without going through the ntuple.
///
/// Event structure: one GenEvent per Geant4 event, and one GenVertex per
/// crossing at the point and time the particle crossed, holding that particle
/// as an outgoing status-1 particle. Crossings genuinely happen at different
/// places and times, so a single shared vertex would be a lie; the reader picks
/// up each particle's own production vertex. Each vertex also carries the
/// primary as an incoming status-4 particle -- both as provenance and because
/// HepMC3's ASCII reader refuses to parse a vertex with no incoming particle,
/// so an outgoing-only vertex would write a file nothing can read back. The
/// volume that was left rides along as an event attribute.
///
/// Units are HepMC3 MEV/MM, matching the rest of the pipeline; vertex times are
/// stored as c*t (HepMC3's convention) and converted back on read.
class ExitWriter {
public:
    /// One particle crossing the boundary, in Geant4 units (MeV, mm, ns).
    struct Crossing {
        int pdg = 0;
        int trackID = 0;
        int parentID = 0;
        double px = 0, py = 0, pz = 0;   ///< momentum at the crossing [MeV/c]
        double energy = 0;               ///< TOTAL energy [MeV]
        double mass = 0;                 ///< [MeV]
        G4ThreeVector position;          ///< crossing point [mm]
        double time = 0;                 ///< global time [ns]
    };

    ExitWriter();
    ~ExitWriter();

    // --- configuration (messenger) ---
    void SetFile(const G4String& path) { fPath = path; fEnabled = !path.empty(); }
    void SetVolume(const G4String& name) { fVolume = name; }
    void SetMinKineticEnergy(double keMeV) { fMinKE = keMeV; }
    void SetKillAtBoundary(bool kill) { fKill = kill; }

    bool Enabled() const { return fEnabled; }
    const G4String& Volume() const { return fVolume; }   ///< empty/"World" = the world boundary
    double MinKineticEnergy() const { return fMinKE; }
    bool KillAtBoundary() const { return fKill; }

    // --- lifecycle ---
    void BeginRun();                     ///< open the file (no-op when disabled)
    void EndRun();                       ///< flush + close, and report the count
    void BeginEvent() { fCrossings.clear(); }
    void Record(const Crossing& c) { fCrossings.push_back(c); }
    /// Write this event. Events with no crossings are still written (empty), so
    /// the file stays 1:1 with the run -- a downstream `beamOn N` lines up.
    /// `primaryEnergy` is the primary's KINETIC energy; `primaryMass` turns it
    /// into the total energy HepMC3 wants for the incoming beam leg.
    void EndEvent(int eventID, int primaryPDG, double primaryEnergy,
                  double primaryMass, const G4ThreeVector& primaryMomentum);

private:
    bool fEnabled = false;
    G4String fPath;
    G4String fVolume = "World";
    double fMinKE = 0.0;
    bool fKill = false;

    std::unique_ptr<HepMC3::WriterAscii> fWriter;
    std::vector<Crossing> fCrossings;
    long fWritten = 0;      ///< particles written across the run
    long fEvents = 0;
};

#endif
