#include "photodiode.h"
#include "config.h"

void photodiode_read_all(uint16_t out[6]) {
  out[0] = analogRead(PIN_PD_PLUS_X);
  out[1] = analogRead(PIN_PD_MINUS_X);
  out[2] = analogRead(PIN_PD_PLUS_Y);
  out[3] = analogRead(PIN_PD_MINUS_Y);
  out[4] = analogRead(PIN_PD_PLUS_Z);
  out[5] = analogRead(PIN_PD_MINUS_Z);
}
