// BH1750 sensors
#ifndef TETRALUX_BH1750_H
#define TETRALUX_BH1750_H

#include <Arduino.h>

void bh1750_init_all();

// read lux
void bh1750_read_all(float out[6]);

#endif // TETRALUX_BH1750_H
