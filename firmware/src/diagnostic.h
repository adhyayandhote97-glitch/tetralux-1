// Bench-test output for the photodiode/BH1750 pairing. Serial only.
#ifndef TETRALUX_DIAGNOSTIC_H
#define TETRALUX_DIAGNOSTIC_H

#include "config.h"

#if DIAGNOSTIC_MODE
#include "telemetry/packet.h"

// Prints one line per face, +x..-z, from the values already in `s`.
void diagnostic_print(const SensorSample& s);
#endif

#endif // TETRALUX_DIAGNOSTIC_H
