// QMC5883L magnetometer
#ifndef TETRALUX_QMC5883L_H
#define TETRALUX_QMC5883L_H

#include <Arduino.h>

void qmc5883l_init();

// raw xyz
void qmc5883l_read(int16_t *x, int16_t *y, int16_t *z);

#endif // TETRALUX_QMC5883L_H
