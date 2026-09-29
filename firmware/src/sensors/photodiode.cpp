#include "photodiode.h"
#include "config.h"

// The one place the face order lives: index 0..5 is +x,-x,+y,-y,+z,-z, matching
// FACE_NAMES on the ground station. A4/A5 are the I2C bus, so the last two
// faces use A6/A7. Reorder this array and the sun vector comes out wrong.
static const uint8_t PD_PINS[6] = {
    PIN_PD_PLUS_X,   // +x
    PIN_PD_MINUS_X,  // -x
    PIN_PD_PLUS_Y,   // +y
    PIN_PD_MINUS_Y,  // -y
    PIN_PD_PLUS_Z,   // +z
    PIN_PD_MINUS_Z,  // -z
};

// How many reads to average per face, to settle ADC noise.
static const uint8_t PD_SAMPLES = 16;

// Switches the ADC to 12-bit. Call once from setup(), before any read.
void photodiode_init() {
  analogReadResolution(12);  // 0-4095, matching ADC_MAX on the ground station
}

// Reads all 6 photodiode pins into `out[6]`, averaged over PD_SAMPLES reads.
void photodiode_read_all(uint16_t out[6]) {
  for (uint8_t face = 0; face < 6; face++) {
    uint32_t total = 0;
    for (uint8_t i = 0; i < PD_SAMPLES; i++) {
      total += analogRead(PD_PINS[face]);
    }
    out[face] = (uint16_t)(total / PD_SAMPLES);
  }
}
