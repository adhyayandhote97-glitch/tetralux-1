// packet builder
#ifndef TETRALUX_PACKET_H
#define TETRALUX_PACKET_H

#include <Arduino.h>

struct SensorSample {
  uint32_t seq;
  uint32_t ts_ms;
  uint16_t pd[6];  // raw ADC
  float lux[6];  // face order
  int16_t mag_x, mag_y, mag_z;
  float opt_X[4], opt_Y[4], opt_Z[4], opt_lux[4];
  float temp[6];  // NAN=null
  uint8_t flags;  // bit0 WiFi
};

// build packet
size_t build_packet(const SensorSample &s, char *out, size_t out_size);

// XOR checksum
uint8_t xor_checksum(const char *data, size_t len);

#endif // TETRALUX_PACKET_H
