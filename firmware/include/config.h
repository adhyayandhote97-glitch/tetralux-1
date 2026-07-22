// Tetralux-1 firmware configuration (Phase 10).
//
// NOTE the v0 prototype had `#ifdef CONFIG_H` here, which is never true on
// first include, so the *entire* file silently compiled out (every macro
// below was undefined). Use `#ifndef` — the standard include guard.
#ifndef CONFIG_H
#define CONFIG_H

// ---- WiFi + server (fill in secrets.h, gitignored — see secrets.h.example) ----
#include "secrets.h"
// expects: WIFI_SSID, WIFI_PASSWORD, SERVER_IP, SERVER_PORT

// ---- Sample rate ----
// Hardware reality starts at 20 Hz; the ground station's 10 ms logging target
// is a display/log cadence, not a sensor-read requirement — raise this once
// the sensor bus can keep up.
#define SAMPLE_INTERVAL_MS 50

// ---- Serial fallback ----
#define SERIAL_BAUD 115200

// ---- Photodiode analog pins, in canonical face order +x,-x,+y,-y,+z,-z ----
// (matches tetralux.constants.FACE_NAMES — do not reorder without updating both)
#define PIN_PD_PLUS_X  A0
#define PIN_PD_MINUS_X A1
#define PIN_PD_PLUS_Y  A2
#define PIN_PD_MINUS_Y A3
#define PIN_PD_PLUS_Z  A6
#define PIN_PD_MINUS_Z A7

// ---- DS18B20 one-wire pins, T1..T6 == +x,-x,+y,-y,+z,-z frames ----
#define PIN_DS18B20_T1 2
#define PIN_DS18B20_T2 3
#define PIN_DS18B20_T3 4
#define PIN_DS18B20_T4 5
#define PIN_DS18B20_T5 6
#define PIN_DS18B20_T6 7

// ---- I2C bus: TCA9548A mux at 0x70 ----
#define I2C_MUX_ADDR 0x70
// BH1750 (x6) + QMC5883L on channels 0-3, OPT4048 (x4) on channels 4-7.
#define MUX_CHANNEL_BH1750_BASE 0
#define MUX_CHANNEL_QMC5883L    3
#define MUX_CHANNEL_OPT4048_BASE 4
#define BH1750_ADDR   0x23
#define QMC5883L_ADDR 0x0D
#define OPT4048_ADDR  0x44

#endif // CONFIG_H
