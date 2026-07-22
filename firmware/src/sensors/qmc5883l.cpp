#include "qmc5883l.h"
#include "config.h"
#include "mux.h"
#include <QMC5883LCompass.h>

static QMC5883LCompass compass;

void qmc5883l_init() {
  mux_select_channel(MUX_CHANNEL_QMC5883L);
  compass.init();
}

void qmc5883l_read(int16_t *x, int16_t *y, int16_t *z) {
  mux_select_channel(MUX_CHANNEL_QMC5883L);
  compass.read();
  *x = compass.getX();
  *y = compass.getY();
  *z = compass.getZ();
}
