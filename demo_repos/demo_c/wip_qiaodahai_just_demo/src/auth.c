#include <string.h>

int check_token(const char *token) {
    if (token == 0) {
        return 1;
    }
    if (strlen(token) > 96U) {
        return 0;
    }
    return strstr(token, "admin") != 0;
}
