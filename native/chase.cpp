#include "jieqi/rules.hpp"
#include <bitset>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace jieqi {
namespace {
int x(int s) { return s % 9; }
int y(int s) { return s / 9; }
int direction(int d) { return (d > 0) - (d < 0); }
bool major(Kind k) { return k == Kind::Rook || k == Kind::Horse || k == Kind::Cannon; }
}

// Independent array-board implementation of ADJUDICATION.md. Hypothetical
// captures use public positional types throughout; they never sample identities.
class ChaseAnalysis {
public:
    explicit ChaseAnalysis(const Position& input) : position_(input) {
        for (int s = 0; s < 90; ++s) {
            auto& piece = position_.board_[static_cast<std::size_t>(s)];
            if (piece.kind == Kind::Dark) piece.kind = dark_role(piece.color, s);
        }
    }

    std::bitset<90> targets(Color actor) const {
        if (actor != Color::Red && actor != Color::Black) throw std::invalid_argument("invalid chase actor");
        const auto [blocked, pinning] = pins(actor);
        std::bitset<90> result;
        for (int target = 0; target < 90; ++target) {
            const auto victim = at(position_, target);
            if (victim.kind == Kind::Empty || victim.kind == Kind::King || victim.color == actor) continue;
            for (int attacker = 0; attacker < 90; ++attacker) {
                const auto piece = at(position_, attacker);
                if (piece.kind == Kind::Empty || piece.color != actor || piece.kind == Kind::King || piece.kind == Kind::Soldier) continue;
                if (blocked[static_cast<std::size_t>(attacker)]) {
                    if (!pinning[static_cast<std::size_t>(target)]) continue;
                } else if (victim.kind == Kind::Soldier &&
                           (victim.color == Color::Red ? y(target) <= 4 : y(target) >= 5)) continue;
                if (!safe_capture(position_, attacker, target)) continue;
                const bool protected_exception =
                    ((piece.kind == Kind::Horse || piece.kind == Kind::Cannon) && victim.kind == Kind::Rook) ||
                    ((piece.kind == Kind::Advisor || piece.kind == Kind::Elephant) && major(victim.kind));
                if (!protected_exception) {
                    const auto captured = relocate(position_, attacker, target);
                    bool defended = false;
                    for (int defender = 0; defender < 90 && !defended; ++defender) {
                        const auto p = at(captured, defender);
                        if (p.kind != Kind::Empty && p.color == victim.color)
                            defended = safe_capture(captured, defender, target);
                    }
                    if (defended) continue;
                    if (piece.kind == victim.kind && safe_capture(position_, target, attacker)) continue;
                }
                result.set(static_cast<std::size_t>(target));
                break;
            }
        }
        return result;
    }

private:
    Position position_;
    static Piece at(const Position& p, int s) { return p.board_[static_cast<std::size_t>(s)]; }
    static Position relocate(const Position& p, int from, int to) {
        Position result = p;
        result.board_[static_cast<std::size_t>(to)] = at(p, from);
        result.board_[static_cast<std::size_t>(from)] = {};
        return result;
    }
    static bool attacked(const Position& p, Color king_color) {
        const int king = p.king_square(king_color);
        for (int s = 0; s < 90; ++s) {
            const auto piece = at(p, s);
            if (piece.kind == Kind::Empty || piece.color == king_color) continue;
            // The pinned fallback's hypothetical king-safety test treats the
            // enemy king as a rook ray. Actual moves still use normal geometry.
            if (piece.kind == Kind::King ? p.intervening(s, king) == 0 : p.geometry(s, king)) return true;
        }
        return false;
    }
    static bool safe_capture(const Position& p, int from, int to) {
        const auto mover = at(p, from), victim = at(p, to);
        if (from == to || mover.kind == Kind::Empty || victim.kind == Kind::Empty ||
            victim.kind == Kind::King || mover.color == victim.color || !p.geometry(from, to)) return false;
        return !attacked(relocate(p, from, to), mover.color);
    }

    std::pair<std::bitset<90>, std::bitset<90>> pins(Color actor) const {
        // Geometric king threats define candidate pinners. For non-cannons,
        // other such non-cannon candidates do not count as intervening screens.
        const int king = position_.king_square(actor);
        std::bitset<90> candidates, omitted;
        std::array<std::bitset<90>, 90> paths;
        for (int s = 0; s < 90; ++s) {
            const auto p = at(position_, s);
            if (p.kind == Kind::Empty || p.color == actor) continue;
            const int dx = x(king)-x(s), dy = y(king)-y(s);
            const int ax = std::abs(dx), ay = std::abs(dy);
            bool candidate = false;
            auto& path = paths[static_cast<std::size_t>(s)];
            if ((p.kind == Kind::Rook || p.kind == Kind::Cannon || p.kind == Kind::King) && (dx == 0 || dy == 0)) {
                candidate = true;
                const int step = direction(dx) + 9*direction(dy);
                for (int point = s+step; point != king; point += step) path.set(static_cast<std::size_t>(point));
            } else if (p.kind == Kind::Horse && ((ax == 2 && ay == 1) || (ax == 1 && ay == 2))) {
                candidate = true;
                path.set(static_cast<std::size_t>(s + (ax == 2 ? direction(dx) : 9*direction(dy))));
            } else if (p.kind == Kind::Elephant && ax == 2 && ay == 2) {
                candidate = true;
                path.set(static_cast<std::size_t>(s + dx/2 + 9*(dy/2)));
            }
            if (candidate) {
                candidates.set(static_cast<std::size_t>(s));
                if (p.kind != Kind::Cannon) omitted.set(static_cast<std::size_t>(s));
            }
        }
        std::bitset<90> blocked, pinning;
        for (int s = 0; s < 90; ++s) if (candidates[static_cast<std::size_t>(s)]) {
            std::bitset<90> screens;
            const bool cannon = at(position_, s).kind == Kind::Cannon;
            bool friendly = false;
            for (int point = 0; point < 90; ++point) {
                const auto p = at(position_, point);
                if (paths[static_cast<std::size_t>(s)][static_cast<std::size_t>(point)] && p.kind != Kind::Empty &&
                    (cannon || !omitted[static_cast<std::size_t>(point)])) {
                    screens.set(static_cast<std::size_t>(point));
                    friendly = friendly || p.color == actor;
                }
            }
            if (screens.count() == (cannon ? 2U : 1U)) {
                blocked |= screens;
                if (friendly) pinning.set(static_cast<std::size_t>(s));
            }
        }
        return {blocked, pinning};
    }
};

std::bitset<90> Position::chase_targets(Color actor) const { return ChaseAnalysis(*this).targets(actor); }
}  // namespace jieqi
