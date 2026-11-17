// Tetralux-1 firmware (Phase 10) — Arduino Nano 33 IoT.
//
// Samples all sensors, builds one JSON packet per docs/architecture.md §8.1,
// and sends it over Serial every sample (and WiFi when WIFI_ENABLED), at
// SAMPLE_INTERVAL_MS.
// See docs/bringup.md for the flash/bring-up procedure.
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
  // Give the USB port a moment to enumerate, but boot anyway if nothing opens
  // it — the board must run on battery with no laptop attached.
  while (!Serial && millis() < 4000);
  Wire.begin();

  photodiode_init();
  bh1750_init_all();
  ds18b20_init_all();
  qmc5883l_init();
  opt4048_init_all();

  // WiFi is optional: wifi_begin() waits at most WIFI_BEGIN_TIMEOUT_MS and
  // wifi_service() retries every WIFI_RETRY_MS. Serial carries every frame.
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
  bool wifi_ok = false;  // bench mode: WiFi never started, nothing is POSTed
  diagnostic_print(s);
#elif WIFI_ENABLED
  bool wifi_ok = wifi_service();
#else
  bool wifi_ok = false;  // USB-only build: WiFi is never started
#endif
  s.flags = wifi_ok ? 0x01 : 0x00;

  size_t len = build_packet(s, packet_buf, sizeof(packet_buf));
  if (len == 0) {
    // Buffer overflow building the packet — should not happen with the sizes
    // above, but skip this sample rather than send a truncated/garbage frame.
    delay(SAMPLE_INTERVAL_MS);
    return;
  }

  if (wifi_ok) {
    wifi_send_packet(packet_buf, len);
  }
  // Serial always gets the same line, so a USB-only bring-up works even while
  // WiFi is down, and both paths can be compared side by side.
  Serial.println(packet_buf);

  delay(SAMPLE_INTERVAL_MS);
}
