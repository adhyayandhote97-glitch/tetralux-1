// DS18B20 thermal sensors (Phase 10) — 6 units on one shared one-wire bus, one per face.
#ifndef TETRALUX_DS18B20_H
#define TETRALUX_DS18B20_H

#include <Arduino.h>

void ds18b20_init_all();

// Writes the latest completed temperature per sensor into `out[6]` (degrees C),
// in face order +x,-x,+y,-y,+z,-z (DS18B20_ADDR_* in config.h). Never blocks: values refresh once per conversion
// (~750 ms), so consecutive frames can repeat them. A sensor that doesn't answer,
// or any sensor before the first conversion completes, is NAN, which packet.cpp
// serializes as JSON `null` — matching tetralux.frames.SensorFrame's
// nullable-temperature contract.
void ds18b20_read_all(float out[6]);

#endif // TETRALUX_DS18B20_H
