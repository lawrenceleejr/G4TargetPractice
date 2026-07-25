// pythia_gen -- minimal Pythia 8 -> HepMC3 generator for GDMLTargetPractice.
//
//   pythia_gen <card.cmnd> [out.hepmc]
//
// Reads a Pythia command file (rendered by pythia/run_pythia.py from the host's
// pythia_job.json), generates Main:numberOfEvents events and writes HepMC3
// ASCII, which the shared HepMC3 -> output.root converter then turns into the
// common ntuple schema.
//
// Deliberately tiny and under our control rather than depending on whichever
// mainNN example a given Pythia release ships. The output file comes from the
// second argument when given, else the card's `HEPMCoutput:file`, else
// pythia_events.hepmc.
//
// Requires Pythia >= 8.3 (the Pythia8Plugins/HepMC3.h interface).
#include <iostream>
#include <string>

#include "Pythia8/Pythia.h"
#include "Pythia8Plugins/HepMC3.h"

int main(int argc, char* argv[]) {
  if (argc < 2) {
    std::cerr << "usage: pythia_gen <card.cmnd> [out.hepmc]\n";
    return 2;
  }
  const std::string card = argv[1];

  Pythia8::Pythia pythia;
  if (!pythia.readFile(card)) {
    std::cerr << "pythia_gen: failed to read card " << card << "\n";
    return 1;
  }

  // Output path comes from argv (the driver always passes it). Deliberately NOT
  // read from a card setting: HEPMCoutput:file is a mainNN-example convention,
  // not guaranteed to be a declared setting in every Pythia release.
  std::string out = (argc > 2) ? argv[2] : std::string("pythia_events.hepmc");

  if (!pythia.init()) {
    std::cerr << "pythia_gen: initialization failed (check the beam/process "
                 "settings in " << card << ")\n";
    return 1;
  }

  Pythia8::Pythia8ToHepMC toHepMC(out);
  const int nEvent = pythia.mode("Main:numberOfEvents");
  const int nAbort = pythia.mode("Main:timesAllowErrors");

  int iAbort = 0, nWritten = 0;
  for (int iEvent = 0; iEvent < nEvent; ++iEvent) {
    if (!pythia.next()) {
      if (++iAbort < nAbort) continue;
      std::cerr << "pythia_gen: too many errors, stopping after " << nWritten
                << " event(s)\n";
      break;
    }
    toHepMC.writeNextEvent(pythia);
    ++nWritten;
  }

  pythia.stat();
  std::cout << "pythia_gen: wrote " << nWritten << " event(s) to " << out
            << std::endl;
  // A run that produced nothing is a failure the driver must see.
  return (nWritten > 0) ? 0 : 1;
}
