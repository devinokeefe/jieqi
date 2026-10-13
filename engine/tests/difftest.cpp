// Differential test: jqe move generation / check detection / make-unmake against the
// independent rules oracle in native/ (jieqi_core). Random games with a random hidden deal.
#include "position.h"
#include "search.h"

#include <jieqi/repetition.hpp>
#include <jieqi/rules.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <set>
#include <string>
#include <vector>

using namespace jq;

namespace {

std::string public_board(const Position& p) {
    std::string s(90, '.');
    for (int i = 0; i < NUM_SQ; ++i) s[i] = piece_char(p.board[i]);
    return s;
}

jieqi::Kind to_kind(PieceType t) {
    switch (t) {
    case ROOK: return jieqi::Kind::Rook;
    case HORSE: return jieqi::Kind::Horse;
    case ELEPHANT: return jieqi::Kind::Elephant;
    case ADVISOR: return jieqi::Kind::Advisor;
    case CANNON: return jieqi::Kind::Cannon;
    case SOLDIER: return jieqi::Kind::Soldier;
    default: return jieqi::Kind::Empty;
    }
}

int failures = 0;
void fail(const std::string& what, const Position& p) {
    if (++failures <= 20) std::printf("FAIL %s\n%s\n", what.c_str(), p.pretty().c_str());
}

// Random games interrupted by constructed two-fold cycles A, B, A', B' (played twice, so the start
// position occurs three times): jqe's in-search verdict must equal the native referee's adjudication.
void rep_test(int games, std::mt19937_64& rng) {
    int cycles = 0, verdicts[4] = {0, 0, 0, 0};
    for (int g = 0; g < games && failures <= 20; ++g) {
        Position p;
        p.set_fen(START_FEN);
        int deal[2][NUM_SQ];
        for (int c = 0; c < 2; ++c) {
            std::vector<int> bag;
            for (int sl = 0; sl < NUM_SLOTS; ++sl)
                for (int k = 0; k < URN_INIT[sl]; ++k) bag.push_back(sl);
            std::shuffle(bag.begin(), bag.end(), rng);
            int k = 0;
            for (int s = 0; s < NUM_SQ; ++s)
                deal[c][s] = (p.board[s] && type_of(p.board[s]) == DARK && color_of(p.board[s]) == c) ? bag[k++] : -1;
        }
        jieqi::RepetitionHistory hist(jieqi::Position(public_board(p), jieqi::Color::Red, 0));
        auto play = [&](Move m) {
            const bool dark = p.is_dark_move(m);
            const PieceType rev = dark ? slot_type(deal[p.stm][from_sq(m)]) : NO_TYPE;
            std::string tok = move_str(m);
            if (dark) tok += piece_char(make_piece(p.stm, rev));
            const Piece victim = p.board[to_sq(m)];
            if (victim && type_of(victim) == DARK)
                tok += piece_char(make_piece(color_of(victim), slot_type(deal[color_of(victim)][to_sq(m)])));
            std::string err;
            hist.append({from_sq(m), to_sq(m)}, dark ? to_kind(rev) : jieqi::Kind::Empty);
            return p.apply_token(tok, &err);
        };
        auto quiet_bright = [&](std::vector<Move>& out) {
            Move ml[MAX_MOVES];
            const int n = p.gen_legal(ml);
            out.clear();
            for (int i = 0; i < n; ++i)
                if (!p.is_capture(ml[i]) && !p.is_dark_move(ml[i])) out.push_back(ml[i]);
            return n;
        };
        // Prefer moves that newly threaten an enemy piece under the chase rule (to exercise chase verdicts).
        auto chasing = [&](std::vector<Move>& qs) {
            std::vector<Move> out;
            const auto before = p.chase_threats(p.stm);
            for (Move m : qs) {
                Position c = p;
                StateInfo st;
                c.do_move(m, st);
                if ((c.chase_threats(~c.stm) & ~before).any()) out.push_back(m);
            }
            if (!out.empty() && rng() % 5 != 0) qs = out;
        };
        auto is_legal = [&](Move m) {
            Move ml[MAX_MOVES];
            const int n = p.gen_legal(ml);
            for (int i = 0; i < n; ++i)
                if (ml[i] == m) return true;
            return false;
        };
        const int warmup = 10 + int(rng() % 80);
        for (int ply = 0; ply < 400; ++ply) {
            if (hist.terminal_status() != jieqi::GameStatus::Ongoing) break;
            std::vector<Move> q;
            Move ml[MAX_MOVES];
            const int n = p.gen_legal(ml);
            if (n == 0) break;
            bool cycled = false;
            if (ply >= warmup && rng() % 3 == 0) {
                // Try a cycle: A (stm), B (opponent), reverse A, reverse B, twice.
                std::vector<Move> qa;
                quiet_bright(qa);
                chasing(qa);
                if (!qa.empty()) {
                    const Move a = qa[rng() % qa.size()];
                    const Position save = p;
                    const jieqi::RepetitionHistory hsave = hist;
                    bool ok = play(a);
                    std::vector<Move> qb;
                    if (ok) quiet_bright(qb);
                    if (ok && rng() % 2) chasing(qb);
                    if (ok && !qb.empty()) {
                        const Move b = qb[rng() % qb.size()];
                        const Move ar = make_move(to_sq(a), from_sq(a)), br = make_move(to_sq(b), from_sq(b));
                        ok = play(b) && is_legal(ar) && play(ar) && is_legal(br) && play(br);
                        for (int rep = 0; ok && rep < 1; ++rep)
                            ok = is_legal(a) && play(a) && is_legal(b) && play(b) && is_legal(ar) && play(ar) && is_legal(br) && play(br);
                        if (ok) {
                            const auto r = hist.adjudicate_repetition();
                            const int mine = p.repetition_status();
                            int expect = -1;  // jqe encoding: 1 draw, 2 stm wins, 3 stm loses
                            if (r.status == jieqi::RepetitionStatus::Draw) expect = 1;
                            else if (r.status == jieqi::RepetitionStatus::RedLoses) expect = p.stm == RED ? 3 : 2;
                            else if (r.status == jieqi::RepetitionStatus::BlackLoses) expect = p.stm == BLACK ? 3 : 2;
                            ++cycles;
                            if (expect >= 0) ++verdicts[expect];
                            if (mine != expect) {
                                fail("repetition verdict mismatch: jqe " + std::to_string(mine) + " referee " +
                                         std::to_string(expect) + " cycle " + move_str(a) + " " + move_str(b), p);
                            }
                            cycled = true;
                        }
                    }
                    if (!cycled) {  // roll back a failed attempt
                        p = save;
                        hist = hsave;
                    }
                }
            }
            if (cycled) continue;
            const Move m = ml[rng() % n];
            if (!play(m)) { fail("apply in rep_test", p); break; }
        }
    }
    std::printf("repetition cycles %d: draw %d, stm-wins %d, stm-loses %d, failures %d\n", cycles, verdicts[1], verdicts[2],
                verdicts[3], failures);
}

}  // namespace

