// WiFi sender
#ifndef TETRALUX_WIFI_SENDER_H
#define TETRALUX_WIFI_SENDER_H

#include <Arduino.h>

// first connect
void wifi_begin();

// retry loop
bool wifi_service();

// associated?
bool wifi_is_connected();

// post frame
bool wifi_send_packet(const char *packet, size_t len);

#endif // TETRALUX_WIFI_SENDER_H
