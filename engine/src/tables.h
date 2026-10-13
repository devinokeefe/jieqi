// Precomputed geometry for the 9x10 board.
#pragma once
#include "types.h"

namespace jq {

enum Dir : int { NORTH = 0, SOUTH = 1, EAST = 2, WEST = 3 };  // NORTH = towards rank 9

struct Tables {
    uint8_t ray[NUM_SQ][4][9];
    uint8_t rayLen[NUM_SQ][4];
    // Horse moves from a square: destination and blocking "leg" square.
    uint8_t horseTo[NUM_SQ][8], horseLeg[NUM_SQ][8], horseN[NUM_SQ];
    // Squares from which a horse attacks this square, with the attacker's leg square.
    uint8_t horseFrom[NUM_SQ][8], horseFromLeg[NUM_SQ][8], horseFromN[NUM_SQ];
    uint8_t elephTo[NUM_SQ][4], elephEye[NUM_SQ][4], elephN[NUM_SQ];
    uint8_t advTo[NUM_SQ][4], advN[NUM_SQ];
    uint8_t kingTo[NUM_SQ][4], kingN[NUM_SQ];   // orthogonal steps staying inside the same palace
    uint8_t darkRole[2][NUM_SQ];                // PieceType role of a face-down piece, 0 if not a start point
    int8_t dirTo[NUM_SQ][NUM_SQ];               // ray direction from the first square to the second, -1 if none
    uint64_t zPiece[PIECE_CODES][NUM_SQ];
    uint64_t zSide;
    uint64_t zUrn[2][NUM_SLOTS][8];
};

extern Tables T;
void init_tables();

}  // namespace jq
