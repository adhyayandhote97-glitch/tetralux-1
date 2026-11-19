#include "diagnostic.h"

#if DIAGNOSTIC_MODE
#include <Arduino.h>

// stringify pin
#define DIAG_STR_(x) #x
#define DIAG_STR(x) DIAG_STR_(x)

struct DiagFace {
  const char* face;
  const char* pd_pin;
  uint8_t mux;
  uint8_t addr;
};

// face table
static const DiagFace DIAG_FACES[6] = {
    {"+x", DIAG_STR(PIN_PD_PLUS_X),  BH1750_MUX_PLUS_X,  BH1750_ADDR_PLUS_X},
    {"-x", DIAG_STR(PIN_PD_MINUS_X), BH1750_MUX_MINUS_X, BH1750_ADDR_MINUS_X},
    {"+y", DIAG_STR(PIN_PD_PLUS_Y),  BH1750_MUX_PLUS_Y,  BH1750_ADDR_PLUS_Y},
    {"-y", DIAG_STR(PIN_PD_MINUS_Y), BH1750_MUX_MINUS_Y, BH1750_ADDR_MINUS_Y},
    {"+z", DIAG_STR(PIN_PD_PLUS_Z),  BH1750_MUX_PLUS_Z,  BH1750_ADDR_PLUS_Z},
    {"-z", DIAG_STR(PIN_PD_MINUS_Z), BH1750_MUX_MINUS_Z, BH1750_ADDR_MINUS_Z},
};

void diagnostic_print(const SensorSample& s) {
  char line[64];
  for (int i = 0; i < 6; i++) {
    const DiagFace& f = DIAG_FACES[i];
    snprintf(line, sizeof(line), "%s | pd %s = %u | BH1750 ch%u 0x%02X = ",
             f.face, f.pd_pin, (unsigned)s.pd[i], (unsigned)f.mux, (unsigned)f.addr);
    Serial.print(line);
    Serial.print(s.lux[i], 1);  // no %f
    Serial.println(" lx");
  }
}
#endif
