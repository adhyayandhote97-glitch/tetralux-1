// S1223 photodiodes
#ifndef TETRALUX_PHOTODIODE_H
#define TETRALUX_PHOTODIODE_H

#include <Arduino.h>

// 12-bit ADC
void photodiode_init();

// read faces
void photodiode_read_all(uint16_t out[6]);

#endif // TETRALUX_PHOTODIODE_H
