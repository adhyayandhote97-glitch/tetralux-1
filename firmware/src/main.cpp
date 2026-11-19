// Tetralux-1 firmware
#include <Arduino.h>
#include <Wire.h>
#include "config.h"
#include "sensors/photodiode.h"
#include "sensors/bh1750.h"
#include "sensors/ds18b20.h"
#include "sensors/qmc5883l.h"
#include "sensors/opt4048.h"
#include "telemetry/packet.h"
#include "telemetry/wifi_sender.h"
#include "diagnostic.h"

static uint32_t seq = 0;
static char packet_buf[600];

void setup() {
  Serial.begin(SERIAL_BAUD);
  // USB wait
  while (!Serial && millis() < 4000);
  Wire.begin();

  photodiode_init();
  bh1750_init_all();
  ds18b20_init_all();
  qmc5883l_init();
  opt4048_init_all();

  // optional WiFi
#if WIFI_ENABLED && !DIAGNOSTIC_MODE
  wifi_begin();
#endif
}

void loop() {
  SensorSample s;
  s.seq = seq++;
  s.ts_ms = millis();

  photodiode_read_all(s.pd);
  bh1750_read_all(s.lux);
  qmc5883l_read(&s.mag_x, &s.mag_y, &s.mag_z);
  opt4048_read_all(s.opt_X, s.opt_Y, s.opt_Z, s.opt_lux);
  ds18b20_read_all(s.temp);

#if DIAGNOSTIC_MODE
  bool wifi_ok = false;  // bench mode
  diagnostic_print(s);
#elif WIFI_ENABLED
  bool wifi_ok = wifi_service();
#else
  bool wifi_ok = false;  // USB only
#endif
  s.flags = wifi_ok ? 0x01 : 0x00;

  size_t len = build_packet(s, packet_buf, sizeof(packet_buf));
  if (len == 0) {
    // skip sample
    delay(SAMPLE_INTERVAL_MS);
    return;
  }

  if (wifi_ok) {
    wifi_send_packet(packet_buf, len);
  }
  // always Serial
  Serial.println(packet_buf);

  delay(SAMPLE_INTERVAL_MS);
}
