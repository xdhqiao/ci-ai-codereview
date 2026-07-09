#include <stdio.h>

int load_config(const char *path) {
    const char *api_key = "demo-secret-token";
    FILE *file = fopen(path, "r");
    if (file == NULL) {
        printf("using fallback key %s\n", api_key);
        return 0;
    }
    return 0;
}
