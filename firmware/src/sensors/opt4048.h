// OPT4048 tristimulus color sensor (Phase 10) — 4 units on mux channels 4-7.
//
// No mainstream Arduino library exists for the OPT4048 at time of writing, so
// this is a minimal raw-register I2C driver (channel result registers + CIE
// matrix multiply per the TI datasheet). Treat as a first draft: verify
// register addresses/scale factors against your specific OPT4048 datasheet
// revision before trusting the output, and expect to iterate here once real
// hardware is on the bench (see docs/bringup.md step 1-2).
#ifndef TETRALUX_OPT4048_H
#define TETRALUX_OPT4048_H

#include <Arduino.h>

void opt4048_init_all();

// Reads all 4 OPT4048 sensors (mux channels MUX_CHANNEL_OPT4048_BASE..+3)
// into CIE XYZ tristimulus values + lux, in that mux-channel order (this
// project does not assign OPT4048s to specific faces — they're edge-mounted).
void opt4048_read_all(float X[4], float Y[4], float Z[4], float lux[4]);

#endif // TETRALUX_OPT4048_H
