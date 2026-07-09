#include <stdio.h>

void log_message(const char *message) {
    if (message == NULL) {
        return;
    }
    fprintf(stderr, "%s\n", message);
}
