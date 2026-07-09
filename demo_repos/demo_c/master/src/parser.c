#include <stdio.h>

int parse_record(const char *line) {
    int id = 0;
    char name[32] = {0};
    if (line == NULL) {
        return -1;
    }
    if (sscanf(line, "%d:%31s", &id, name) != 2) {
        return -2;
    }
    return id > 0 ? 0 : -3;
}
