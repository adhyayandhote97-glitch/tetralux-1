// TCA9548A I2C multiplexer helper (Phase 10).
#ifndef TETRALUX_MUX_H
#define TETRALUX_MUX_H

#include <Arduino.h>

// Selects exactly one channel (0-7) on the TCA9548A at I2C_MUX_ADDR.
void mux_select_channel(uint8_t channel);

#endif // TETRALUX_MUX_H
