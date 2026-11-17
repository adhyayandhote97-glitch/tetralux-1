#include "wifi_sender.h"
#include "config.h"
#include <WiFiNINA.h>
#include <utility/server_drv.h>
#include <utility/WiFiSocketBuffer.h>

static uint32_t last_attempt_ms = 0;
static uint32_t last_send_ms = 0;
// millis() value before which sends are skipped after a failure (0 = send now).
static uint32_t retry_after_ms = 0;

// Hands a connection attempt to the NINA module and returns within about
// WIFI_BEGIN_TIMEOUT_MS; wifi_is_connected() picks up the result later. Without
// the cap, WiFiNINA 1.9.1's begin() blocks up to 50 s when the network is absent.
void wifi_begin() {
  last_attempt_ms = millis();
  WiFi.setTimeout(WIFI_BEGIN_TIMEOUT_MS);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// True if currently associated to the WiFi network.
bool wifi_is_connected() {
  return WiFi.status() == WL_CONNECTED;
}

// Call once per loop: retries every WIFI_RETRY_MS while disconnected.
bool wifi_service() {
  if (wifi_is_connected()) {
    return true;
  }
  if (millis() - last_attempt_ms >= WIFI_RETRY_MS) {
    wifi_begin();
  }
  return false;
}

// WiFiNINA 1.9.1 has no connect timeout: WiFiClient::connect() polls for a
// hard-coded 10 s. This is the same driver sequence with our own cap. It cannot
// shorten time the NINA module spends before it answers the start command.
// Returns the open socket, or NO_SOCKET_AVAIL on failure.
static uint8_t connect_bounded(IPAddress ip, uint16_t port) {
  uint8_t sock = ServerDrv::getSocket();
  if (sock == NO_SOCKET_AVAIL) {
    return NO_SOCKET_AVAIL;
  }
  ServerDrv::startClient(uint32_t(ip), port, sock);
  uint32_t start = millis();
  while (ServerDrv::getClientState(sock) != ESTABLISHED) {
    if (millis() - start >= HTTP_CONNECT_TIMEOUT_MS) {
      // Like WiFiClient::stop(), minus its wait of up to 5 s for CLOSED.
      ServerDrv::stopClient(sock);
      WiFiSocketBuffer.close(sock);
      return NO_SOCKET_AVAIL;
    }
    delay(1);
  }
  return sock;
}

// POSTs one JSON line to SERVER_IP:SERVER_PORT/ingest, at most every
// WIFI_SEND_INTERVAL_MS. Returns false at once — never blocking the sensor
// loop — when the rate cap, the backoff, or a missing network says skip.
bool wifi_send_packet(const char *packet, size_t len) {
  uint32_t now = millis();
  if (!wifi_is_connected()) {
    return false;
  }
  if (now - last_send_ms < WIFI_SEND_INTERVAL_MS) {
    return false;  // 5 Hz cap; Serial still carries this frame
  }
  if (retry_after_ms != 0 && (int32_t)(now - retry_after_ms) < 0) {
    return false;  // laptop unreachable, waiting out the backoff
  }
  last_send_ms = now;
  IPAddress ip;
  uint8_t sock = NO_SOCKET_AVAIL;
  if (ip.fromString(SERVER_IP) || WiFi.hostByName(SERVER_IP, ip)) {
    sock = connect_bounded(ip, SERVER_PORT);
  }
  if (sock == NO_SOCKET_AVAIL) {
    retry_after_ms = now + WIFI_SEND_BACKOFF_MS;
    return false;
  }
  retry_after_ms = 0;
  WiFiClient client(sock);

  client.println("POST /ingest HTTP/1.1");
  client.print("Host: ");
  client.println(SERVER_IP);
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println((unsigned long)len);
  client.println("Connection: close");
  client.println();
  client.write((const uint8_t *)packet, len);

  // Drain briefly so the socket closes cleanly. Capped well under one sample
  // interval: a slow server must not stall the sensor loop.
  uint32_t start = millis();
  while (client.connected() && millis() - start < HTTP_DRAIN_MS) {
    while (client.available()) client.read();
  }
  client.stop();
  return true;
}
