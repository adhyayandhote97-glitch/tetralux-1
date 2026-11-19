// bench output
#ifndef TETRALUX_DIAGNOSTIC_H
#define TETRALUX_DIAGNOSTIC_H

#include "config.h"

#if DIAGNOSTIC_MODE
#include "telemetry/packet.h"

// per-face lines
void diagnostic_print(const SensorSample& s);
#endif

#endif // TETRALUX_DIAGNOSTIC_H
