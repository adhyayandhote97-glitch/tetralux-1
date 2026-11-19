#include "ds18b20.h"
#include "config.h"
#include <DallasTemperature.h>
#include <OneWire.h>

// shared bus
static OneWire bus(PIN_DS18B20_BUS);
static DallasTemperature sensors(&bus);

// face order
static const DeviceAddress ADDRS[6] = {
    DS18B20_ADDR_PLUS_X, DS18B20_ADDR_MINUS_X, DS18B20_ADDR_PLUS_Y,
    DS18B20_ADDR_MINUS_Y, DS18B20_ADDR_PLUS_Z, DS18B20_ADDR_MINUS_Z,
};

// last readings
static float last_c[6] = {NAN, NAN, NAN, NAN, NAN, NAN};
static uint32_t requested_ms = 0;

void ds18b20_init_all() {
  sensors.begin();
  sensors.setWaitForConversion(false);  // non-blocking
  sensors.requestTemperatures();
  requested_ms = millis();
}

// never waits
void ds18b20_read_all(float out[6]) {
  if (millis() - requested_ms >= sensors.millisToWaitForConversion()) {
    for (int i = 0; i < 6; i++) {
      float t = sensors.getTempC(ADDRS[i]);
      // missing sensor
      last_c[i] = (t <= -100.0f) ? NAN : t;
    }
    sensors.requestTemperatures();
    requested_ms = millis();
  }
  for (int i = 0; i < 6; i++) {
    out[i] = last_c[i];
  }
}
