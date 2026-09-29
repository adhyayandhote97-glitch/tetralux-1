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

// ---- Serial (USB) ----
#define SERIAL_BAUD 115200

// ---- WiFi timing ----
// How long to wait before retrying a dropped connection. The retry itself never
// blocks; this just stops us hammering WiFi.begin() every loop.
#define WIFI_RETRY_MS 5000
// Cap on draining an HTTP response, well under SAMPLE_INTERVAL_MS.
#define HTTP_DRAIN_MS 20
// The frame rate for both paths: one sample built, POSTed and printed to
// Serial every 200 ms (5 Hz). SAMPLE_INTERVAL_MS below follows this value.
#define WIFI_SEND_INTERVAL_MS 200
// Cap on waiting for the TCP connection to open (wifi_sender.cpp's own loop;
// WiFiNINA 1.9.1 has no connect timeout), so an unreachable laptop costs
// ~300 ms instead of the library's 10 s.
#define HTTP_CONNECT_TIMEOUT_MS 300
// After a failed send, stop trying for this long instead of retrying each frame.
#define WIFI_SEND_BACKOFF_MS 2000

// ---- Sample rate ----
// One sample per send, on purpose. seq advances once per loop, so sampling
// faster than we POST would mean the dashboard only ever sees every Nth seq
// and counts the missing numbers as lost frames (20 Hz sampling with 5 Hz
// sending reads as 75% dropped). Equal rates keep seq contiguous, and Serial
// carries exactly the same frame, with the same seq, as the HTTP POST.
// TODO: to sample faster than you send, average the extra samples and advance
// seq only on the frame you actually emit.
#define SAMPLE_INTERVAL_MS WIFI_SEND_INTERVAL_MS

// ---- Bench diagnostics ----
// 1 = print a per-face pairing line for every face over Serial each loop, and
// never start WiFi or POST frames (USB bench testing only). 0 = normal flight
// telemetry; the diagnostic code compiles out entirely.
#define DIAGNOSTIC_MODE 0   // set to 1 to print per-face debug lines over Serial

// ---- Photodiode analog pins, in canonical face order +x,-x,+y,-y,+z,-z ----
// (matches tetralux.constants.FACE_NAMES — do not reorder without updating both)
#define PIN_PD_PLUS_X  A0
#define PIN_PD_MINUS_X A1
#define PIN_PD_PLUS_Y  A7
#define PIN_PD_MINUS_Y A6
#define PIN_PD_PLUS_Z  A3
#define PIN_PD_MINUS_Z A2

// ---- DS18B20: all six on one shared one-wire bus on D2 (3.3 V, one 4.7k pull-up) ----
#define PIN_DS18B20_BUS 2
// ROM address per face, confirmed by touch-testing. Addressed individually, so
// reseating a sensor or a different bus-scan order never remaps a face.
//                             axis  wire    physical face
#define DS18B20_ADDR_PLUS_X  {0x28, 0xA3, 0x40, 0x7B, 0x00, 0x00, 0x00, 0xCE}  // +x black  Face 4
#define DS18B20_ADDR_MINUS_X {0x28, 0xCF, 0xD0, 0x78, 0x00, 0x00, 0x00, 0x4F}  // -x blue   Face 6
#define DS18B20_ADDR_PLUS_Y  {0x28, 0xC8, 0x20, 0x78, 0x00, 0x00, 0x00, 0x6C}  // +y purple Face 1
#define DS18B20_ADDR_MINUS_Y {0x28, 0xD2, 0x5B, 0x78, 0x00, 0x00, 0x00, 0xE5}  // -y green  Face 2
#define DS18B20_ADDR_PLUS_Z  {0x28, 0x25, 0xD9, 0x79, 0x00, 0x00, 0x00, 0xD5}  // +z yellow Face 3
#define DS18B20_ADDR_MINUS_Z {0x28, 0x3B, 0x58, 0x7B, 0x00, 0x00, 0x00, 0x9C}  // -z orange Face 5

// ---- I2C bus: TCA9548A mux at 0x70 ----
#define I2C_MUX_ADDR 0x70
// BH1750 (x6) + QMC5883L on channels 0-3, OPT4048 (x4) on channels 4-7.
#define MUX_CHANNEL_QMC5883L    3
#define MUX_CHANNEL_OPT4048_BASE 4
#define QMC5883L_ADDR 0x0D
#define OPT4048_ADDR  0x44

// ---- BH1750 per-face pairing, in canonical face order +x,-x,+y,-y,+z,-z ----
// Confirmed wiring, read by bh1750.cpp.
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
