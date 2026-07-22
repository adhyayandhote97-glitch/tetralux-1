#include "ds18b20.h"
#include "config.h"
#include <DallasTemperature.h>
#include <OneWire.h>

// Each DS18B20 is on its own one-wire pin (config.h), not a shared bus.
static OneWire wires[6] = {
    OneWire(PIN_DS18B20_T1), OneWire(PIN_DS18B20_T2), OneWire(PIN_DS18B20_T3),
    OneWire(PIN_DS18B20_T4), OneWire(PIN_DS18B20_T5), OneWire(PIN_DS18B20_T6),
};
static DallasTemperature sensors[6] = {
    DallasTemperature(&wires[0]), DallasTemperature(&wires[1]),
    DallasTemperature(&wires[2]), DallasTemperature(&wires[3]),
    DallasTemperature(&wires[4]), DallasTemperature(&wires[5]),
};

void ds18b20_init_all() {
  for (int i = 0; i < 6; i++) {
    sensors[i].begin();
  }
}

void ds18b20_read_all(float out[6]) {
  for (int i = 0; i < 6; i++) {
    sensors[i].requestTemperatures();
    float t = sensors[i].getTempCByIndex(0);
    // DallasTemperature returns -127.0 (DEVICE_DISCONNECTED_C) on failure.
    out[i] = (t <= -100.0f) ? NAN : t;
  }
}
