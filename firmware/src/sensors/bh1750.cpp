#include "bh1750.h"
#include "config.h"
#include "mux.h"
#include <BH1750.h>

// per-face objects
static const uint8_t BH1750_MUX[6] = {
    BH1750_MUX_PLUS_X, BH1750_MUX_MINUS_X, BH1750_MUX_PLUS_Y,
    BH1750_MUX_MINUS_Y, BH1750_MUX_PLUS_Z, BH1750_MUX_MINUS_Z,
};
static const uint8_t BH1750_ADDRS[6] = {
    BH1750_ADDR_PLUS_X, BH1750_ADDR_MINUS_X, BH1750_ADDR_PLUS_Y,
    BH1750_ADDR_MINUS_Y, BH1750_ADDR_PLUS_Z, BH1750_ADDR_MINUS_Z,
};
static BH1750 sensors[6];

void bh1750_init_all() {
  for (int ch = 0; ch < 6; ch++) {
    mux_select_channel(BH1750_MUX[ch]);
    sensors[ch].begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDRS[ch]);
  }
}

void bh1750_read_all(float out[6]) {
  for (int ch = 0; ch < 6; ch++) {
    mux_select_channel(BH1750_MUX[ch]);
    float lux = sensors[ch].readLightLevel();
    out[ch] = (lux < 0) ? 0.0f : lux;  // read failure
  }
}
