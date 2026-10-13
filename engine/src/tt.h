// Shared transposition table. Lockless: each entry's key field holds key ^ data, so an entry torn by
// concurrent writers fails validation and reads as a miss; probes return a private copy of the data.
#pragma once
#include "mem.h"
#include "types.h"

#include <algorithm>
#include <cstring>
#include <new>

namespace jq {

struct TTEntry {
    uint64_t key;  // position key ^ data word (in the table); the plain key in a probed copy
    uint16_t move;
    int16_t value;
    int16_t eval;
    uint8_t depth;
    uint8_t genBound;  // generation << 2 | bound
};
static_assert(sizeof(TTEntry) == 16, "TTEntry layout");

extern int g_ttWays;  // 1: one entry per slot; 2 / 4: buckets of 2 / 4 entries (worth-based replacement)

class TranspositionTable {
public:
    struct alignas(64) Line { TTEntry e[4]; };

    TranspositionTable() = default;
    TranspositionTable(const TranspositionTable&) = delete;
    TranspositionTable& operator=(const TranspositionTable&) = delete;
    ~TranspositionTable() { std::free(table_); }

    void resize(std::size_t mb) {
        std::size_t n = 1;  // entries (a power of two, at least one cache line)
        while (n * 2 * sizeof(TTEntry) <= mb * 1024 * 1024) n *= 2;
        n = std::max<std::size_t>(n, 4);
        std::free(table_);
        table_ = static_cast<Line*>(alloc_large(n / 4 * sizeof(Line)));  // zeroed; huge pages where the kernel gives them
        if (!table_) throw std::bad_alloc();
        lines_ = n / 4;
        mask_ = n - 1;  // entry index mask
    }
    void clear() { std::memset(static_cast<void*>(table_), 0, lines_ * sizeof(Line)); }
    void new_search() { gen_ = uint8_t((gen_ + 1) & 63); }
    // Starts loading the cache line of key's slot: issued when a move is chosen, it hides most of the cache miss
    // the child's probe would otherwise wait for.
    void prefetch(uint64_t key) const { __builtin_prefetch(&table_[(key & mask_) >> 2]); }

    // Returns the matching slot (found = true, out = validated copy) or the slot to overwrite.
    TTEntry* probe(uint64_t key, bool& found, TTEntry& out) {
        const int ways = g_ttWays >= 4 ? 4 : g_ttWays > 1 ? 2 : 1;
        const std::size_t idx = key & mask_ & ~std::size_t(ways - 1);
        TTEntry* first = &table_[idx >> 2].e[idx & 3];
        for (int i = 0; i < ways; ++i) {
            TTEntry e = first[i];
            if ((e.key ^ data(e)) == key && (e.genBound & 3) != BOUND_NONE) {
                found = true;
                e.key = key;
                out = e;
                return &first[i];
            }
        }
        found = false;
        out = TTEntry{};
        if (ways == 1) return first;
        TTEntry* r = first;
        for (int i = 1; i < ways; ++i)
            if (worth(first[i]) < worth(*r)) r = &first[i];
        return r;
    }
    void store(TTEntry* slot, uint64_t key, Value v, Bound b, int depth, Move m, Value eval) {
        const TTEntry old = *slot;
        const bool sameKey = (old.key ^ data(old)) == key;
        if (!sameKey || depth + 2 >= old.depth || b == BOUND_EXACT || (old.genBound >> 2) != gen_) {
            TTEntry e;
            e.move = (m != MOVE_NONE || !sameKey) ? uint16_t(base_move(m)) : old.move;
            e.value = int16_t(v);
            e.eval = int16_t(eval);
            e.depth = uint8_t(depth < 0 ? 0 : depth > 255 ? 255 : depth);
            e.genBound = uint8_t(gen_ << 2 | b);
            e.key = key ^ data(e);
            *slot = e;
        }
    }
    int hashfull() const {
        int n = 0;
        for (std::size_t i = 0; i < 250 && i < lines_; ++i)
            for (const TTEntry& e : table_[i].e) n += (e.genBound & 3) != BOUND_NONE && (e.genBound >> 2) == gen_;
        return n;
    }

private:
    static uint64_t data(const TTEntry& e) {
        uint64_t d;
        std::memcpy(&d, &e.move, sizeof d);
        return d;
    }
    int worth(const TTEntry& e) const {
        if ((e.genBound & 3) == BOUND_NONE) return -1000;
        return int(e.depth) - 8 * ((gen_ - (e.genBound >> 2)) & 63);
    }
    Line* table_ = nullptr;
    std::size_t lines_ = 0;
    std::size_t mask_ = 0;
    uint8_t gen_ = 0;
};

}  // namespace jq
