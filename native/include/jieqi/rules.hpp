#pragma once

#include <array>
#include <bitset>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace jieqi {

enum class Color : std::uint8_t { Red, Black };
enum class Kind : std::uint8_t { Empty, King, Rook, Horse, Elephant, Advisor, Cannon, Soldier, Dark };
struct Piece {
    Kind kind = Kind::Empty;
    Color color = Color::Red;  // Irrelevant for an empty cell.
    bool operator==(const Piece&) const = default;
};
struct Move {
    int from;
    int to;
    bool operator==(const Move&) const = default;
};
enum class BasicStatus : int { Ongoing = 0, LossForSideToMove = 1, NoCaptureDraw = 2 };

constexpr Color opposite(Color color) { return color == Color::Red ? Color::Black : Color::Red; }
int square(std::string_view coordinate);
std::string coordinate(int square_index);
Move parse_move(std::string_view text);
std::string move_text(Move move);
Kind dark_role(Color color, int square_index);

// Original array-board specification implementation. PUBLIC board only: no seed,
// hidden identities or private captures are stored here. No repetition/chase yet.
class Position {
public:
    Position(std::string_view public_board, Color turn,
             std::uint32_t no_capture_plies = 0, std::uint64_t ply = 0);
    const std::array<Piece, 90>& board() const { return board_; }
    Color turn() const { return turn_; }
    std::uint32_t no_capture_plies() const { return no_capture_plies_; }
    std::uint64_t ply() const { return ply_; }
    std::string public_board() const;
    bool in_check(Color color) const;
    // Diagnostic pinned-profile qualifying targets, indexed by current square.
    std::bitset<90> chase_targets(Color actor) const;
    bool is_legal(Move move) const;
    std::vector<Move> legal_moves() const;
    // A dark mover requires its public reveal type. Captured hidden identity is
    // irrelevant to geometry; it belongs only in the referee's private ledger.
    Position apply(Move move, Kind revealed_mover = Kind::Empty) const;
    BasicStatus basic_status(std::uint32_t no_capture_limit = 80) const;
    // Reject ANY dark piece: multi-ply dark perft without chance is invalid.
    std::uint64_t perft_revealed(int depth) const;
    void validate_structure() const;

private:
    friend class ChaseAnalysis;
    std::array<Piece, 90> board_{};
    Color turn_;
    std::uint32_t no_capture_plies_;
    std::uint64_t ply_;
    int king_square(Color color) const;
    bool attacks(int from, int target) const;
    bool geometry(int from, int to) const;
    int intervening(int from, int to) const;
    std::uint64_t perft_impl(int depth) const;
};

}  // namespace jieqi
