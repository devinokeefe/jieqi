// NNUE evaluation (original design, float inference).
//
// Inputs per perspective P (1470): piece-square features for 16 kinds (own/opponent x K R N B A C
// P face-down) on 90 squares, oriented so that P's home rank is rank 0; plus urn thresholds
// "urn[c][t] >= j" (15 per colour, own colour first). Feature transformer 1470 -> FT (+1 PSQT
// column), shared by both perspectives; then [us, them] -> L1 -> L2 -> 1 with clipped ReLU.
#pragma once
#include "position.h"

#include <string>

namespace jq::nnue {

constexpr int NUM_PIECE_FEATURES = 16 * NUM_SQ;          // 1440 (per king bucket)
constexpr int NUM_URN_FEATURES = 30;
constexpr int NUM_FEATURES = NUM_PIECE_FEATURES + NUM_URN_FEATURES;  // 1470 (version-1 nets)
constexpr int MAX_FT = 1024;
constexpr int URN_OFFSET[NUM_SLOTS] = {0, 2, 4, 6, 8, 10};  // cumulative URN_INIT

inline int orient(Color persp, int s) { return persp == RED ? s : (9 - rank_of(s)) * 9 + file_of(s); }
// Version-2 nets replicate the piece features per bucket of the perspective's own king square
// (3 = king file, 9 = palace square); urn features follow all buckets. Set by load().
extern int g_kingBuckets;
extern int g_urnBase;  // g_kingBuckets * NUM_PIECE_FEATURES
inline int king_bucket_offset(Color persp, int ksq) {
    if (g_kingBuckets == 1) return 0;
    const int ko = orient(persp, ksq);
    const int b = g_kingBuckets == 9 ? (ko / 9) * 3 + (ko % 9 - 3) : ko % 9 - 3;
    return b * NUM_PIECE_FEATURES;
}
inline int piece_feature(Color persp, Piece p, int s, int kbOff) {
    const int rel = color_of(p) == persp ? 0 : 8;
    return kbOff + (rel + int(type_of(p)) - 1) * NUM_SQ + orient(persp, s);
}
// Feature for "urn[owner][slot] >= j", j in 1..URN_INIT[slot].
inline int urn_feature(Color persp, Color owner, int slot, int j) {
    return g_urnBase + (owner == persp ? 0 : 15) + URN_OFFSET[slot] + j - 1;
}

struct alignas(64) Accumulator {
    float v[2][MAX_FT + 16];     // float path
    int16_t q[2][MAX_FT + 32];   // quantized path (scale QF = 254)
};

// Feature changes caused by one move (position before the move).
struct Dirty {
    int nRem = 0, nAdd = 0;
    Piece remP[2], addP[1];
    int8_t remS[2], addS[1];
    int8_t urnOwner = -1, urnSlot = 0, urnJ = 0;  // removed urn threshold feature, if any
    int8_t refresh = -1;          // perspective whose king changed bucket: needs a full refresh
    int16_t kbOff[2] = {0, 0};    // king-bucket feature offsets per perspective
};

bool load(const std::string& path, std::string* error = nullptr);
void unload();
void set_flush_denormals();  // call once per thread that evaluates (denormals are very slow)
// Quantized inference (int16 accumulators, int8 L1) is used when available and enabled.
void set_quantized(bool on);
bool quantized();
bool loaded();
int ft_size();  // FT width including the PSQT column

void refresh(const Position& pos, Accumulator& acc);
void make_dirty(const Position& pos, Move m, Dirty& d);  // m carries the reveal for a dark mover
// Incremental update; not valid when d.refresh >= 0 (refresh from the new position instead).
void update(const Accumulator& prev, Accumulator& next, const Dirty& d);
Value evaluate(const Accumulator& acc, Color stm);
Value evaluate(const Position& pos);  // full refresh; for tools and the root

}  // namespace jq::nnue
