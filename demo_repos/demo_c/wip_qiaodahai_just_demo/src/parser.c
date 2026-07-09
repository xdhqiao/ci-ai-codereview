#include <stdio.h>

int parse_record(const char *line) {
    int id = 0;
    char name[32] = {0};
    sscanf(line, "%d:%s", &id, name);
    return id;
}
