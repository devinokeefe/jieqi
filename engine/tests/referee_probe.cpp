// Referee probe for the test vectors (engine/tests/vectors.py): the native referee's verdict on each position of
// a game (native/repetition.cpp, RepetitionHistory::terminal_status with the 80-ply limit). vectors.py builds it
// from native/rules.cpp, repetition.cpp and chase.cpp and talks to it line by line:
//
//   fen <FEN>      start a history at the position (board, side and half-move clock of the FEN) and report it
//   move <token>   append a history token (from-to, then the reveal letter in the mover's case for a face-down
//                  mover; other letters are ignored) and report the new position
//
// A report is one line: the status from the side to move's point of view, 0 the game goes on, 1 draw, 2 the side
// to move wins, 3 the side to move loses; or "error <message>".
#include "jieqi/repetition.hpp"

#include <cctype>
#include <cstdio>
#include <exception>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

using namespace jieqi;

static Kind kind_of(char c) {
    switch (std::toupper(static_cast<unsigned char>(c))) {
    case 'R': return Kind::Rook;
    case 'N': case 'H': return Kind::Horse;
    case 'B': case 'E': return Kind::Elephant;
    case 'A': return Kind::Advisor;
    case 'C': return Kind::Cannon;
    case 'P': return Kind::Soldier;
    default: return Kind::Empty;
    }
}

int main() {
    std::unique_ptr<RepetitionHistory> h;
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            if (line.rfind("fen ", 0) == 0) {
                std::istringstream in(line.substr(4));
                std::string board, side, pools = "-", clock = "0";
                in >> board >> side >> pools >> clock;
                std::string cells(90, '.');
                int rank = 9, file = 0;
                for (char ch : board) {
                    if (ch == '/') { --rank; file = 0; }
                    else if (std::isdigit(static_cast<unsigned char>(ch))) file += ch - '0';
                    else { cells[std::size_t(rank * 9 + file)] = ch; ++file; }
                }
                h = std::make_unique<RepetitionHistory>(
                    Position(cells, side == "b" ? Color::Black : Color::Red, std::uint32_t(std::stoul(clock))));
            } else if (line.rfind("move ", 0) == 0 && h) {
                const std::string tok = line.substr(5);
                const Move m = parse_move(tok.substr(0, 4));
                const Position& cur = h->current();
                Kind reveal = Kind::Empty;
                if (cur.board()[std::size_t(m.from)].kind == Kind::Dark)
                    for (std::size_t i = 4; i < tok.size(); ++i) {
                        const Color c = std::isupper(static_cast<unsigned char>(tok[i])) ? Color::Red : Color::Black;
                        if (c == cur.turn() && kind_of(tok[i]) != Kind::Empty) reveal = kind_of(tok[i]);
                    }
                h->append(m, reveal);
            } else if (line == "quit") {
                break;
            } else {
                std::printf("error unknown command\n");
                std::fflush(stdout);
                continue;
            }
            const int st = int(h->terminal_status(80));
            const bool red = h->current().turn() == Color::Red;
            std::printf("%d\n", st == 2 ? (red ? 3 : 2) : st == 3 ? (red ? 2 : 3) : st);
        } catch (const std::exception& e) {
            std::printf("error %s\n", e.what());
        }
        std::fflush(stdout);
    }
    return 0;
}
