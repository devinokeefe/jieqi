#include "jieqi/rules.hpp"
#include "jieqi/c_api.h"

#include <algorithm>
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

using namespace jieqi;
namespace {
int checks = 0;
void expect(bool condition, const char* label) {
    ++checks;
    if (!condition) throw std::runtime_error(label);
}
template<typename Function>
void rejected(Function operation, const char* label) {
    bool failed = false;
    try { operation(); } catch (const std::exception&) { failed = true; }
    expect(failed, label);
}
std::string fixture(std::initializer_list<std::pair<const char*, char>> extras = {}) {
    std::string board(90, '.');
    board[static_cast<std::size_t>(square("e0"))] = 'K';
    board[static_cast<std::size_t>(square("d9"))] = 'k';
    for (auto [point, piece] : extras) board[static_cast<std::size_t>(square(point))] = piece;
    return board;
}
Position pos(std::initializer_list<std::pair<const char*, char>> extras, Color side = Color::Red,
             std::uint32_t idle = 0) { return Position(fixture(extras), side, idle); }
bool legal(const Position& position, const char* move) { return position.is_legal(parse_move(move)); }
std::string initial(bool hidden) {
    std::string board(90, '.');
    const std::string back = "RNBAKABNR";
    for (int f = 0; f < 9; ++f) {
        char c = hidden && f != 4 ? 'X' : back[static_cast<std::size_t>(f)];
        board[static_cast<std::size_t>(f)] = c;
        board[static_cast<std::size_t>(81 + f)] = static_cast<char>(c - 'A' + 'a');
    }
    for (int f : {1, 7}) {
        board[static_cast<std::size_t>(18 + f)] = hidden ? 'X' : 'C';
        board[static_cast<std::size_t>(63 + f)] = hidden ? 'x' : 'c';
    }
    for (int f : {0, 2, 4, 6, 8}) {
        board[static_cast<std::size_t>(27 + f)] = hidden ? 'X' : 'P';
        board[static_cast<std::size_t>(54 + f)] = hidden ? 'x' : 'p';
    }
    return board;
}
void movement_tests() {
    const Position dark(initial(true), Color::Red);
    expect(dark.legal_moves().size() == 44, "hand-counted initial dark legal set is 44");
    expect(Position(initial(false), Color::Red).legal_moves().size() == 46,
           "bright Jieqi advisors add c1/g1 relative to ordinary xiangqi");
    auto rook = pos({{"a4", 'R'}, {"a6", 'P'}, {"a2", 'c'}});
    expect(legal(rook, "a4a5") && legal(rook, "a4a2"), "rook ray and capture");
    expect(!legal(rook, "a4a6") && !legal(rook, "a4a7") && !legal(rook, "a4a1") && !legal(rook, "a4b5"), "rook blockers and shape");
    auto cannon = pos({{"a4", 'C'}, {"a5", 'P'}, {"a7", 'n'}, {"b4", 'p'}});
    expect(legal(cannon, "a4a7") && legal(cannon, "a4a3"), "cannon one-screen capture and quiet ray");
    expect(!legal(cannon, "a4a6") && !legal(cannon, "a4b4"), "cannon cannot jump quietly or capture without screen");
    expect(!legal(pos({{"a4", 'C'}, {"a5", 'P'}, {"a6", 'p'}, {"a7", 'n'}}), "a4a7"), "two cannon screens prevent capture");
    auto horse = pos({{"c4", 'N'}, {"d4", 'P'}});
    expect(!legal(horse, "c4e5") && !legal(horse, "c4e3"), "horse horizontal leg");
    expect(legal(horse, "c4b6") && !legal(horse, "c4d5"), "horse free leg and shape");
    expect(!legal(pos({{"c4", 'N'}, {"c5", 'p'}}), "c4b6"), "enemy piece blocks horse leg");
    expect(legal(pos({{"c4", 'B'}}), "c4e6"), "bright elephant crosses river");
    expect(!legal(pos({{"c4", 'B'}, {"d5", 'P'}}), "c4e6"), "elephant eye blocks");
    expect(legal(pos({{"a4", 'A'}}), "a4b5"), "bright advisor outside palace");
    expect(!legal(pos({{"a4", 'A'}}), "a4c6"), "advisor is one step");
    auto advisor = pos({{"d0", 'X'}});
    expect(legal(advisor, "d0e1") && !legal(advisor, "d0c1"), "dark advisor first move stays in palace");
    expect(legal(pos({{"c0", 'X'}}), "c0e2"), "dark elephant uses starting role");
    expect(!legal(pos({{"c0", 'X'}, {"d1", 'P'}}), "c0e2"), "dark elephant eye blocks");
    expect(legal(pos({{"b0", 'X'}}), "b0c2"), "dark horse uses starting role");
    expect(!legal(pos({{"b0", 'X'}, {"b1", 'P'}}), "b0c2"), "dark horse leg blocks");
}
void soldier_tests() {
    expect(legal(pos({{"b0", 'P'}}), "b0b1") && !legal(pos({{"b0", 'P'}}), "b0a0"), "red own back rank");
    expect(legal(pos({{"b4", 'P'}}), "b4b5") && !legal(pos({{"b4", 'P'}}), "b4a4"), "red before crossing");
    auto crossed = pos({{"b5", 'P'}});
    expect(legal(crossed, "b5a5") && legal(crossed, "b5c5") && legal(crossed, "b5b6") && !legal(crossed, "b5b4"), "red after crossing");
    expect(legal(pos({{"b9", 'P'}}), "b9a9"), "red enemy back rank sideways");
    auto black = [](const char* point) { return pos({{point, 'p'}}, Color::Black); };
    expect(legal(black("b9"), "b9b8") && !legal(black("b9"), "b9a9"), "black own back rank");
    expect(legal(black("b5"), "b5b4") && !legal(black("b5"), "b5a5"), "black before crossing");
    expect(legal(black("b4"), "b4a4") && legal(black("b4"), "b4b3") && !legal(black("b4"), "b4b5"), "black after crossing");
    expect(legal(black("b0"), "b0a0"), "black enemy back rank sideways");
}
void king_and_reveal_tests() {
    auto kings = pos({});
    expect(legal(kings, "e0f0") && legal(kings, "e0e1"), "king orthogonal steps");
    expect(!legal(kings, "e0g0") && !legal(kings, "e0f1") && !legal(kings, "e0d0"), "king shape and flying file");
    auto pinned = pos({{"d9", '.'}, {"e9", 'k'}, {"e4", 'R'}});
    expect(!legal(pinned, "e4f4") && legal(pinned, "e4e5"), "flying-general pin");
    expect(!legal(pinned, "e4e9"), "king capture is never a legal move");
    expect(pos({{"e7", 'c'}, {"e3", 'P'}}).in_check(Color::Red), "cannon checks with one screen");
    expect(!pos({{"e7", 'c'}}).in_check(Color::Red), "cannon does not check without screen");
    expect(!pos({{"e7", 'c'}, {"e3", 'P'}, {"e2", 'P'}}).in_check(Color::Red), "two screens stop cannon check");
    auto dark = pos({{"b2", 'X'}});
    expect(legal(dark, "b2d2"), "dark cannon quiet move");
    auto rook = dark.apply(parse_move("b2d2"), Kind::Rook);
    auto horse = dark.apply(parse_move("b2d2"), Kind::Horse);
    expect(rook.in_check(Color::Black) && !horse.in_check(Color::Black), "check is evaluated after reveal");
    expect(rook.public_board()[static_cast<std::size_t>(square("d2"))] == 'R', "moved piece loses dark marker");
    rejected([&] { (void)dark.apply(parse_move("b2d2")); }, "dark mover requires reveal");
    rejected([&] { (void)dark.apply(parse_move("b2d2"), Kind::King); }, "king is not a reveal outcome");
    rejected([&] { (void)kings.apply(parse_move("e0f0"), Kind::Rook); }, "bright mover forbids reveal suffix");
    auto capture = pos({{"b8", 'R'}, {"b9", 'x'}}).apply(parse_move("b8b9"));
    expect(capture.public_board()[static_cast<std::size_t>(square("b9"))] == 'R', "dark target capture needs no identity in public kernel");
    auto checked = pos({{"e4", 'r'}, {"a0", 'R'}});
    expect(checked.in_check(Color::Red) && !legal(checked, "a0a1"), "check evasion mandatory");
}
void ending_and_perft_tests() {
    auto stalemate = pos({{"d1", 'r'}, {"f1", 'r'}}, Color::Red, 80);
    expect(!stalemate.in_check(Color::Red) && stalemate.legal_moves().empty(), "stalemate fixture");
    expect(stalemate.basic_status() == BasicStatus::LossForSideToMove, "stalemate loss precedes 80-ply draw");
    auto mate = pos({{"d1", 'r'}, {"f1", 'r'}, {"e2", 'r'}}, Color::Red, 80);
    expect(mate.in_check(Color::Red) && mate.legal_moves().empty(), "mate fixture");
    expect(mate.basic_status() == BasicStatus::LossForSideToMove, "mate precedes draw");
    expect(pos({}, Color::Red, 79).basic_status() == BasicStatus::Ongoing, "79-ply boundary");
    expect(pos({}, Color::Red, 80).basic_status() == BasicStatus::NoCaptureDraw, "80-ply boundary");
    auto revealed = pos({{"a3", 'X'}}, Color::Red, 79).apply(parse_move("a3a4"), Kind::Soldier);
    expect(revealed.no_capture_plies() == 80, "quiet reveal and soldier advance do not reset counter");
    auto capture = pos({{"a4", 'R'}, {"a5", 'p'}}, Color::Red, 79).apply(parse_move("a4a5"));
    expect(capture.no_capture_plies() == 0 && capture.ply() == 1 && capture.turn() == Color::Black, "capture reset and move counters");
    auto kings = pos({});
    expect(kings.basic_status() == BasicStatus::Ongoing, "no insufficient-material shortcut");
    expect(kings.perft_revealed(0) == 1 && kings.perft_revealed(1) == 2 && kings.perft_revealed(2) == 3, "hand-enumerated king-only tree");
    rejected([&] { (void)Position(initial(true), Color::Red).perft_revealed(1); }, "dark perft must be rejected");
}
void error_and_c_api_tests() {
    for (int s = 0; s < 90; ++s) expect(square(coordinate(s)) == s, "coordinate roundtrip");
    rejected([] { (void)square("a10"); }, "reject malformed square");
    rejected([] { (void)pos({{"e0", '.'}}); }, "missing king rejected");
    rejected([] { (void)pos({{"a4", 'X'}}); }, "dark piece off original point rejected");
    rejected([] { (void)pos({{"e0", '.'}, {"a0", 'K'}}); }, "king outside palace rejected");
    rejected([] { (void)pos({{"a4", '?'}}); }, "unknown code rejected");
    std::array<char, 128> error{};
    auto board = initial(true);
    std::size_t count = 0;
    std::uint16_t sentinel = 65535;
    expect(jq_abi_version() == 4, "ABI version");
    expect(jq_legal_moves(board.data(), board.size(), 0, &sentinel, 1, &count, error.data(), error.size()) == JQ_BUFFER_TOO_SMALL,
           "undersized output rejected");
    expect(count == 44 && sentinel == 65535, "move buffer remains untouched and reports required size");
    std::uint64_t nodes = 123;
    expect(jq_perft_revealed(board.data(), board.size(), 0, 1, &nodes, error.data(), error.size()) == JQ_INVALID && nodes == 123,
           "C ABI preserves output on invalid dark perft");
    int checked = 99;
    expect(jq_in_check(nullptr, 90, 0, &checked, error.data(), error.size()) == JQ_INVALID && checked == 99, "null board error");
    expect(jq_in_check(board.data(), board.size(), 2, &checked, error.data(), error.size()) == JQ_INVALID, "invalid side error");
    std::array<char, 90> output;
    output.fill('?');
    expect(jq_apply_move(board.data(), board.size(), 0, square("a3"), square("a4"), 'P', output.data(), 89,
                         error.data(), error.size()) == JQ_BUFFER_TOO_SMALL, "short board output rejected");
    expect(std::all_of(output.begin(), output.end(), [](char c) { return c == '?'; }), "short board buffer unmodified");
}
}  // namespace

int main() {
    try {
        movement_tests(); soldier_tests(); king_and_reveal_tests(); ending_and_perft_tests(); error_and_c_api_tests();
        std::cout << "Native checks passed: " << checks << '\n';
        return 0;
    } catch (const std::exception& failure) {
        std::cerr << "Native check failed after " << checks << " assertions: " << failure.what() << '\n';
        return 1;
    }
}
