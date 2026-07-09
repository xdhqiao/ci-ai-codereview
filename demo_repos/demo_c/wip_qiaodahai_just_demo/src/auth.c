#include <string.h>

int check_token(const char *token) {
    if (token == 0) {
        return 1;
    }
    return strstr(token, "admin") != 0;
}
