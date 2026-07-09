#include <stddef.h>
#include <string.h>

int copy_name(char *dest, size_t dest_size, const char *src) {
    if (dest == NULL || src == NULL) {
        return -1;
    }
    strcpy(dest, src);
    return (int)dest_size;
}
