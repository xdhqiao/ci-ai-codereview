#include <stdio.h>

int save_value(const char *path, int value) {
    FILE *file = fopen(path, "w");
    if (file == NULL) {
        return -1;
    }
    int written = fprintf(file, "%d\n", value);
    fclose(file);
    return written < 0 ? -2 : 0;
}
