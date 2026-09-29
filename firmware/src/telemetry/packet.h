// Tetralux-1 telemetry packet builder (Phase 10).
//
// Must match src/tetralux/telemetry/json_frame.py byte-for-byte: field order
// seq,ts,pd,lux,mag,opt,temp,flags,chk; checksum is an 8-bit XOR over the
// exact transmitted bytes up to (not including) `,"chk"`.
#ifndef TETRALUX_PACKET_H
#define TETRALUX_PACKET_H

#include <Arduino.h>

struct SensorSample {
  uint32_t seq;
  uint32_t ts_ms;
  uint16_t pd[6];          // +x,-x,+y,-y,+z,-z raw ADC (0-4095, 12-bit)
  float lux[6];            // same face order
  int16_t mag_x, mag_y, mag_z;
  float opt_X[4], opt_Y[4], opt_Z[4], opt_lux[4];
  float temp[6];           // NAN => transmit JSON null (sensor missing)
  uint8_t flags;           // bit0 = WiFi connected
};

// Builds the full packet string (including the checksum field) into `out`.
// Returns the length written. `out` must be large enough (~600 bytes is safe).
size_t build_packet(const SensorSample &s, char *out, size_t out_size);

// 8-bit XOR checksum over `len` bytes of `data` — the same algorithm the
// ground station's xor_checksum() uses.
uint8_t xor_checksum(const char *data, size_t len);

#endif // TETRALUX_PACKET_H
