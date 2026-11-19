#include "photodiode.h"
#include "config.h"

// keep order
static const uint8_t PD_PINS[6] = {
    PIN_PD_PLUS_X,   // +x
    PIN_PD_MINUS_X,  // -x
    PIN_PD_PLUS_Y,   // +y
    PIN_PD_MINUS_Y,  // -y
    PIN_PD_PLUS_Z,   // +z
    PIN_PD_MINUS_Z,  // -z
};

// averaging count
static const uint8_t PD_SAMPLES = 16;

// 12-bit ADC
void photodiode_init() {
  analogReadResolution(12);  // 0-4095
}

// averaged read
void photodiode_read_all(uint16_t out[6]) {
  for (uint8_t face = 0; face < 6; face++) {
    uint32_t total = 0;
    for (uint8_t i = 0; i < PD_SAMPLES; i++) {
      total += analogRead(PD_PINS[face]);
    }
    out[face] = (uint16_t)(total / PD_SAMPLES);
  }
}
