// Tetralux-1 firmware (Phase 10) — Arduino Nano 33 IoT.
//
// Samples all sensors, builds one JSON packet per docs/architecture.md §8.1,
// and sends it over WiFi (primary) or Serial (fallback) at SAMPLE_INTERVAL_MS.
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

static uint32_t seq = 0;
static char packet_buf[600];

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin();

  bh1750_init_all();
  ds18b20_init_all();
  qmc5883l_init();
  opt4048_init_all();

  // WiFi is attempted but not required to boot — a WiFi-less board still
  // functions over Serial (see the wifi_send_packet() fallback in loop()).
  wifi_connect();
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

  bool wifi_ok = wifi_is_connected();
  s.flags = wifi_ok ? 0x01 : 0x00;

  size_t len = build_packet(s, packet_buf, sizeof(packet_buf));
  if (len == 0) {
    // Buffer overflow building the packet — should not happen with the sizes
    // above, but skip this sample rather than send a truncated/garbage frame.
    delay(SAMPLE_INTERVAL_MS);
    return;
  }

  bool sent = false;
  if (wifi_ok) {
    sent = wifi_send_packet(packet_buf, len);
  }
  if (!sent) {
    // Serial fallback: identical JSON line, so tetralux.ingest.serial_reader
    // (which forwards any line starting with '{') decodes it the same way.
    Serial.println(packet_buf);
  }

  delay(SAMPLE_INTERVAL_MS);
}
