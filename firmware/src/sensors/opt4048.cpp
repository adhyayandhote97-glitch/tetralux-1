#include "opt4048.h"
#include "config.h"
#include "mux.h"
#include <Wire.h>

// result registers
#define OPT4048_REG_CH0 0x00
#define OPT4048_REG_CH1 0x02
#define OPT4048_REG_CH2 0x04
#define OPT4048_REG_CH3 0x06
#define OPT4048_REG_CONFIG 0x0A

static uint16_t read_reg16(uint8_t reg) {
  Wire.beginTransmission(OPT4048_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((int)OPT4048_ADDR, 2);
  uint16_t hi = Wire.available() ? Wire.read() : 0;
  uint16_t lo = Wire.available() ? Wire.read() : 0;
  return (hi << 8) | lo;
}

// decode word
static float decode_channel(uint16_t raw) {
  uint8_t exponent = (raw >> 12) & 0x0F;
  uint16_t mantissa = raw & 0x0FFF;
  return (float)mantissa * (float)(1UL << exponent);
}

static void configure_default() {
  // default config
  Wire.beginTransmission(OPT4048_ADDR);
  Wire.write(OPT4048_REG_CONFIG);
  Wire.write(0x00);
  Wire.write(0x00);
  Wire.endTransmission();
}

void opt4048_init_all() {
  for (int ch = 0; ch < 4; ch++) {
    mux_select_channel(MUX_CHANNEL_OPT4048_BASE + ch);
    configure_default();
  }
}

// TODO: matrix
static void channels_to_xyz(float ch0, float ch1, float ch2, float ch3,
                            float *X, float *Y, float *Z) {
  (void)ch3;  // unused
  *X = ch0;
  *Y = ch1;
  *Z = ch2;
}

void opt4048_read_all(float X[4], float Y[4], float Z[4], float lux[4]) {
  for (int ch = 0; ch < 4; ch++) {
    mux_select_channel(MUX_CHANNEL_OPT4048_BASE + ch);
    float c0 = decode_channel(read_reg16(OPT4048_REG_CH0));
    float c1 = decode_channel(read_reg16(OPT4048_REG_CH1));
    float c2 = decode_channel(read_reg16(OPT4048_REG_CH2));
    float c3 = decode_channel(read_reg16(OPT4048_REG_CH3));
    channels_to_xyz(c0, c1, c2, c3, &X[ch], &Y[ch], &Z[ch]);
    lux[ch] = Y[ch];  // placeholder scale
  }
}
