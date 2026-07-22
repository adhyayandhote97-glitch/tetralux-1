#include "bh1750.h"
#include "config.h"
#include "mux.h"
#include <BH1750.h>

static BH1750 sensor;

void bh1750_init_all() {
  for (int ch = 0; ch < 6; ch++) {
    mux_select_channel(MUX_CHANNEL_BH1750_BASE + ch);
    sensor.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR);
  }
}

void bh1750_read_all(float out[6]) {
  for (int ch = 0; ch < 6; ch++) {
    mux_select_channel(MUX_CHANNEL_BH1750_BASE + ch);
    float lux = sensor.readLightLevel();
    out[ch] = (lux < 0) ? 0.0f : lux;  // library returns -1 on read failure
  }
}
