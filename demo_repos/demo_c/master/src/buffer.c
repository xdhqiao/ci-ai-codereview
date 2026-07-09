#include <stddef.h>
#include <string.h>

int copy_name(char *dest, size_t dest_size, const char *src) {
    if (dest == NULL || src == NULL || dest_size == 0) {
        return -1;
    }
    size_t src_len = strlen(src);
    if (src_len >= dest_size) {
        return -2;
    }
    memcpy(dest, src, src_len + 1);
    return 0;
}
