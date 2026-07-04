int bit_tricks(int x) {
    int a = x ^ x; // Always 0
    int b = a | x; // Just x
    return b;
}