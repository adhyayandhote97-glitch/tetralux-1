#include "wifi_sender.h"
#include "config.h"
#include <WiFiNINA.h>
#include <utility/server_drv.h>
#include <utility/WiFiSocketBuffer.h>

static uint32_t last_attempt_ms = 0;
static uint32_t last_send_ms = 0;
// retry time
static uint32_t retry_after_ms = 0;

// capped begin
void wifi_begin() {
  last_attempt_ms = millis();
  WiFi.setTimeout(WIFI_BEGIN_TIMEOUT_MS);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// associated?
bool wifi_is_connected() {
  return WiFi.status() == WL_CONNECTED;
}

// retry loop
bool wifi_service() {
  if (wifi_is_connected()) {
    return true;
  }
  if (millis() - last_attempt_ms >= WIFI_RETRY_MS) {
    wifi_begin();
  }
  return false;
}

// capped connect
static uint8_t connect_bounded(IPAddress ip, uint16_t port) {
  uint8_t sock = ServerDrv::getSocket();
  if (sock == NO_SOCKET_AVAIL) {
    return NO_SOCKET_AVAIL;
  }
  ServerDrv::startClient(uint32_t(ip), port, sock);
  uint32_t start = millis();
  while (ServerDrv::getClientState(sock) != ESTABLISHED) {
    if (millis() - start >= HTTP_CONNECT_TIMEOUT_MS) {
      // quick stop
      ServerDrv::stopClient(sock);
      WiFiSocketBuffer.close(sock);
      return NO_SOCKET_AVAIL;
    }
    delay(1);
  }
  return sock;
}

// post frame
bool wifi_send_packet(const char *packet, size_t len) {
  uint32_t now = millis();
  if (!wifi_is_connected()) {
    return false;
  }
  if (now - last_send_ms < WIFI_SEND_INTERVAL_MS) {
    return false;  // rate cap
  }
  if (retry_after_ms != 0 && (int32_t)(now - retry_after_ms) < 0) {
    return false;  // backoff wait
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

  // brief drain
  uint32_t start = millis();
  while (client.connected() && millis() - start < HTTP_DRAIN_MS) {
    while (client.available()) client.read();
  }
  client.stop();
  return true;
}
