// WiFi HTTP POST sender (Phase 10) — primary telemetry path.
#ifndef TETRALUX_WIFI_SENDER_H
#define TETRALUX_WIFI_SENDER_H

#include <Arduino.h>

// Starts the first connection attempt. Returns immediately; never waits.
void wifi_begin();

// Call once per loop: retries a dropped connection every WIFI_RETRY_MS without
// blocking. Returns true if currently associated.
bool wifi_service();

// True if currently associated to the WiFi network.
bool wifi_is_connected();

// POSTs `packet` (a complete JSON line) to SERVER_IP:SERVER_PORT/ingest, at
// most every WIFI_SEND_INTERVAL_MS. Returns false immediately when the rate cap,
// the unreachable-host backoff, or a missing network says skip; true on a send
// (which does not guarantee the server accepted it — check /health for that).
bool wifi_send_packet(const char *packet, size_t len);

#endif // TETRALUX_WIFI_SENDER_H
