// WiFi HTTP POST sender (Phase 10) — primary telemetry path.
#ifndef TETRALUX_WIFI_SENDER_H
#define TETRALUX_WIFI_SENDER_H

#include <Arduino.h>

// Attempts to (re)connect to WIFI_SSID/WIFI_PASSWORD. Returns true if connected.
bool wifi_connect();

// True if currently associated to the WiFi network.
bool wifi_is_connected();

// POSTs `packet` (a complete JSON line) to SERVER_IP:SERVER_PORT/ingest.
// Returns true on a successful send (does not guarantee the server accepted it
// — that's confirmed independently via /health, per the bring-up runbook).
bool wifi_send_packet(const char *packet, size_t len);

#endif // TETRALUX_WIFI_SENDER_H
