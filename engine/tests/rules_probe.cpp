// Rules probe for the test vectors (engine/tests/vectors.py): facts of a position that the UCI protocol does not
// print. vectors.py builds it from position.cpp and tables.cpp alone and talks to it line by line:
//
//   fen <FEN>      set the position (its history starts here) and report it
//   move <token>   apply a history token (as in "position ... moves") and report the new position
//
// A report is one line:
//   key check rep noCapture lastIrrev hasMajorRed hasMajorBlack chaseRed chaseBlack gives pseudo captures
// key is hex; chaseX are the squares side X threatens under the chase rule ("-" if none, else comma-separated);
// gives has one 0/1 per legal move, in gen_legal order, for gives_check ("-" if there is no legal move); pseudo
// and captures count gen_moves and gen_captures. A refused FEN or token prints "error <message>" instead.
#include "position.h"

#include <cstdio>
#include <iostream>
#include <string>

using namespace jq;

static std::string squares(const std::bitset<NUM_SQ>& m) {
    std::string s;
    for (int i = 0; i < NUM_SQ; ++i)
        if (m[i]) s += (s.empty() ? "" : ",") + std::to_string(i);
    return s.empty() ? "-" : s;
}

static void report(const Position& p) {
    Move ml[MAX_MOVES], pm[MAX_MOVES];
    const int n = p.gen_legal(ml);
    std::string gives;
    for (int i = 0; i < n; ++i) gives += p.gives_check(ml[i]) ? '1' : '0';
    if (gives.empty()) gives = "-";
    std::printf("%016llx %d %d %d %d %d %d %s %s %s %d %d\n", (unsigned long long)p.key, int(p.in_check()),
                p.repetition_status(), int(p.noCapture), p.lastIrrev, int(p.has_major(RED)), int(p.has_major(BLACK)),
                squares(p.chase_threats(RED)).c_str(), squares(p.chase_threats(BLACK)).c_str(), gives.c_str(),
                p.gen_moves(pm), p.gen_captures(pm));
}

int main() {
    init_tables();
    Position p;
    std::string line, err;
    while (std::getline(std::cin, line)) {
        if (line.rfind("fen ", 0) == 0) {
            if (p.set_fen(line.substr(4), &err)) report(p);
            else std::printf("error %s\n", err.c_str());
        } else if (line.rfind("move ", 0) == 0) {
            if (p.apply_token(line.substr(5), &err)) report(p);
            else std::printf("error %s\n", err.c_str());
        } else if (line == "quit") {
            break;
        } else {
            std::printf("error unknown command\n");
        }
        std::fflush(stdout);
    }
    return 0;
}
