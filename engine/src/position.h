// Board state, move generation and make/unmake for Jieqi.
//
// Information model (from the point of view of the player the engine plays for):
//   urn[c][slot]  candidate identities still unaccounted for among c's face-down pieces.
//   A face-down piece reveals as slot t with probability urn[c][t] / urnTotal[c].
// Captured face-down pieces whose identity the observer did not see stay in the urn;
// by exchangeability the live pieces are then still a uniform draw from the urn.
// Inside search, capturing a face-down piece never branches on its identity for the
// same reason (the urn is left unchanged), while moving one is a chance node.
#pragma once
#include "tables.h"
#include "types.h"

#include <bitset>
#include <string>
#include <vector>

namespace jq {

struct StateInfo {
    uint64_t key;        // key before the move
    Piece captured;
    int8_t urnSlot;      // slot drawn by the mover's reveal, -1 if none
    int16_t noCapture;   // counter before the move
    int16_t lastIrrev;   // irreversible boundary before the move
};

constexpr int NO_CAPTURE_LIMIT = 80;
// 1: a repetition without checks is adjudicated by the perpetual-chase rule of the match referee
// (native/chase.cpp, ADJUDICATION.md); 0: every such repetition is a draw.
extern int g_chaseRule;
constexpr int MAX_MOVES = 160;

class Position {
public:
    Piece board[NUM_SQ];
    Color stm = RED;
    int8_t urn[2][NUM_SLOTS];
    int8_t urnTotal[2];
    int8_t darkCount[2];
    int8_t kingSq[2];
    int16_t noCapture = 0;
    uint8_t plist[2][16];
    int8_t pcount[2];
    int8_t pidx[NUM_SQ];
    uint64_t key = 0;
    // Game + search history: key and "side to move is in check" per position.
    std::vector<uint64_t> keyHist;
    std::vector<uint8_t> checkHist;
    std::vector<Move> moveHist;  // moveHist[j]: base move played from position j (MOVE_NULL for a null move)
    int lastIrrev = 0;  // index into keyHist of the latest position after an irreversible move

    Position() { keyHist.reserve(1024); checkHist.reserve(1024); moveHist.reserve(1024); }

    // Pikafish-dialect FEN: board (ranks 9..0, X/x = face down), side, pools, half-move clock, move number.
    bool set_fen(const std::string& fen, std::string* error = nullptr);
    // History token from-to + optional reveal letter (mover colour) + optional captured identity (victim colour) or 'x'.
    bool apply_token(const std::string& token, std::string* error = nullptr);
    // Same as apply_token with parsed parts (reveal / captured identity NO_TYPE when not observed).
    bool apply_observed(Move base, PieceType reveal, PieceType capturedId, std::string* error = nullptr);
    std::string fen() const;
    std::string pretty() const;

    PieceType role(int s) const {
        const Piece p = board[s];
        return type_of(p) == DARK ? PieceType(T.darkRole[color_of(p)][s]) : type_of(p);
    }
    bool is_dark_move(Move m) const { return type_of(board[from_sq(m)]) == DARK; }
    bool is_capture(Move m) const { return board[to_sq(m)] != NO_PIECE; }

    bool king_attacked(Color c, int k) const;
    bool ray_attacked(Color c, int k, int d) const;  // rook / cannon / facing-king attack along one ray
    bool in_check() const { return king_attacked(stm, kingSq[stm]); }
    // Pseudo-legal generation of base moves (no reveal). Captures-only variant for quiescence.
    int gen_moves(Move* list) const;
    template <bool CAP> int gen(Move* list) const;
    int gen_captures(Move* list) const;
    // Own-king safety for a pseudo-legal base move; identity of a dark mover is irrelevant.
    bool legal(Move m) const;
    // Whether a legal move by a face-up piece checks the opponent (false for face-down movers).
    bool gives_check(Move m) const;
    // A face-down mover from -> to revealed as t: does the revealed piece itself attack the enemy king?
    // reveal_may_check is a cheap necessary condition for any identity to differ.
    bool reveal_gives_check(int from, int to, PieceType t) const;
    bool reveal_may_check(int to) const;
    // Square attacked by `by` (king-centric test; adequate for capture safety heuristics).
    bool attacked(Color by, int s) const { return king_attacked(~by, s); }
    int gen_legal(Move* list) const;
    bool has_legal_move() const;

    // m must carry a reveal type when the mover is face down.
    void do_move(Move m, StateInfo& st);
    uint64_t key_after(Move m) const;  // the key do_move(m) will produce (m carries the reveal for a dark mover)
    void undo_move(Move m, const StateInfo& st);
    void do_null(StateInfo& st);
    void undo_null(const StateInfo& st);

    // 0: none, 1: draw, 2: side to move wins (opponent perpetually checked or chased), 3: side to move loses.
    int repetition_status() const;
    std::bitset<NUM_SQ> chase_threats(Color actor) const;  // enemy squares actor threatens under the chase rule
    bool has_major(Color c) const;
    uint64_t compute_key() const;
    bool valid(std::string* error = nullptr) const;

private:
    int chase_verdict(int first) const;
    void add_piece(int s, Piece p);
    void remove_piece(int s);
    void move_piece(int from, int to);
    void push_history() { keyHist.push_back(key); checkHist.push_back(uint8_t(in_check())); }
};

std::string move_str(Move m);
Move parse_move_coords(const std::string& s);
char piece_char(Piece p);

extern const char* START_FEN;

}  // namespace jq
