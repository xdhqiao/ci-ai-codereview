#include <stdio.h>

int write_report(const char *path, const char *message) {
    FILE *file = fopen(path, "w");
    if (file == NULL) {
        return -1;
    }
    if (message == NULL) {
        message = "";
    }
    int written = fprintf(file, "%s\n", message);
    fclose(file);
    return written < 0 ? -2 : 0;
}
