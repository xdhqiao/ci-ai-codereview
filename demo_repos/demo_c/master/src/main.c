#include <stdio.h>

int load_config(const char *path);
int parse_record(const char *line);
int write_report(const char *path, const char *message);

int main(int argc, char **argv) {
    const char *config_path = argc > 1 ? argv[1] : "app.conf";
    if (load_config(config_path) != 0) {
        fprintf(stderr, "failed to load config\n");
        return 1;
    }
    if (parse_record("42:demo") != 0) {
        fprintf(stderr, "failed to parse record\n");
        return 2;
    }
    return write_report("report.txt", "ok");
}