int main(int argc, char** argv) {
    const int games = argc > 1 ? std::atoi(argv[1]) : 2000;
    const unsigned seed = argc > 2 ? unsigned(std::atoi(argv[2])) : 12345u;
    search::init();
    std::mt19937_64 rng(seed);
    uint64_t positions = 0, movesChecked = 0, chaseChecked = 0, chaseNonEmpty = 0;
    int decisive = 0, draws80 = 0, capped = 0;
    for (int g = 0; g < games; ++g) {
        Position p;
        p.set_fen(START_FEN);
        // Hidden deal: identity per (colour, start square), a shuffled urn.
        int deal[2][NUM_SQ];
        for (int c = 0; c < 2; ++c) {
            std::vector<int> bag;
            for (int sl = 0; sl < NUM_SLOTS; ++sl)
                for (int k = 0; k < URN_INIT[sl]; ++k) bag.push_back(sl);
            std::shuffle(bag.begin(), bag.end(), rng);
            int k = 0;
            for (int s = 0; s < NUM_SQ; ++s)
                deal[c][s] = (p.board[s] && type_of(p.board[s]) == DARK && color_of(p.board[s]) == c) ? bag[k++] : -1;
        }
        const double captureBias = std::uniform_real_distribution<double>(0.2, 0.9)(rng);
        for (int ply = 0;; ++ply) {
            ++positions;
            jieqi::Position o(public_board(p), p.stm == RED ? jieqi::Color::Red : jieqi::Color::Black, uint32_t(p.noCapture));
            std::string err;
            if (!p.valid(&err)) { fail("invalid state: " + err, p); break; }
            // Legal move sets.
            Move ml[MAX_MOVES];
            const int n = p.gen_legal(ml);
            std::set<std::pair<int, int>> mine, theirs;
            for (int i = 0; i < n; ++i) mine.insert({from_sq(ml[i]), to_sq(ml[i])});
            for (const auto& m : o.legal_moves()) theirs.insert({m.from, m.to});
            if (mine != theirs) {
                std::string d = "legal set mismatch: mine-only";
                for (auto& x : mine) if (!theirs.count(x)) d += " " + move_str(make_move(x.first, x.second));
                d += " oracle-only";
                for (auto& x : theirs) if (!mine.count(x)) d += " " + move_str(make_move(x.first, x.second));
                fail(d, p);
                break;
            }
            const bool chk = p.in_check();
            if (chk != o.in_check(p.stm == RED ? jieqi::Color::Red : jieqi::Color::Black)) { fail("check mismatch", p); break; }
            if (chk != (p.checkHist.back() != 0)) { fail("checkHist mismatch", p); break; }
            for (int c = 0; c < 2; ++c) {
                const auto mine = p.chase_threats(Color(c));
                const auto theirs = o.chase_targets(c == RED ? jieqi::Color::Red : jieqi::Color::Black);
                ++chaseChecked;
                chaseNonEmpty += mine.any();
                if (mine != theirs) { fail("chase threat mismatch for " + std::string(c == RED ? "red" : "black"), p); goto next_game; }
            }
            if (n == 0) { ++decisive; break; }
            if (p.noCapture >= NO_CAPTURE_LIMIT) { ++draws80; break; }
            if (ply >= 400) { ++capped; break; }
            // gives_check / make-unmake round trip on every legal move.
            const std::string fenBefore = p.fen();
            const uint64_t keyBefore = p.key;
            for (int i = 0; i < n; ++i) {
                const Move m = ml[i];
                Move mm = m;
                if (p.is_dark_move(m)) mm = make_move(from_sq(m), to_sq(m), slot_type(deal[p.stm][from_sq(m)]));
                const bool gc = p.gives_check(m);
                StateInfo st;
                p.do_move(mm, st);
                ++movesChecked;
                const bool oppInCheck = p.in_check();
                if (st.urnSlot < 0 && gc != oppInCheck) {
                    p.undo_move(mm, st);
                    fail("gives_check mismatch on " + move_str(m), p);
                    goto next_game;
                }
                if (!p.valid(&err)) { p.undo_move(mm, st); fail("invalid after " + move_str(m) + ": " + err, p); goto next_game; }
                p.undo_move(mm, st);
                if (p.key != keyBefore || p.fen() != fenBefore) { fail("undo mismatch on " + move_str(m), p); goto next_game; }
            }
            {
                // Choose a move: prefer captures with probability captureBias.
                std::vector<Move> caps;
                for (int i = 0; i < n; ++i) if (p.is_capture(ml[i])) caps.push_back(ml[i]);
                Move m = (!caps.empty() && std::uniform_real_distribution<double>(0, 1)(rng) < captureBias)
                             ? caps[rng() % caps.size()] : ml[rng() % n];
                const bool dark = p.is_dark_move(m);
                const PieceType rev = dark ? slot_type(deal[p.stm][from_sq(m)]) : NO_TYPE;
                jieqi::Position next = o.apply({from_sq(m), to_sq(m)}, dark ? to_kind(rev) : jieqi::Kind::Empty);
                // Build an observer-free token so apply_token's parser is exercised too (victim identity known).
                std::string tok = move_str(m);
                if (dark) tok += piece_char(make_piece(p.stm, rev));
                const Piece victim = p.board[to_sq(m)];
                if (victim && type_of(victim) == DARK) {
                    const int vid = deal[color_of(victim)][to_sq(m)];
                    tok += piece_char(make_piece(color_of(victim), slot_type(vid)));
                }
                if (!p.apply_token(tok, &err)) { fail("apply_token " + tok + ": " + err, p); break; }
                if (public_board(p) != next.public_board()) { fail("board mismatch after " + tok, p); break; }
                if (uint32_t(p.noCapture) != next.no_capture_plies()) { fail("counter mismatch after " + tok, p); break; }
            }
        }
    next_game:;
        if (failures > 20) break;
    }
    std::printf("games %d positions %llu moves-checked %llu nolegal %d draw80 %d capped %d failures %d\n", games,
                (unsigned long long)positions, (unsigned long long)movesChecked, decisive, draws80, capped, failures);
    std::printf("chase threat sets compared %llu (non-empty %llu)\n", (unsigned long long)chaseChecked,
                (unsigned long long)chaseNonEmpty);
    rep_test(games, rng);
    // Chance-perft sanity: probability mass of the expanded tree equals the base-move perft count.
    Position s;
    s.set_fen(START_FEN);
    for (int d = 1; d <= 3; ++d) {
        uint64_t leaves = 0;
        Position c = s;
        const double mass = search::perft_chance(c, d, leaves);
        Position b = s;
        const uint64_t base = search::perft(b, d);
        std::printf("start depth %d: base perft %llu, chance leaves %llu, expected base leaves %.4f\n", d,
                    (unsigned long long)base, (unsigned long long)leaves, mass);
    }
    return failures ? 1 : 0;
}
