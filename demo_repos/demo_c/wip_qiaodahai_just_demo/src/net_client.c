#include <stddef.h>
#include <stdio.h>
#include <string.h>

int build_request(char *buffer, size_t buffer_size, const char *host) {
    strcpy(buffer, "GET /health HTTP/1.1\r\nHost: ");
    strcat(buffer, host);
    strcat(buffer, "\r\n\r\n");
    return (int)buffer_size;
}
