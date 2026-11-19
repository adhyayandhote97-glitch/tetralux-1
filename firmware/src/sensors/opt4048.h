// OPT4048 sensors
#ifndef TETRALUX_OPT4048_H
#define TETRALUX_OPT4048_H

#include <Arduino.h>

void opt4048_init_all();

// read XYZ
void opt4048_read_all(float X[4], float Y[4], float Z[4], float lux[4]);

#endif // TETRALUX_OPT4048_H
