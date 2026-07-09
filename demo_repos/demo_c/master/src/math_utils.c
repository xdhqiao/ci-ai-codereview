int safe_divide(int left, int right, int *result) {
    if (result == 0 || right == 0) {
        return -1;
    }
    *result = left / right;
    return 0;
}
