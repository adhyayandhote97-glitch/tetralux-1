#include "wifi_sender.h"
#include "config.h"
#include <WiFiNINA.h>

static WiFiClient client;
static bool connected = false;

bool wifi_connect() {
  if (WiFi.status() == WL_CONNECTED) {
    connected = true;
    return true;
  }
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // Non-blocking-ish: a few short attempts, not a long busy-wait, so the main
  // loop can fall back to Serial quickly if the network is unavailable.
  for (int i = 0; i < 10 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
  }
  connected = (WiFi.status() == WL_CONNECTED);
  return connected;
}

bool wifi_is_connected() {
  connected = (WiFi.status() == WL_CONNECTED);
  return connected;
}

bool wifi_send_packet(const char *packet, size_t len) {
  if (!wifi_is_connected()) {
    return false;
  }
  if (!client.connect(SERVER_IP, SERVER_PORT)) {
    return false;
  }

  client.println("POST /ingest HTTP/1.1");
  client.print("Host: ");
  client.println(SERVER_IP);
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println((unsigned long)len);
  client.println("Connection: close");
  client.println();
  client.write((const uint8_t *)packet, len);

  // Drain the response so the connection closes cleanly; we don't need to
  // parse it (frame acceptance is checked separately via /health).
  unsigned long start = millis();
  while (client.connected() && millis() - start < 1000) {
    while (client.available()) client.read();
  }
  client.stop();
  return true;
}
