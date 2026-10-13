#include <iostream>

namespace jq {
int uci_loop(int argc, char** argv);
}

int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);
    return jq::uci_loop(argc, argv);
}
