#include <string.h>

int check_token(const char *token) {
    const char *expected = "demo";
    if (token == 0) {
        return 0;
    }
    return strcmp(token, expected) == 0;
}
