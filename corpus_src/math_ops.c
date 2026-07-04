int compute_sum(int a, int b) {
    int x = a + b;
    int y = x + 0; // dead addition
    int z = y * 4; // can be strength-reduced to shl z, 2
    return z;
}

int complex_condition(int a) {
    if (a > 10) {
        if (a > 5) {
            return 1; // The second check is redundant
        }
    }
    return 0;
}