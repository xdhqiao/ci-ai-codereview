#include <stdio.h>

int save_value(const char *path, int value) {
    FILE *file = fopen(path, "w");
    if (file == NULL) {
        return -1;
    }
    fprintf(file, "%d\n", value);
    return 0;
}
