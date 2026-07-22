// S1223 photodiode reader (Phase 10) — 6 analog faces, +x,-x,+y,-y,+z,-z order.
#ifndef TETRALUX_PHOTODIODE_H
#define TETRALUX_PHOTODIODE_H

#include <Arduino.h>

// Reads all 6 photodiode pins into `out[6]`, in canonical face order.
// 10-bit ADC (0-1023) per docs/architecture.md's hardware map.
void photodiode_read_all(uint16_t out[6]);

#endif // TETRALUX_PHOTODIODE_H
