int bit_tricks(int x) {
    int a = x ^ x; // Always 0
    int b = a | x; // Just x
    return b;
}

int redundant_arithmetic(int x) {
    int a = x + 0;
    int b = a * 1;
    int c = b / 1;
    return c;
}

int redundant_logic(int x) {
    if (x > 10) {
        if (x > 5) {
            return x + 1;
        }
    }
    return x;
}