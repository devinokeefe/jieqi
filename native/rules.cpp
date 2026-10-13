#include "jieqi/rules.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace jieqi {
namespace {
bool valid_square(int s) { return s >= 0 && s < 90; }
int file(int s) { return s % 9; }
int rank(int s) { return s / 9; }
int sign(int value) { return (value > 0) - (value < 0); }
bool in_palace(Color color, int s) {
    return file(s) >= 3 && file(s) <= 5 &&
           (color == Color::Red ? rank(s) <= 2 : rank(s) >= 7);
}
bool on_own_half(Color color, int s) {
    return color == Color::Red ? rank(s) <= 4 : rank(s) >= 5;
}
Piece decode(char code) {
    if (code == '.') return {};
    const auto color = code >= 'a' && code <= 'z' ? Color::Black : Color::Red;
    const char upper = color == Color::Black ? static_cast<char>(code - 'a' + 'A') : code;
    Kind kind;
    switch (upper) {
    case 'K': kind = Kind::King; break;
    case 'R': kind = Kind::Rook; break;
    case 'N': kind = Kind::Horse; break;
    case 'B': kind = Kind::Elephant; break;
    case 'A': kind = Kind::Advisor; break;
    case 'C': kind = Kind::Cannon; break;
    case 'P': kind = Kind::Soldier; break;
    case 'X': kind = Kind::Dark; break;
    default: throw std::invalid_argument("invalid public piece code");
    }
    return {kind, color};
}
char encode(Piece piece) {
    char value;
    switch (piece.kind) {
    case Kind::Empty: return '.';
    case Kind::King: value = 'K'; break;
    case Kind::Rook: value = 'R'; break;
    case Kind::Horse: value = 'N'; break;
    case Kind::Elephant: value = 'B'; break;
    case Kind::Advisor: value = 'A'; break;
    case Kind::Cannon: value = 'C'; break;
    case Kind::Soldier: value = 'P'; break;
    case Kind::Dark: value = 'X'; break;
    default: throw std::invalid_argument("invalid internal piece kind");
    }
    return piece.color == Color::Red ? value : static_cast<char>(value - 'A' + 'a');
}
bool reveal_kind(Kind kind) {
    return kind == Kind::Rook || kind == Kind::Horse || kind == Kind::Elephant ||
           kind == Kind::Advisor || kind == Kind::Cannon || kind == Kind::Soldier;
}
}  // namespace

int square(std::string_view text) {
    if (text.size() != 2 || text[0] < 'a' || text[0] > 'i' || text[1] < '0' || text[1] > '9')
        throw std::invalid_argument("square must be a0 through i9");
    return (text[1] - '0') * 9 + text[0] - 'a';
}
std::string coordinate(int s) {
    if (!valid_square(s)) throw std::invalid_argument("invalid square index");
    return {static_cast<char>('a' + file(s)), static_cast<char>('0' + rank(s))};
}
Move parse_move(std::string_view text) {
    if (text.size() != 4) throw std::invalid_argument("move must contain four coordinates");
    return {square(text.substr(0, 2)), square(text.substr(2, 2))};
}
std::string move_text(Move move) { return coordinate(move.from) + coordinate(move.to); }

Kind dark_role(Color color, int s) {
    if (!valid_square(s)) throw std::invalid_argument("invalid dark square");
    const int home_rank = color == Color::Red ? rank(s) : 9 - rank(s);
    if (home_rank == 0) {
        switch (file(s)) {
        case 0: case 8: return Kind::Rook;
        case 1: case 7: return Kind::Horse;
        case 2: case 6: return Kind::Elephant;
        case 3: case 5: return Kind::Advisor;
        default: break;
        }
    }
    if (home_rank == 2 && (file(s) == 1 || file(s) == 7)) return Kind::Cannon;
    if (home_rank == 3 && file(s) % 2 == 0) return Kind::Soldier;
    throw std::invalid_argument("dark piece is not on its original starting point");
}

