#pragma once

#include "jieqi/rules.hpp"
#include <bitset>
#include <cstddef>
#include <span>

namespace jieqi {

// Public history and strict pinned-fallback referee. The diagnostic repetition()
// entry retains an explicit ChaseRequired result; adjudicate_repetition() resolves it.
enum class RepetitionStatus : int {
    NotRepeated = 0, Draw = 1, RedLoses = 2, BlackLoses = 3, ChaseRequired = 4
};
struct RepetitionReport {
    RepetitionStatus status = RepetitionStatus::NotRepeated;
    std::size_t begin = 0;  // Snapshot index of the second earlier occurrence.
    std::size_t end = 0;    // Current snapshot index (relative to initial input).
    std::array<bool, 2> perpetual_check{};
    bool any_check = false;
};
enum class GameStatus : int { Ongoing = 0, Draw = 1, RedLoses = 2, BlackLoses = 3 };
using ChaseTargets = std::bitset<90>;  // Stable physical IDs, NOT current squares.

class RepetitionHistory {
public:
    explicit RepetitionHistory(Position initial);
    // Legal geometry/reveal only. Does not authorize continuing a terminal game.
    // Failed appends leave the history unchanged.
    void append(Move move, Kind reveal = Kind::Empty);
    const Position& current() const { return snapshots_.back().position; }
    std::size_t size() const { return snapshots_.size(); }
    std::size_t repetition_boundary() const { return boundary_; }
    int physical_id(std::size_t snapshot, int square_index) const;
    RepetitionReport repetition() const;
    RepetitionReport adjudicate_repetition() const;
    GameStatus terminal_status(std::uint32_t no_capture_limit = 80) const;
    void append_game(Move move, Kind reveal = Kind::Empty, std::uint32_t no_capture_limit = 80);
    // Pure responsibility reduction, shared with the integrated threat classifier.
    // Input: newly qualifying target IDs for EVERY move in [begin,end).
    // It checks IDs/ownership but DOES NOT certify threat geometry or provenance.
    // Only callable on a ChaseRequired report. Never exposed as a rated referee.
    RepetitionReport with_chase_evidence(std::span<const ChaseTargets> new_targets) const;

private:
    struct Snapshot {
        Position position;
        std::array<int, 90> ids;
        bool checked;
    };
    std::vector<Snapshot> snapshots_;
    std::size_t boundary_ = 0;
};
}  // namespace jieqi
