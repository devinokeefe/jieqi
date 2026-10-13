#include "jieqi/repetition.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace jieqi {
namespace {
std::size_t side_index(Color color) { return color == Color::Red ? 0U : 1U; }
RepetitionStatus responsibility(bool red, bool black) {
    if (red == black) return RepetitionStatus::Draw;
    return red ? RepetitionStatus::RedLoses : RepetitionStatus::BlackLoses;
}
}  // namespace

RepetitionHistory::RepetitionHistory(Position initial) {
    std::array<int, 90> ids;
    ids.fill(-1);
    for (std::size_t s = 0; s < ids.size(); ++s)
        if (initial.board()[s].kind != Kind::Empty) ids[s] = static_cast<int>(s);
    const bool checked = initial.in_check(initial.turn());
    snapshots_.push_back({std::move(initial), ids, checked});
}

void RepetitionHistory::append(Move move, Kind reveal) {
    const auto& prior = snapshots_.back();
    // apply validates coordinates and legality before any indexing below.
    Position next = prior.position.apply(move, reveal);
    const auto from = static_cast<std::size_t>(move.from);
    const auto to = static_cast<std::size_t>(move.to);
    const bool monotonic = prior.position.board()[to].kind != Kind::Empty ||
                           prior.position.board()[from].kind == Kind::Dark;
    auto ids = prior.ids;
    ids[to] = ids[from];
    ids[from] = -1;
    const bool checked = next.in_check(next.turn());
    // push_back is the only potentially allocating mutation. Commit the boundary
    // afterwards; a rejected move or allocation exception cannot erase history.
    snapshots_.push_back({std::move(next), ids, checked});
    if (monotonic) boundary_ = snapshots_.size() - 1;
}

int RepetitionHistory::physical_id(std::size_t snapshot, int square_index) const {
    if (snapshot >= snapshots_.size() || square_index < 0 || square_index >= 90)
        throw std::invalid_argument("invalid history ID lookup");
    return snapshots_[snapshot].ids[static_cast<std::size_t>(square_index)];
}

RepetitionReport RepetitionHistory::repetition() const {
    const auto end = snapshots_.size() - 1;
    RepetitionReport report;
    report.begin = report.end = end;
    if (end - boundary_ < 8) return report;
    const auto& final = current();
    int matches = 0;
    // Exact public board comparisons avoid Zobrist collisions. Private pools and
    // counters are irrelevant within this capture-free, reveal-free interval.
    for (std::size_t distance = 4; distance <= end - boundary_; distance += 2) {
        const auto i = end - distance;
        const auto& candidate = snapshots_[i].position;
        if (candidate.turn() != final.turn() || candidate.board() != final.board()) continue;
        if (++matches == 2) {
            report.begin = i;
            break;
        }
    }
    if (matches != 2) return report;
    report.perpetual_check.fill(true);
    for (std::size_t i = report.begin; i < end; ++i) {
        const auto actor = snapshots_[i].position.turn();
        const bool check = snapshots_[i + 1].checked;
        report.perpetual_check[side_index(actor)] = report.perpetual_check[side_index(actor)] && check;
        report.any_check = report.any_check || check;
    }
    if (report.perpetual_check[0] || report.perpetual_check[1])
        report.status = responsibility(report.perpetual_check[0], report.perpetual_check[1]);
    else if (report.any_check)
        report.status = RepetitionStatus::Draw;  // Pinned newer mixed-check convention.
    else
        report.status = RepetitionStatus::ChaseRequired;
    return report;
}

RepetitionReport RepetitionHistory::with_chase_evidence(std::span<const ChaseTargets> targets) const {
    auto report = repetition();
    if (report.status != RepetitionStatus::ChaseRequired)
        throw std::invalid_argument("chase evidence requires an unchecked repetition interval");
    if (targets.size() != report.end - report.begin)
        throw std::invalid_argument("chase evidence must cover the complete repeated interval");
    std::array<ChaseTargets, 2> common;
    for (auto& mask : common) mask.set();
    for (std::size_t i = report.begin; i < report.end; ++i) {
        const auto actor = snapshots_[i].position.turn();
        const auto& after = snapshots_[i + 1];
        ChaseTargets allowed;
        for (std::size_t s = 0; s < 90; ++s) {
            const auto piece = after.position.board()[s];
            if (piece.kind != Kind::Empty && piece.kind != Kind::King && piece.color != actor)
                allowed.set(static_cast<std::size_t>(after.ids[s]));
        }
        const auto supplied = targets[i - report.begin];
        if ((supplied & ~allowed).any())
            throw std::invalid_argument("chase evidence contains absent, friendly or king IDs");
        common[side_index(actor)] &= supplied;
    }
    report.status = responsibility(common[0].any(), common[1].any());
    return report;
}
RepetitionReport RepetitionHistory::adjudicate_repetition() const {
    auto report = repetition();
    if (report.status != RepetitionStatus::ChaseRequired) return report;
    auto threats = [&](std::size_t index, Color actor) {
        const auto squares = snapshots_[index].position.chase_targets(actor);
        ChaseTargets ids;
        for (std::size_t s = 0; s < 90; ++s)
            if (squares[s]) ids.set(static_cast<std::size_t>(snapshots_[index].ids[s]));
        return ids;
    };
    std::vector<ChaseTargets> newly_threatened;
    for (std::size_t i = report.begin; i < report.end; ++i) {
        const auto actor = snapshots_[i].position.turn();
        newly_threatened.push_back(threats(i + 1, actor) & ~threats(i, actor));
    }
    return with_chase_evidence(newly_threatened);
}

GameStatus RepetitionHistory::terminal_status(std::uint32_t limit) const {
    if (limit == 0) throw std::invalid_argument("no-capture limit must be positive");
    if (current().legal_moves().empty())
        return current().turn() == Color::Red ? GameStatus::RedLoses : GameStatus::BlackLoses;
    const auto report = adjudicate_repetition();
    if (report.status != RepetitionStatus::NotRepeated) return static_cast<GameStatus>(report.status);
    return current().no_capture_plies() >= limit ? GameStatus::Draw : GameStatus::Ongoing;
}

void RepetitionHistory::append_game(Move move, Kind reveal, std::uint32_t limit) {
    if (terminal_status(limit) != GameStatus::Ongoing)
        throw std::invalid_argument("cannot continue an adjudicated terminal position");
    append(move, reveal);
}
}  // namespace jieqi
