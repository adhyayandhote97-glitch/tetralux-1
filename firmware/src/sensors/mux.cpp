#include "mux.h"
#include "config.h"
#include <Wire.h>

void mux_select_channel(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(I2C_MUX_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}
