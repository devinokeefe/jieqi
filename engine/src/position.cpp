#include "position.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <bitset>
#include <cstring>
#include <sstream>

namespace jq {

const char* START_FEN =
    "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1";

namespace {
PieceType type_from_char(char ch) {
    switch (std::toupper(static_cast<unsigned char>(ch))) {
    case 'K': return KING;
    case 'R': return ROOK;
    case 'N': case 'H': return HORSE;
    case 'B': case 'E': return ELEPHANT;
    case 'A': return ADVISOR;
    case 'C': return CANNON;
    case 'P': return SOLDIER;
    case 'X': return DARK;
    default: return NO_TYPE;
    }
}
bool fail(std::string* error, const char* text) {
    if (error) *error = text;
    return false;
}
}  // namespace

char piece_char(Piece p) {
    static const char* chars = ".KRNBACPX";
    if (p == NO_PIECE) return '.';
    const char c = chars[type_of(p)];
    return color_of(p) == RED ? c : char(std::tolower(static_cast<unsigned char>(c)));
}

std::string move_str(Move m) {
    if (m == MOVE_NONE) return "0000";
    std::string s;
    s += char('a' + file_of(from_sq(m)));
    s += char('0' + rank_of(from_sq(m)));
    s += char('a' + file_of(to_sq(m)));
    s += char('0' + rank_of(to_sq(m)));
    return s;
}

Move parse_move_coords(const std::string& s) {
    if (s.size() < 4) return MOVE_NONE;
    const int f1 = s[0] - 'a', r1 = s[1] - '0', f2 = s[2] - 'a', r2 = s[3] - '0';
    if (f1 < 0 || f1 > 8 || f2 < 0 || f2 > 8 || r1 < 0 || r1 > 9 || r2 < 0 || r2 > 9) return MOVE_NONE;
    return make_move(make_sq(f1, r1), make_sq(f2, r2));
}

void Position::add_piece(int s, Piece p) {
    board[s] = p;
    const Color c = color_of(p);
    pidx[s] = pcount[c];
    plist[c][pcount[c]++] = uint8_t(s);
}

void Position::remove_piece(int s) {
    const Color c = color_of(board[s]);
    const int i = pidx[s];
    const int last = plist[c][--pcount[c]];
    plist[c][i] = uint8_t(last);
    pidx[last] = int8_t(i);
    pidx[s] = -1;
    board[s] = NO_PIECE;
}

void Position::move_piece(int from, int to) {
    const Color c = color_of(board[from]);
    const int i = pidx[from];
    plist[c][i] = uint8_t(to);
    pidx[to] = int8_t(i);
    pidx[from] = -1;
    board[to] = board[from];
    board[from] = NO_PIECE;
}

uint64_t Position::compute_key() const {
    uint64_t k = 0;
    for (int s = 0; s < NUM_SQ; ++s)
        if (board[s]) k ^= T.zPiece[board[s]][s];
    if (stm == BLACK) k ^= T.zSide;
    for (int c = 0; c < 2; ++c)
        for (int sl = 0; sl < NUM_SLOTS; ++sl) k ^= T.zUrn[c][sl][urn[c][sl]];
    return k;
}

bool Position::set_fen(const std::string& fen, std::string* error) {
    init_tables();
    std::istringstream in(fen);
    std::string boardText, side, pools = "-", clock = "0", number = "1";
    if (!(in >> boardText >> side)) return fail(error, "fen needs board and side");
    in >> pools >> clock >> number;
    std::memset(board, 0, sizeof board);
    std::memset(pidx, -1, sizeof pidx);
    pcount[0] = pcount[1] = 0;
    darkCount[0] = darkCount[1] = 0;
    kingSq[0] = kingSq[1] = -1;
    int rank = 9, file = 0;
    for (char ch : boardText) {
        if (ch == '/') {
            if (file != 9) return fail(error, "rank does not have 9 files");
            --rank;
            file = 0;
            continue;
        }
        if (std::isdigit(static_cast<unsigned char>(ch))) {
            file += ch - '0';
            continue;
        }
        const PieceType t = type_from_char(ch);
        if (t == NO_TYPE || rank < 0 || file > 8) return fail(error, "bad board character");
        const Color c = std::isupper(static_cast<unsigned char>(ch)) ? RED : BLACK;
        const int s = make_sq(file, rank);
        if (t == DARK && T.darkRole[c][s] == NO_TYPE) return fail(error, "face-down piece off its start point");
        if (pcount[c] >= 16) return fail(error, "too many pieces");
        add_piece(s, make_piece(c, t));
        if (t == KING) kingSq[c] = int8_t(s);
        if (t == DARK) ++darkCount[c];
        ++file;
    }
    if (rank != 0 || file != 9) return fail(error, "board must have 10 ranks");
    if (kingSq[0] < 0 || kingSq[1] < 0) return fail(error, "missing king");
    if (side == "w" || side == "r") stm = RED;
    else if (side == "b") stm = BLACK;
    else return fail(error, "bad side to move");
    std::memset(urn, 0, sizeof urn);
    if (pools != "-") {
        // Pool letters are R A C P N B in Pikafish order; accept any order.
        for (std::size_t i = 0; i < pools.size();) {
            const char ch = pools[i++];
            const PieceType t = type_from_char(ch);
            if (t < ROOK || t > SOLDIER) return fail(error, "bad pool letter");
            int n = 0;
            while (i < pools.size() && std::isdigit(static_cast<unsigned char>(pools[i]))) n = n * 10 + (pools[i++] - '0');
            const Color c = std::isupper(static_cast<unsigned char>(ch)) ? RED : BLACK;
            if (n > URN_INIT[type_slot(t)]) return fail(error, "pool count too large");
            urn[c][type_slot(t)] = int8_t(n);
        }
    }
    for (int c = 0; c < 2; ++c) {
        urnTotal[c] = 0;
        for (int sl = 0; sl < NUM_SLOTS; ++sl) urnTotal[c] = int8_t(urnTotal[c] + urn[c][sl]);
        if (urnTotal[c] < darkCount[c]) return fail(error, "pool smaller than face-down count");
    }
    noCapture = int16_t(std::stoi(clock));
    key = compute_key();
    keyHist.clear();
    checkHist.clear();
    moveHist.clear();
    lastIrrev = 0;
    push_history();
    (void)number;
    return true;
}

std::string Position::fen() const {
    std::string out;
    for (int r = 9; r >= 0; --r) {
        int empty = 0;
        for (int f = 0; f < 9; ++f) {
            const Piece p = board[make_sq(f, r)];
            if (!p) { ++empty; continue; }
            if (empty) out += char('0' + empty), empty = 0;
            out += piece_char(p);
        }
        if (empty) out += char('0' + empty);
        if (r) out += '/';
    }
    out += stm == RED ? " w " : " b ";
    static const PieceType order[6] = {ROOK, ADVISOR, CANNON, SOLDIER, HORSE, ELEPHANT};
    std::string pools;
    for (int c = 0; c < 2; ++c)
        for (PieceType t : order) {
            const int n = urn[c][type_slot(t)];
            if (!n) continue;
            pools += piece_char(make_piece(Color(c), t));
            pools += std::to_string(n);
        }
    out += pools.empty() ? "-" : pools;
    out += " " + std::to_string(noCapture) + " 1";
    return out;
}

std::string Position::pretty() const {
    std::string out;
    for (int r = 9; r >= 0; --r) {
        out += char('0' + r);
        out += ' ';
        for (int f = 0; f < 9; ++f) {
            out += piece_char(board[make_sq(f, r)]);
            out += ' ';
        }
        out += '\n';
    }
    out += "  a b c d e f g h i\n";
    out += "fen " + fen() + "\n";
    return out;
}

bool Position::ray_attacked(Color c, int k, int d) const {
    const Color e = ~c;
    const int n = T.rayLen[k][d];
    const uint8_t* r = T.ray[k][d];
    int i = 0;
    while (i < n && !board[r[i]]) ++i;
    if (i == n) return false;
    const Piece p = board[r[i]];
    if (color_of(p) == e) {
        const PieceType t = role(r[i]);
        if (t == ROOK) return true;
        if (t == KING && d < 2) return true;  // facing generals
    }
    for (++i; i < n; ++i) {
        if (!board[r[i]]) continue;
        return color_of(board[r[i]]) == e && role(r[i]) == CANNON;
    }
    return false;
}

bool Position::king_attacked(Color c, int k) const {
    const Color e = ~c;
    for (int d = 0; d < 4; ++d)
        if (ray_attacked(c, k, d)) return true;
    for (int j = 0; j < T.horseFromN[k]; ++j) {
        const int p = T.horseFrom[k][j];
        if (board[p] && color_of(board[p]) == e && role(p) == HORSE && !board[T.horseFromLeg[k][j]]) return true;
    }
    // Enemy soldiers attack forward (towards our home) and sideways once across the river.
    const int back = c == RED ? 9 : -9;  // square "in front" of our king from the enemy soldier's view
    const int s1 = k + back;
    if (s1 >= 0 && s1 < NUM_SQ && board[s1] && color_of(board[s1]) == e && role(s1) == SOLDIER) return true;
    if (file_of(k) > 0) {
        const int s = k - 1;
        if (board[s] && color_of(board[s]) == e && role(s) == SOLDIER && !own_half(e, s)) return true;
    }
    if (file_of(k) < 8) {
        const int s = k + 1;
        if (board[s] && color_of(board[s]) == e && role(s) == SOLDIER && !own_half(e, s)) return true;
    }
    // Revealed advisors and elephants roam freely in Jieqi.
    for (int j = 0; j < T.advN[k]; ++j) {
        const int s = T.advTo[k][j];
        if (board[s] && color_of(board[s]) == e && role(s) == ADVISOR) {
            if (type_of(board[s]) != DARK || in_palace(e, k)) return true;
        }
    }
    for (int j = 0; j < T.elephN[k]; ++j) {
        const int s = T.elephTo[k][j];
        if (board[s] && color_of(board[s]) == e && role(s) == ELEPHANT && !board[T.elephEye[k][j]]) {
            if (type_of(board[s]) != DARK || own_half(e, k)) return true;
        }
    }
    return false;
}

namespace {
inline void add(Move*& out, int from, int to) { *out++ = make_move(from, to); }
}  // namespace

template <bool CAP>
int Position::gen(Move* list) const {
    Move* out = list;
    const Color us = stm;
    for (int i = 0; i < pcount[us]; ++i) {
        const int s = plist[us][i];
        const Piece pc = board[s];
        const bool dark = type_of(pc) == DARK;
        const PieceType t = role(s);
        auto target_ok = [&](int to) {
            const Piece q = board[to];
            return !q || (color_of(q) != us && type_of(q) != KING);
        };
        switch (t) {
        case KING:
            for (int j = 0; j < T.kingN[s]; ++j)
                if (target_ok(T.kingTo[s][j]) && (!CAP || board[T.kingTo[s][j]])) add(out, s, T.kingTo[s][j]);
            break;
        case ROOK:
            for (int d = 0; d < 4; ++d)
                for (int j = 0; j < T.rayLen[s][d]; ++j) {
                    const int to = T.ray[s][d][j];
                    if (!board[to]) { if (!CAP) add(out, s, to); continue; }
                    if (target_ok(to)) add(out, s, to);
                    break;
                }
            break;
        case CANNON:
            for (int d = 0; d < 4; ++d) {
                int j = 0;
                const int n = T.rayLen[s][d];
                for (; j < n; ++j) {
                    const int to = T.ray[s][d][j];
                    if (board[to]) break;
                    if (!CAP) add(out, s, to);
                }
                for (++j; j < n; ++j) {
                    const int to = T.ray[s][d][j];
                    if (!board[to]) continue;
                    if (target_ok(to)) add(out, s, to);
                    break;
                }
            }
            break;
        case HORSE:
            for (int j = 0; j < T.horseN[s]; ++j)
                if (!board[T.horseLeg[s][j]] && target_ok(T.horseTo[s][j]) && (!CAP || board[T.horseTo[s][j]])) add(out, s, T.horseTo[s][j]);
            break;
        case ELEPHANT:
            for (int j = 0; j < T.elephN[s]; ++j) {
                const int to = T.elephTo[s][j];
                if (board[T.elephEye[s][j]] || !target_ok(to) || (CAP && !board[to])) continue;
                if (dark && !own_half(us, to)) continue;
                add(out, s, to);
            }
            break;
        case ADVISOR:
            for (int j = 0; j < T.advN[s]; ++j) {
                const int to = T.advTo[s][j];
                if (!target_ok(to) || (CAP && !board[to]) || (dark && !in_palace(us, to))) continue;
                add(out, s, to);
            }
            break;
        case SOLDIER: {
            const int fwd = us == RED ? 9 : -9;
            const int to = s + fwd;
            if (to >= 0 && to < NUM_SQ && target_ok(to) && (!CAP || board[to])) add(out, s, to);
            if (!own_half(us, s)) {
                if (file_of(s) > 0 && target_ok(s - 1) && (!CAP || board[s - 1])) add(out, s, s - 1);
                if (file_of(s) < 8 && target_ok(s + 1) && (!CAP || board[s + 1])) add(out, s, s + 1);
            }
            break;
        }
        default: break;
        }
    }
    return int(out - list);
}

int Position::gen_moves(Move* list) const { return gen<false>(list); }

// Captures only, in the same order as gen_moves() would list them.
int Position::gen_captures(Move* list) const { return gen<true>(list); }

namespace {
inline bool same_line(int a, int b) { return file_of(a) == file_of(b) || rank_of(a) == rank_of(b); }
inline bool diag_adjacent(int a, int b) {
    return std::abs(file_of(a) - file_of(b)) == 1 && std::abs(rank_of(a) - rank_of(b)) == 1;
}
inline int cheb(int a, int b) { return std::max(std::abs(file_of(a) - file_of(b)), std::abs(rank_of(a) - rank_of(b))); }
// A non-king move can change attacks on king k only through k's file/rank (sliders, cannon screens,
// facing generals) or k's diagonal neighbours (horse legs and elephant eyes).
inline bool touches_king_lines(int from, int to, int k) {
    return same_line(from, k) || same_line(to, k) || diag_adjacent(from, k);
}
}  // namespace

bool Position::legal(Move m) const {
    const int from = from_sq(m), to = to_sq(m);
    if (type_of(board[from]) != KING && !checkHist.back() && !touches_king_lines(from, to, kingSq[stm])) return true;
    auto& b = const_cast<Piece(&)[NUM_SQ]>(board);
    const Piece moving = b[from], captured = b[to];
    b[to] = type_of(moving) == DARK ? make_piece(stm, SOLDIER) : moving;  // identity irrelevant for own safety
    b[from] = NO_PIECE;
    bool ok;
    const int k0 = kingSq[stm];
    if (type_of(moving) == KING || checkHist.back() || diag_adjacent(from, k0))
        ok = !king_attacked(stm, type_of(moving) == KING ? to : k0);
    else {
        // Not in check and the king stays: only rays through from (discovery) or to (new cannon
        // screen) can carry a new attack.
        const int df = T.dirTo[k0][from], dt = T.dirTo[k0][to];
        ok = !((df >= 0 && ray_attacked(stm, k0, df)) || (dt >= 0 && dt != df && ray_attacked(stm, k0, dt)));
    }
#ifdef JQ_VERIFY_LEGAL
    if (ok != !king_attacked(stm, type_of(moving) == KING ? to : k0)) { std::fprintf(stderr, "legal mismatch %s\n", fen().c_str()); std::abort(); }
#endif
    b[from] = moving;
    b[to] = captured;
    return ok;
}

bool Position::reveal_may_check(int to) const {
    const int k = kingSq[~stm];
    return file_of(to) == file_of(k) || rank_of(to) == rank_of(k) || cheb(to, k) <= 2;
}

bool Position::reveal_gives_check(int from, int to, PieceType t) const {
    auto& b = const_cast<Piece(&)[NUM_SQ]>(board);
    const Piece moving = b[from], captured = b[to];
    b[to] = make_piece(stm, t);
    b[from] = NO_PIECE;
    const bool check = king_attacked(~stm, kingSq[~stm]);
    b[from] = moving;
    b[to] = captured;
    return check;
}

bool Position::gives_check(Move m) const {
    const int from = from_sq(m), to = to_sq(m);
    const Piece moving = board[from];
    if (type_of(moving) == DARK) return false;
    {
        const int k = kingSq[~stm];
        const PieceType t = type_of(moving);
        // Off the enemy king's lines a rook/cannon/king cannot attack it, and the others need to be close.
        if (!touches_king_lines(from, to, k) && (t == ROOK || t == CANNON || t == KING || cheb(to, k) > 2)) return false;
    }
    auto& b = const_cast<Piece(&)[NUM_SQ]>(board);
    const Piece captured = b[to];
    b[to] = moving;
    b[from] = NO_PIECE;
    const int k = kingSq[~stm];
    const PieceType t = type_of(moving);
    bool check;
    if (diag_adjacent(from, k) || (t != ROOK && t != CANNON && t != KING && cheb(to, k) <= 2))
        check = king_attacked(~stm, k);
    else {
        // The mover can only check along a ray through to; discoveries come through from's ray.
        const int df = T.dirTo[k][from], dt = T.dirTo[k][to];
        check = (df >= 0 && ray_attacked(~stm, k, df)) || (dt >= 0 && dt != df && ray_attacked(~stm, k, dt));
    }
#ifdef JQ_VERIFY_LEGAL
    if (check != king_attacked(~stm, k)) { std::fprintf(stderr, "check mismatch %s\n", fen().c_str()); std::abort(); }
#endif
    b[from] = moving;
    b[to] = captured;
    return check;
}

int Position::gen_legal(Move* list) const {
    Move tmp[MAX_MOVES];
    const int n = gen_moves(tmp);
    int k = 0;
    for (int i = 0; i < n; ++i)
        if (legal(tmp[i])) list[k++] = tmp[i];
    return k;
}

bool Position::has_legal_move() const {
    Move tmp[MAX_MOVES];
    const int n = gen_moves(tmp);
    for (int i = 0; i < n; ++i)
        if (legal(tmp[i])) return true;
    return false;
}

void Position::do_move(Move m, StateInfo& st) {
    const int from = from_sq(m), to = to_sq(m);
    const Color us = stm;
    const Piece pc = board[from];
    const Piece cap = board[to];
    st.key = key;
    st.captured = cap;
    st.urnSlot = -1;
    st.noCapture = noCapture;
    st.lastIrrev = int16_t(lastIrrev);
    if (cap) {
        key ^= T.zPiece[cap][to];
        if (type_of(cap) == DARK) --darkCount[~us];
        remove_piece(to);
    }
    key ^= T.zPiece[pc][from];
    move_piece(from, to);
    Piece np = pc;
    if (type_of(pc) == DARK) {
        const int sl = type_slot(reveal_of(m));
        np = make_piece(us, reveal_of(m));
        board[to] = np;
        key ^= T.zUrn[us][sl][urn[us][sl]];
        --urn[us][sl];
        key ^= T.zUrn[us][sl][urn[us][sl]];
        --urnTotal[us];
        --darkCount[us];
        st.urnSlot = int8_t(sl);
    } else if (type_of(pc) == KING) {
        kingSq[us] = int8_t(to);
    }
    key ^= T.zPiece[np][to];
    key ^= T.zSide;
    noCapture = cap ? 0 : int16_t(noCapture + 1);
    stm = ~us;
    push_history();
    moveHist.push_back(base_move(m));
    if (cap || type_of(pc) == DARK) lastIrrev = int(keyHist.size()) - 1;
}

uint64_t Position::key_after(Move m) const {
    const int from = from_sq(m), to = to_sq(m);
    const Piece pc = board[from], cap = board[to];
    uint64_t k = key ^ T.zPiece[pc][from] ^ T.zSide;
    if (cap) k ^= T.zPiece[cap][to];
    Piece np = pc;
    if (type_of(pc) == DARK) {
        const int sl = type_slot(reveal_of(m));
        np = make_piece(stm, reveal_of(m));
        k ^= T.zUrn[stm][sl][urn[stm][sl]] ^ T.zUrn[stm][sl][urn[stm][sl] - 1];
    }
    return k ^ T.zPiece[np][to];
}

void Position::undo_move(Move m, const StateInfo& st) {
    const int from = from_sq(m), to = to_sq(m);
    stm = ~stm;
    const Color us = stm;
    keyHist.pop_back();
    checkHist.pop_back();
    moveHist.pop_back();
    if (st.urnSlot >= 0) {
        ++urn[us][st.urnSlot];
        ++urnTotal[us];
        ++darkCount[us];
        board[to] = make_piece(us, DARK);
    } else if (type_of(board[to]) == KING) {
        kingSq[us] = int8_t(from);
    }
    move_piece(to, from);
    if (st.captured) {
        add_piece(to, st.captured);
        if (type_of(st.captured) == DARK) ++darkCount[~us];
    }
    key = st.key;
    noCapture = st.noCapture;
    lastIrrev = st.lastIrrev;
}

void Position::do_null(StateInfo& st) {
    st.key = key;
    st.noCapture = noCapture;
    st.lastIrrev = int16_t(lastIrrev);
    key ^= T.zSide;
    stm = ~stm;
    ++noCapture;
    keyHist.push_back(key);
    checkHist.push_back(0);
    moveHist.push_back(MOVE_NULL);
    lastIrrev = int(keyHist.size()) - 1;  // a null move breaks repetition cycles
}

void Position::undo_null(const StateInfo& st) {
    stm = ~stm;
    key = st.key;
    noCapture = st.noCapture;
    lastIrrev = st.lastIrrev;
    keyHist.pop_back();
    checkHist.pop_back();
    moveHist.pop_back();
}

int g_chaseRule = 1;

namespace {
// ---- Perpetual-chase classification -------------------------------------------------------------
// Original port of the project's referee (native/chase.cpp, specified in ADJUDICATION.md). It works on
// a board of public positional types: a face-down piece acts as a face-up piece of its start-square
// role (so a dark advisor or elephant roams freely here, unlike in ordinary move generation).
using Mask = std::bitset<NUM_SQ>;
int sgn(int v) { return (v > 0) - (v < 0); }

int intervening(const Piece* b, int from, int to) {
    if (from == to || (file_of(from) != file_of(to) && rank_of(from) != rank_of(to))) return -1;
    const int step = sgn(file_of(to) - file_of(from)) + 9 * sgn(rank_of(to) - rank_of(from));
    int n = 0;
    for (int s = from + step; s != to; s += step) n += b[s] != NO_PIECE;
    return n;
}

bool geometry(const Piece* b, int from, int to) {
    const Piece pc = b[from];
    if (!pc || from == to) return false;
    const int dx = file_of(to) - file_of(from), dy = rank_of(to) - rank_of(from);
    const int ax = std::abs(dx), ay = std::abs(dy);
    const Color c = color_of(pc);
    switch (type_of(pc)) {
    case KING: return ax + ay == 1 && in_palace(c, to);
    case ROOK: return intervening(b, from, to) == 0;
    case CANNON: return intervening(b, from, to) == (b[to] ? 1 : 0);
    case HORSE:
        if (!((ax == 2 && ay == 1) || (ax == 1 && ay == 2))) return false;
        return !b[from + (ax == 2 ? sgn(dx) : 9 * sgn(dy))];
    case ELEPHANT: return ax == 2 && ay == 2 && !b[from + dx / 2 + 9 * (dy / 2)];
    case ADVISOR: return ax == 1 && ay == 1;
    case SOLDIER: return (dx == 0 && dy == (c == RED ? 1 : -1)) || (dy == 0 && ax == 1 && !own_half(c, from));
    default: return false;
    }
}

int king_square(const Piece* b, Color c) {
    for (int s = 0; s < NUM_SQ; ++s)
        if (b[s] == make_piece(c, KING)) return s;
    return -1;
}

// King safety of the hypothetical test: the enemy king counts as a rook ray (facing generals).
bool king_exposed(const Piece* b, Color c) {
    const int k = king_square(b, c);
    if (k < 0) return true;
    for (int s = 0; s < NUM_SQ; ++s) {
        const Piece pc = b[s];
        if (!pc || color_of(pc) == c) continue;
        if (type_of(pc) == KING ? intervening(b, s, k) == 0 : geometry(b, s, k)) return true;
    }
    return false;
}

bool safe_capture(Piece* b, int from, int to) {
    const Piece m = b[from], v = b[to];
    if (from == to || !m || !v || type_of(v) == KING || color_of(m) == color_of(v) || !geometry(b, from, to)) return false;
    b[to] = m;
    b[from] = NO_PIECE;
    const bool exposed = king_exposed(b, color_of(m));
    b[from] = m;
    b[to] = v;
    return !exposed;
}

bool major(PieceType t) { return t == ROOK || t == HORSE || t == CANNON; }

// Pieces screening an enemy line onto `actor`'s king ("blocked") and the enemy pieces pinning one of
// actor's pieces ("pinning"). For non-cannon lines, other non-cannon candidates are not screens.
void pins(const Piece* b, Color actor, Mask& blocked, Mask& pinning) {
    const int king = king_square(b, actor);
    if (king < 0) return;
    Mask candidates, omitted;
    int path[NUM_SQ][9];
    int plen[NUM_SQ] = {};
    for (int s = 0; s < NUM_SQ; ++s) {
        const Piece pc = b[s];
        if (!pc || color_of(pc) == actor) continue;
        const int dx = file_of(king) - file_of(s), dy = rank_of(king) - rank_of(s);
        const int ax = std::abs(dx), ay = std::abs(dy);
        const PieceType t = type_of(pc);
        bool cand = false;
        if ((t == ROOK || t == CANNON || t == KING) && (dx == 0 || dy == 0)) {
            cand = true;
            const int step = sgn(dx) + 9 * sgn(dy);
            for (int q = s + step; q != king; q += step) path[s][plen[s]++] = q;
        } else if (t == HORSE && ((ax == 2 && ay == 1) || (ax == 1 && ay == 2))) {
            cand = true;
            path[s][plen[s]++] = s + (ax == 2 ? sgn(dx) : 9 * sgn(dy));
        } else if (t == ELEPHANT && ax == 2 && ay == 2) {
            cand = true;
            path[s][plen[s]++] = s + dx / 2 + 9 * (dy / 2);
        }
        if (cand) {
            candidates.set(s);
            if (t != CANNON) omitted.set(s);
        }
    }
    for (int s = 0; s < NUM_SQ; ++s) {
        if (!candidates[s]) continue;
        const bool cannon = type_of(b[s]) == CANNON;
        Mask screens;
        bool friendly = false;
        for (int k = 0; k < plen[s]; ++k) {
            const int q = path[s][k];
            if (b[q] && (cannon || !omitted[q])) {
                screens.set(q);
                friendly = friendly || color_of(b[q]) == actor;
            }
        }
        if (screens.count() == (cannon ? 2u : 1u)) {
            blocked |= screens;
            if (friendly) pinning.set(s);
        }
    }
}

// Enemy pieces (squares) that `actor` threatens in the sense of the chase rule.
Mask chase_targets(Piece* b, Color actor) {
    Mask blocked, pinning, out;
    pins(b, actor, blocked, pinning);
    for (int target = 0; target < NUM_SQ; ++target) {
        const Piece victim = b[target];
        if (!victim || type_of(victim) == KING || color_of(victim) == actor) continue;
        const PieceType vt = type_of(victim);
        for (int a = 0; a < NUM_SQ; ++a) {
            const Piece pc = b[a];
            if (!pc || color_of(pc) != actor || type_of(pc) == KING || type_of(pc) == SOLDIER) continue;
            if (blocked[a]) {
                if (!pinning[target]) continue;
            } else if (vt == SOLDIER && own_half(color_of(victim), target)) continue;
            if (!safe_capture(b, a, target)) continue;
            const PieceType at = type_of(pc);
            const bool always = ((at == HORSE || at == CANNON) && vt == ROOK) || ((at == ADVISOR || at == ELEPHANT) && major(vt));
            if (!always) {
                b[target] = pc;  // hypothetical capture; any legal recapture protects the target
                b[a] = NO_PIECE;
                bool defended = false;
                for (int d = 0; d < NUM_SQ && !defended; ++d)
                    if (b[d] && color_of(b[d]) == color_of(victim)) defended = safe_capture(b, d, target);
                b[a] = pc;
                b[target] = victim;
                if (defended) continue;
                if (at == vt && safe_capture(b, target, a)) continue;  // mutual attack of equal pieces
            }
            out.set(target);
            break;
        }
    }
    return out;
}
}  // namespace

// Cycle from position `first` to the current one (no captures, reveals or checks inside it): a side
// that newly threatens one fixed physical piece with every one of its moves is a perpetual chaser.
// Returns 0 (draw: both or neither chase), 2 (side to move wins) or 3 (side to move loses).
int Position::chase_verdict(int first) const {
    const int p = int(keyHist.size()) - 1;
    const int len = p - first;
    if (len > 2 * MAX_PLY) return 0;
    Piece boards[2 * MAX_PLY + 1][NUM_SQ];
    for (int s = 0; s < NUM_SQ; ++s) {
        const Piece pc = board[s];
        boards[len][s] = pc && type_of(pc) == DARK ? make_piece(color_of(pc), role(s)) : pc;
    }
    for (int j = p - 1; j >= first; --j) {  // undo the cycle's pure relocations
        const Move m = moveHist[j];
        if (m == MOVE_NULL) return 0;
        Piece* b = boards[j - first];
        std::memcpy(b, boards[j - first + 1], NUM_SQ);
        b[from_sq(m)] = b[to_sq(m)];
        b[to_sq(m)] = NO_PIECE;
    }
    int id[NUM_SQ];
    for (int s = 0; s < NUM_SQ; ++s) id[s] = boards[0][s] ? s : -1;
    Mask common[2];
    common[RED].set();
    common[BLACK].set();
    const Color stmFirst = (len & 1) ? ~stm : stm;
    for (int j = 0; j < len; ++j) {
        const Color actor = (j & 1) ? ~stmFirst : stmFirst;
        const Move m = moveHist[first + j];
        Mask before, after;
        if (common[actor].any()) {
            const Mask bsq = chase_targets(boards[j], actor);
            for (int s = 0; s < NUM_SQ; ++s)
                if (bsq[s]) before.set(id[s]);
        }
        id[to_sq(m)] = id[from_sq(m)];
        id[from_sq(m)] = -1;
        if (common[actor].none()) continue;
        const Mask asq = chase_targets(boards[j + 1], actor);
        for (int s = 0; s < NUM_SQ; ++s)
            if (asq[s]) after.set(id[s]);
        common[actor] &= after & ~before;
        if (common[RED].none() && common[BLACK].none()) return 0;
    }
    const bool usChase = common[stm].any(), themChase = common[~stm].any();
    if (usChase == themChase) return 0;
    return usChase ? 3 : 2;
}

std::bitset<NUM_SQ> Position::chase_threats(Color actor) const {
    Piece b[NUM_SQ];
    for (int s = 0; s < NUM_SQ; ++s) b[s] = board[s] && type_of(board[s]) == DARK ? make_piece(color_of(board[s]), role(s)) : board[s];
    return chase_targets(b, actor);
}

int Position::repetition_status() const {
    const int p = int(keyHist.size()) - 1;
    for (int i = p - 4; i >= lastIrrev; i -= 2) {
        if (keyHist[i] != key) continue;
        // Moves in the cycle are made from positions i..p-1; the mover at position j gave check
        // iff the side to move at j+1 is in check. The mover at j is stm when (p-j) is even.
        bool perpUs = true, perpThem = true, anyCheck = false;
        for (int j = i; j < p; ++j) {
            const bool gaveCheck = checkHist[j + 1] != 0;
            anyCheck = anyCheck || gaveCheck;
            if (((p - j) & 1) == 0) perpUs = perpUs && gaveCheck;
            else perpThem = perpThem && gaveCheck;
        }
        if (perpUs && !perpThem) return 3;
        if (perpThem && !perpUs) return 2;
        if (anyCheck || !g_chaseRule) return 1;  // mutual perpetual or intermittent check: draw
        const int v = chase_verdict(i);
        return v ? v : 1;
    }
    return 0;
}

bool Position::has_major(Color c) const {
    for (int i = 0; i < pcount[c]; ++i) {
        const PieceType t = type_of(board[plist[c][i]]);
        if (t == ROOK || t == HORSE || t == CANNON || t == DARK) return true;
    }
    return false;
}

bool Position::apply_token(const std::string& token, std::string* error) {
    const Move base = parse_move_coords(token);
    if (base == MOVE_NONE) return fail(error, "bad move token");
    PieceType reveal = NO_TYPE, capturedId = NO_TYPE;
    for (std::size_t i = 4; i < token.size(); ++i) {
        const char ch = token[i];
        if (ch == 'x' || ch == 'X') continue;
        const PieceType t = type_from_char(ch);
        if (t < ROOK || t > SOLDIER) return fail(error, "bad suffix letter");
        const Color c = std::isupper(static_cast<unsigned char>(ch)) ? RED : BLACK;
        if (c == stm) reveal = t;
        else capturedId = t;
    }
    return apply_observed(base, reveal, capturedId, error);
}

bool Position::apply_observed(Move base, PieceType reveal, PieceType capturedId, std::string* error) {
    base = base_move(base);
    const int from = from_sq(base), to = to_sq(base);
    const Piece mover = board[from];
    if (!mover || color_of(mover) != stm) return fail(error, "no piece of side to move on origin");
    const Piece victim = board[to];
    Move legalMoves[MAX_MOVES];
    const int n = gen_legal(legalMoves);
    bool found = false;
    for (int i = 0; i < n; ++i) found = found || legalMoves[i] == base;
    if (!found) return fail(error, "illegal move in history");
    if (type_of(mover) == DARK) {
        if (reveal == NO_TYPE) return fail(error, "face-down mover without reveal");
        if (urn[stm][type_slot(reveal)] <= 0) return fail(error, "reveal not in pool");
    }
    StateInfo st;
    do_move(type_of(mover) == DARK ? make_move(from, to, reveal) : base, st);
    if (victim && type_of(victim) == DARK && capturedId != NO_TYPE) {
        // The observer saw the captured identity: remove it from that side's urn.
        const Color vc = color_of(victim);
        const int sl = type_slot(capturedId);
        if (urn[vc][sl] <= 0) return fail(error, "captured identity not in pool");
        key ^= T.zUrn[vc][sl][urn[vc][sl]];
        --urn[vc][sl];
        key ^= T.zUrn[vc][sl][urn[vc][sl]];
        --urnTotal[vc];
        keyHist.back() = key;
    }
    return true;
}

bool Position::valid(std::string* error) const {
    if (key != compute_key()) return fail(error, "key mismatch");
    int dark[2] = {0, 0}, cnt[2] = {0, 0};
    for (int s = 0; s < NUM_SQ; ++s) {
        const Piece p = board[s];
        if (!p) { if (pidx[s] != -1) return fail(error, "pidx on empty"); continue; }
        const Color c = color_of(p);
        ++cnt[c];
        if (type_of(p) == DARK) ++dark[c];
        if (pidx[s] < 0 || plist[c][pidx[s]] != s) return fail(error, "piece list mismatch");
        if (type_of(p) == KING && kingSq[c] != s) return fail(error, "king square mismatch");
    }
    for (int c = 0; c < 2; ++c) {
        if (cnt[c] != pcount[c] || dark[c] != darkCount[c]) return fail(error, "count mismatch");
        int tot = 0;
        for (int sl = 0; sl < NUM_SLOTS; ++sl) { if (urn[c][sl] < 0) return fail(error, "negative urn"); tot += urn[c][sl]; }
        if (tot != urnTotal[c] || tot < dark[c]) return fail(error, "urn total mismatch");
    }
    return true;
}

}  // namespace jq