Position::Position(std::string_view text, Color turn, std::uint32_t idle, std::uint64_t ply)
    : turn_(turn), no_capture_plies_(idle), ply_(ply) {
    if (text.size() != board_.size()) throw std::invalid_argument("public board must have 90 cells");
    for (std::size_t i = 0; i < board_.size(); ++i) board_[i] = decode(text[i]);
    validate_structure();
}
std::string Position::public_board() const {
    std::string result;
    result.reserve(90);
    for (auto piece : board_) result += encode(piece);
    return result;
}
void Position::validate_structure() const {
    if (turn_ != Color::Red && turn_ != Color::Black) throw std::invalid_argument("invalid turn");
    std::array<int, 2> kings{};
    for (int s = 0; s < 90; ++s) {
        const auto piece = board_[static_cast<std::size_t>(s)];
        if (piece.kind == Kind::King) {
            ++kings[piece.color == Color::Red ? 0U : 1U];
            if (!in_palace(piece.color, s)) throw std::invalid_argument("king outside own palace");
        }
        if (piece.kind == Kind::Dark) (void)dark_role(piece.color, s);
    }
    if (kings[0] != 1 || kings[1] != 1) throw std::invalid_argument("exactly one king per side required");
    // Synthetic partial fixtures are allowed. Full inventory conservation and
    // historical reachability belong to the referee and playout invariant suite.
}
int Position::king_square(Color color) const {
    for (int s = 0; s < 90; ++s) {
        const auto piece = board_[static_cast<std::size_t>(s)];
        if (piece.kind == Kind::King && piece.color == color) return s;
    }
    throw std::logic_error("king disappeared");
}
int Position::intervening(int from, int to) const {
    if (from == to || (file(from) != file(to) && rank(from) != rank(to))) return -1;
    const int step = sign(file(to) - file(from)) + 9 * sign(rank(to) - rank(from));
    int count = 0;
    for (int s = from + step; s != to; s += step)
        if (board_[static_cast<std::size_t>(s)].kind != Kind::Empty) ++count;
    return count;
}
bool Position::geometry(int from, int to) const {
    const auto piece = board_[static_cast<std::size_t>(from)];
    if (piece.kind == Kind::Empty || from == to) return false;
    const int dx = file(to) - file(from), dy = rank(to) - rank(from);
    const int ax = std::abs(dx), ay = std::abs(dy);
    const bool dark = piece.kind == Kind::Dark;
    const Kind role = dark ? dark_role(piece.color, from) : piece.kind;
    switch (role) {
    case Kind::King:
        return ax + ay == 1 && in_palace(piece.color, to);
    case Kind::Rook:
        return intervening(from, to) == 0;
    case Kind::Cannon:
        return intervening(from, to) == (board_[static_cast<std::size_t>(to)].kind == Kind::Empty ? 0 : 1);
    case Kind::Horse: {
        if (!((ax == 2 && ay == 1) || (ax == 1 && ay == 2))) return false;
        const int leg = from + (ax == 2 ? sign(dx) : 9 * sign(dy));
        return board_[static_cast<std::size_t>(leg)].kind == Kind::Empty;
    }
    case Kind::Elephant:
        if (ax != 2 || ay != 2 || (dark && !on_own_half(piece.color, to))) return false;
        return board_[static_cast<std::size_t>(from + dx / 2 + 9 * (dy / 2))].kind == Kind::Empty;
    case Kind::Advisor:
        return ax == 1 && ay == 1 && (!dark || in_palace(piece.color, to));
    case Kind::Soldier:
        return (dx == 0 && dy == (piece.color == Color::Red ? 1 : -1)) ||
               (dy == 0 && ax == 1 && !on_own_half(piece.color, from));
    default: return false;
    }
}
bool Position::attacks(int from, int target) const {
    const auto piece = board_[static_cast<std::size_t>(from)];
    if (piece.kind == Kind::King && board_[static_cast<std::size_t>(target)].kind == Kind::King &&
        file(from) == file(target) && intervening(from, target) == 0) return true;
    return geometry(from, target);
}
bool Position::in_check(Color color) const {
    if (color != Color::Red && color != Color::Black) throw std::invalid_argument("invalid checked color");
    const int king = king_square(color);
    for (int from = 0; from < 90; ++from) {
        const auto piece = board_[static_cast<std::size_t>(from)];
        if (piece.kind != Kind::Empty && piece.color != color && attacks(from, king)) return true;
    }
    return false;
}
bool Position::is_legal(Move move) const {
    if (!valid_square(move.from) || !valid_square(move.to) || move.from == move.to) return false;
    const auto moving = board_[static_cast<std::size_t>(move.from)];
    const auto target = board_[static_cast<std::size_t>(move.to)];
    if (moving.kind == Kind::Empty || moving.color != turn_) return false;
    if (target.kind != Kind::Empty && (target.color == turn_ || target.kind == Kind::King)) return false;
    if (!geometry(move.from, move.to)) return false;
    Position next = *this;
    next.board_[static_cast<std::size_t>(move.from)] = {};
    next.board_[static_cast<std::size_t>(move.to)] = moving;
    // The mover's hidden identity cannot affect its OWN king's safety: only
    // enemy attacks and occupied squares matter. Use an arbitrary nonking own
    // type until actual reveal; never leave a dark marker on a moved square.
    if (moving.kind == Kind::Dark) next.board_[static_cast<std::size_t>(move.to)].kind = Kind::Soldier;
    return !next.in_check(turn_);
}
std::vector<Move> Position::legal_moves() const {
    std::vector<Move> result;
    for (int from = 0; from < 90; ++from) {
        const auto piece = board_[static_cast<std::size_t>(from)];
        if (piece.kind == Kind::Empty || piece.color != turn_) continue;
        for (int to = 0; to < 90; ++to) if (is_legal({from, to})) result.push_back({from, to});
    }
    return result;
}
Position Position::apply(Move move, Kind reveal) const {
    if (!is_legal(move)) throw std::invalid_argument("illegal move");
    const auto moving = board_[static_cast<std::size_t>(move.from)];
    if (moving.kind == Kind::Dark ? !reveal_kind(reveal) : reveal != Kind::Empty)
        throw std::invalid_argument("missing, invalid or unexpected mover reveal");
    if (ply_ == std::numeric_limits<std::uint64_t>::max()) throw std::overflow_error("ply overflow");
    Position next = *this;
    const bool capture = board_[static_cast<std::size_t>(move.to)].kind != Kind::Empty;
    if (!capture && no_capture_plies_ == std::numeric_limits<std::uint32_t>::max())
        throw std::overflow_error("no-capture counter overflow");
    next.board_[static_cast<std::size_t>(move.from)] = {};
    next.board_[static_cast<std::size_t>(move.to)] = {moving.kind == Kind::Dark ? reveal : moving.kind, turn_};
    next.turn_ = opposite(turn_);
    next.no_capture_plies_ = capture ? 0 : no_capture_plies_ + 1;
    next.ply_ = ply_ + 1;
    return next;
}
BasicStatus Position::basic_status(std::uint32_t limit) const {
    if (limit == 0) throw std::invalid_argument("no-capture limit must be positive");
    if (legal_moves().empty()) return BasicStatus::LossForSideToMove;
    if (no_capture_plies_ >= limit) return BasicStatus::NoCaptureDraw;
    return BasicStatus::Ongoing;
}
std::uint64_t Position::perft_impl(int depth) const {
    if (depth == 0) return 1;
    std::uint64_t result = 0;
    for (auto move : legal_moves()) {
        const auto child = apply(move).perft_impl(depth - 1);
        if (std::numeric_limits<std::uint64_t>::max() - result < child) throw std::overflow_error("perft overflow");
        result += child;
    }
    return result;
}
std::uint64_t Position::perft_revealed(int depth) const {
    if (depth < 0 || depth > 12) throw std::invalid_argument("perft depth outside [0,12]");
    if (std::any_of(board_.begin(), board_.end(), [](Piece p) { return p.kind == Kind::Dark; }))
        throw std::invalid_argument("revealed-only perft cannot accept dark pieces");
    // Perft counts legal paths, deliberately ignoring draw/repetition adjudication.
    return perft_impl(depth);
}
}  // namespace jieqi
