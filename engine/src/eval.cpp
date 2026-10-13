#include "eval.h"

#include "nnue.h"

namespace jq {

int PieceValue[9] = {0, 0, 900, 400, 230, 230, 450, 100, 0};

int urn_mean_value(const Position& pos, Color c) {
    if (pos.urnTotal[c] <= 0) return 0;
    int sum = 0;
    for (int sl = 0; sl < NUM_SLOTS; ++sl) sum += pos.urn[c][sl] * PieceValue[slot_type(sl)];
    return sum / pos.urnTotal[c];
}

namespace {
int mobility_ray(const Position& pos, int s) {
    int n = 0;
    for (int d = 0; d < 4; ++d)
        for (int j = 0; j < T.rayLen[s][d]; ++j) {
            if (pos.board[T.ray[s][d][j]]) break;
            ++n;
        }
    return n;
}

int side_score(const Position& pos, Color c) {
    int score = 0;
    const int darkValue = urn_mean_value(pos, c);
    const int enemyKing = pos.kingSq[~c];
    for (int i = 0; i < pos.pcount[c]; ++i) {
        const int s = pos.plist[c][i];
        const PieceType t = type_of(pos.board[s]);
        const int rel = c == RED ? rank_of(s) : 9 - rank_of(s);  // 0 = own back rank
        const int centre = 4 - (file_of(s) > 4 ? file_of(s) - 4 : 4 - file_of(s));
        switch (t) {
        case DARK: score += darkValue; break;
        case ROOK: score += PieceValue[ROOK] + 6 * mobility_ray(pos, s); break;
        case CANNON: score += PieceValue[CANNON] + 2 * mobility_ray(pos, s) + (file_of(s) == file_of(enemyKing) ? 25 : 0); break;
        case HORSE: score += PieceValue[HORSE] + 8 * centre + (rel >= 3 && rel <= 7 ? 20 : 0); break;
        case SOLDIER:
            if (rel >= 5) score += 2 * PieceValue[SOLDIER] + (rel <= 8 ? 15 * (rel - 4) : 0) + 6 * centre;
            else score += PieceValue[SOLDIER];
            break;
        case ADVISOR: case ELEPHANT: score += PieceValue[t]; break;
        default: break;
        }
    }
    return score;
}
}  // namespace

Value classical_eval(const Position& pos) {
    const int v = side_score(pos, RED) - side_score(pos, BLACK);
    return (pos.stm == RED ? v : -v) + 20;
}

Value evaluate(const Position& pos) {
    if (nnue::loaded()) return nnue::evaluate(pos);
    return classical_eval(pos);
}

}  // namespace jq
