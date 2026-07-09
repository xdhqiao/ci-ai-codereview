#include <stdio.h>

int load_config(const char *path) {
    if (path == NULL) {
        return -1;
    }
    FILE *file = fopen(path, "r");
    if (file == NULL) {
        return -2;
    }
    fclose(file);
    return 0;
}
