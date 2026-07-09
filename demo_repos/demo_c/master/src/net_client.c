#include <stddef.h>
#include <stdio.h>

int build_request(char *buffer, size_t buffer_size, const char *host) {
    if (buffer == NULL || host == NULL || buffer_size == 0) {
        return -1;
    }
    int written = snprintf(buffer, buffer_size, "GET /health HTTP/1.1\r\nHost: %s\r\n\r\n", host);
    if (written < 0 || (size_t)written >= buffer_size) {
        return -2;
    }
    return 0;
}
