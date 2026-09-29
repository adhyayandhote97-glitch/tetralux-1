#include "ds18b20.h"
#include "config.h"
#include <DallasTemperature.h>
#include <OneWire.h>

// All six sensors share one one-wire bus; each is picked out by its ROM address.
static OneWire bus(PIN_DS18B20_BUS);
static DallasTemperature sensors(&bus);

// Index 0..5 is +x,-x,+y,-y,+z,-z, the same face order as every other array.
static const DeviceAddress ADDRS[6] = {
    DS18B20_ADDR_PLUS_X, DS18B20_ADDR_MINUS_X, DS18B20_ADDR_PLUS_Y,
    DS18B20_ADDR_MINUS_Y, DS18B20_ADDR_PLUS_Z, DS18B20_ADDR_MINUS_Z,
};

// Latest completed reading per face; NAN until the first conversion finishes.
static float last_c[6] = {NAN, NAN, NAN, NAN, NAN, NAN};
static uint32_t requested_ms = 0;

void ds18b20_init_all() {
  sensors.begin();
  sensors.setWaitForConversion(false);  // requestTemperatures() returns at once
  sensors.requestTemperatures();
  requested_ms = millis();
}

// One conversion covers all six and takes up to 750 ms (12-bit), longer than a
// loop, so this never waits: once the conversion time has passed it reads all
// six and starts the next one; otherwise it returns the last completed values.
void ds18b20_read_all(float out[6]) {
  if (millis() - requested_ms >= sensors.millisToWaitForConversion()) {
    for (int i = 0; i < 6; i++) {
      float t = sensors.getTempC(ADDRS[i]);
      // -127.0 (DEVICE_DISCONNECTED_C) means that address didn't answer; the
      // rest are still read.
      last_c[i] = (t <= -100.0f) ? NAN : t;
    }
    sensors.requestTemperatures();
    requested_ms = millis();
  }
  for (int i = 0; i < 6; i++) {
    out[i] = last_c[i];
  }
}
