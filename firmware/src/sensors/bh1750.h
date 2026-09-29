// BH1750 ambient lux sensors (Phase 10) — 6 units behind the TCA9548A mux.
#ifndef TETRALUX_BH1750_H
#define TETRALUX_BH1750_H

#include <Arduino.h>

void bh1750_init_all();

// Reads all 6 BH1750 sensors (per-face BH1750_MUX_*/BH1750_ADDR_* pairs) into
// `out[6]`, in canonical face order. Failed reads are left at 0.0 (BH1750 has
// no "missing sensor" sentinel unlike DS18B20).
void bh1750_read_all(float out[6]);

#endif // TETRALUX_BH1750_H
