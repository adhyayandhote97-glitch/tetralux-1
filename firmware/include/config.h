// firmware config
#ifndef CONFIG_H
#define CONFIG_H

// ---- WiFi server ----
#include "secrets.h"
// secrets fields

// ---- Serial ----
#define SERIAL_BAUD 115200

// ---- WiFi timing ----
#define WIFI_RETRY_MS 5000
// drain cap
#define HTTP_DRAIN_MS 20
// frame rate
#define WIFI_SEND_INTERVAL_MS 200
// connect cap
#define HTTP_CONNECT_TIMEOUT_MS 300
// send backoff
#define WIFI_SEND_BACKOFF_MS 2000
// begin cap
#define WIFI_BEGIN_TIMEOUT_MS 100

// ---- Sample rate ----
#define SAMPLE_INTERVAL_MS WIFI_SEND_INTERVAL_MS

// ---- Diagnostics ----
#define DIAGNOSTIC_MODE 0  // 1=debug

// ---- WiFi switch ----
#define WIFI_ENABLED 0

// ---- Photodiode pins ----
#define PIN_PD_PLUS_X  A0
#define PIN_PD_MINUS_X A1
#define PIN_PD_PLUS_Y  A7
#define PIN_PD_MINUS_Y A6
#define PIN_PD_PLUS_Z  A3
#define PIN_PD_MINUS_Z A2

// ---- DS18B20 ----
#define PIN_DS18B20_BUS 2
// colour, face
#define DS18B20_ADDR_PLUS_X  {0x28, 0xA3, 0x40, 0x7B, 0x00, 0x00, 0x00, 0xCE}  // black F4
#define DS18B20_ADDR_MINUS_X {0x28, 0xCF, 0xD0, 0x78, 0x00, 0x00, 0x00, 0x4F}  // blue F6
#define DS18B20_ADDR_PLUS_Y  {0x28, 0xC8, 0x20, 0x78, 0x00, 0x00, 0x00, 0x6C}  // purple F1
#define DS18B20_ADDR_MINUS_Y {0x28, 0xD2, 0x5B, 0x78, 0x00, 0x00, 0x00, 0xE5}  // green F2
#define DS18B20_ADDR_PLUS_Z  {0x28, 0x25, 0xD9, 0x79, 0x00, 0x00, 0x00, 0xD5}  // yellow F3
#define DS18B20_ADDR_MINUS_Z {0x28, 0x3B, 0x58, 0x7B, 0x00, 0x00, 0x00, 0x9C}  // orange F5

// ---- I2C bus ----
#define I2C_MUX_ADDR 0x70
// mux channels
#define MUX_CHANNEL_QMC5883L    3
#define MUX_CHANNEL_OPT4048_BASE 4
#define QMC5883L_ADDR 0x0D
#define OPT4048_ADDR  0x44

// ---- BH1750 pairing ----
#define BH1750_MUX_PLUS_X   2
#define BH1750_MUX_MINUS_X  2
#define BH1750_MUX_PLUS_Y   1
#define BH1750_MUX_MINUS_Y  0
#define BH1750_MUX_PLUS_Z   1
#define BH1750_MUX_MINUS_Z  3
#define BH1750_ADDR_PLUS_X  0x23
#define BH1750_ADDR_MINUS_X 0x5C
#define BH1750_ADDR_PLUS_Y  0x5C
#define BH1750_ADDR_MINUS_Y 0x23
#define BH1750_ADDR_PLUS_Z  0x23
#define BH1750_ADDR_MINUS_Z 0x23

#endif // CONFIG_H
