// S1223 photodiode reader (Phase 10) — 6 analog faces, +x,-x,+y,-y,+z,-z order.
#ifndef TETRALUX_PHOTODIODE_H
#define TETRALUX_PHOTODIODE_H

#include <Arduino.h>

// Switches the ADC to 12-bit. Call once from setup(), before any read.
void photodiode_init();

// Reads all 6 photodiode pins into `out[6]`, in canonical face order.
// 12-bit ADC (0-4095) on the Nano 33 IoT, averaged over 16 samples per face.
void photodiode_read_all(uint16_t out[6]);

#endif // TETRALUX_PHOTODIODE_H
