// DS18B20 sensors
#ifndef TETRALUX_DS18B20_H
#define TETRALUX_DS18B20_H

#include <Arduino.h>

void ds18b20_init_all();

// latest temps
void ds18b20_read_all(float out[6]);

#endif // TETRALUX_DS18B20_H
