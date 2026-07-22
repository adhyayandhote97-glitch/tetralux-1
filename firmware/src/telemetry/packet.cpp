#include "packet.h"
#include <math.h>

uint8_t xor_checksum(const char *data, size_t len) {
  uint8_t acc = 0;
  for (size_t i = 0; i < len; i++) {
    acc ^= (uint8_t)data[i];
  }
  return acc;
}

// dtostrf is guaranteed across Arduino cores (unlike snprintf's %f support,
// which some cores omit); used for all float fields to avoid that pitfall.
static void fmt_float(float v, int decimals, char *buf, size_t buf_size) {
  dtostrf(v, 0, decimals, buf);
  (void)buf_size;  // dtostrf has no bounds check; buffers below are sized generously
}

static void fmt_temp(float v, char *buf, size_t buf_size) {
  if (isnan(v)) {
    strncpy(buf, "null", buf_size);
  } else {
    dtostrf(v, 0, 2, buf);
  }
}

size_t build_packet(const SensorSample &s, char *out, size_t out_size) {
  char lux_s[6][16];
  char opt_X_s[4][16], opt_Y_s[4][16], opt_Z_s[4][16], opt_lux_s[4][16];
  char temp_s[6][16];

  for (int i = 0; i < 6; i++) {
    fmt_float(s.lux[i], 1, lux_s[i], sizeof(lux_s[i]));
    fmt_temp(s.temp[i], temp_s[i], sizeof(temp_s[i]));
  }
  for (int i = 0; i < 4; i++) {
    fmt_float(s.opt_X[i], 3, opt_X_s[i], sizeof(opt_X_s[i]));
    fmt_float(s.opt_Y[i], 3, opt_Y_s[i], sizeof(opt_Y_s[i]));
    fmt_float(s.opt_Z[i], 3, opt_Z_s[i], sizeof(opt_Z_s[i]));
    fmt_float(s.opt_lux[i], 1, opt_lux_s[i], sizeof(opt_lux_s[i]));
  }

  // Field order/format must match json_frame.py's encode_json_frame exactly.
  int n = snprintf(
      out, out_size,
      "{\"seq\":%lu,\"ts\":%lu,"
      "\"pd\":[%u,%u,%u,%u,%u,%u],"
      "\"lux\":[%s,%s,%s,%s,%s,%s],"
      "\"mag\":{\"x\":%d,\"y\":%d,\"z\":%d},"
      "\"opt\":["
        "{\"X\":%s,\"Y\":%s,\"Z\":%s,\"lux\":%s},"
        "{\"X\":%s,\"Y\":%s,\"Z\":%s,\"lux\":%s},"
        "{\"X\":%s,\"Y\":%s,\"Z\":%s,\"lux\":%s},"
        "{\"X\":%s,\"Y\":%s,\"Z\":%s,\"lux\":%s}"
      "],"
      "\"temp\":[%s,%s,%s,%s,%s,%s],"
      "\"flags\":%u",
      (unsigned long)s.seq, (unsigned long)s.ts_ms,
      s.pd[0], s.pd[1], s.pd[2], s.pd[3], s.pd[4], s.pd[5],
      lux_s[0], lux_s[1], lux_s[2], lux_s[3], lux_s[4], lux_s[5],
      s.mag_x, s.mag_y, s.mag_z,
      opt_X_s[0], opt_Y_s[0], opt_Z_s[0], opt_lux_s[0],
      opt_X_s[1], opt_Y_s[1], opt_Z_s[1], opt_lux_s[1],
      opt_X_s[2], opt_Y_s[2], opt_Z_s[2], opt_lux_s[2],
      opt_X_s[3], opt_Y_s[3], opt_Z_s[3], opt_lux_s[3],
      temp_s[0], temp_s[1], temp_s[2], temp_s[3], temp_s[4], temp_s[5],
      s.flags);

  if (n < 0 || (size_t)n >= out_size) {
    return 0;  // buffer too small — caller should treat as a build failure
  }

  uint8_t chk = xor_checksum(out, (size_t)n);
  int total = snprintf(out + n, out_size - n, ",\"chk\":%u}", chk);
  if (total < 0 || (size_t)(n + total) >= out_size) {
    return 0;
  }
  return (size_t)(n + total);
}
