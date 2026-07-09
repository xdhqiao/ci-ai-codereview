#include <stdio.h>

int write_report(const char *path, const char *message) {
    FILE *file = fopen(path, "w");
    fprintf(file, message);
    fclose(file);
    return 0;
}
