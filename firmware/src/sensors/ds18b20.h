// DS18B20 thermal sensors (Phase 10) — 6 units, one-wire, T1..T6.
#ifndef TETRALUX_DS18B20_H
#define TETRALUX_DS18B20_H

#include <Arduino.h>

void ds18b20_init_all();

// Reads all 6 sensors into `out[6]` (degrees C). A failed/disconnected sensor
// is written as NAN, which packet.cpp serializes as JSON `null` — matching
// tetralux.frames.SensorFrame's nullable-temperature contract.
void ds18b20_read_all(float out[6]);

#endif // TETRALUX_DS18B20_H
