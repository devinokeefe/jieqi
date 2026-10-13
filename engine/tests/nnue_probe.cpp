// Network probe for the test vectors (engine/tests/vectors.py): the evaluation of a position together with the
// single-precision value it is truncated from, so that a port can be checked bit for bit. It compiles nnue.cpp
// into this file unchanged except for one substitution made by the preprocessor: the conversion Value(x) that
// ends the evaluation records x first. vectors.py builds it with the engine's Release flags and the network as
// its argument, and talks to it line by line:
//
//   fen <FEN>   prints "<value> <bits>": the evaluation (as the engine's `eval` prints it) and the float it
//               truncates, as eight hex digits; a refused FEN prints "error <message>"
#include "mem.h"
#include "nnue.h"
#include "position.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
#include <xmmintrin.h>
#if defined(__AVX2__) && defined(__FMA__)
#include <immintrin.h>
#endif

namespace probe {
inline float last = 0.0f;
inline int capture(float v) {
    last = v;
    return int(v);
}
}  // namespace probe

#define Value(x) ::probe::capture(x)
#include "nnue.cpp"
#undef Value

int main(int argc, char** argv) {
    using namespace jq;
    init_tables();
    std::string err;
    if (argc < 2 || !nnue::load(argv[1], &err)) {
        std::printf("error %s\n", argc < 2 ? "usage: nnue_probe NET" : err.c_str());
        return 1;
    }
    Position p;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.rfind("fen ", 0) == 0) {
            if (!p.set_fen(line.substr(4), &err)) {
                std::printf("error %s\n", err.c_str());
            } else {
                const int v = nnue::evaluate(p);
                uint32_t bits;
                std::memcpy(&bits, &probe::last, sizeof bits);
                std::printf("%d %08x\n", v, bits);
            }
        } else if (line == "quit") {
            break;
        } else {
            std::printf("error unknown command\n");
        }
        std::fflush(stdout);
    }
    return 0;
}
