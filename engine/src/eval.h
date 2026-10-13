#pragma once
#include "position.h"

namespace jq {

extern int PieceValue[9];          // indexed by PieceType (DARK unused)
int urn_mean_value(const Position& pos, Color c);
Value classical_eval(const Position& pos);   // side-to-move perspective
Value evaluate(const Position& pos);         // NNUE if loaded, otherwise classical

}  // namespace jq
