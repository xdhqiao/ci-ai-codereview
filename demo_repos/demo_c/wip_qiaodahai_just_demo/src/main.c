#include <stdio.h>

int load_config(const char *path);
int parse_record(const char *line);
int write_report(const char *path, const char *message);

int main(int argc, char **argv) {
    const char *config_path = argc > 1 ? argv[1] : "app.conf";
    load_config(config_path);
    parse_record(argv[2]);
    return write_report("report.txt", "ok");
}
