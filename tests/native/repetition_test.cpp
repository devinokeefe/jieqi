#include "jieqi/repetition.hpp"
#include "jieqi/c_api.h"
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

using namespace jieqi;
namespace {
int checks = 0;
void expect(bool value, const char* label) {
    ++checks;
    if (!value) throw std::runtime_error(label);
}
template<class F> void rejects(F f, const char* label) {
    bool failed = false;
    try { f(); } catch (const std::exception&) { failed = true; }
    expect(failed, label);
}
Position position(std::initializer_list<std::pair<const char*, char>> pieces,
                  Color turn = Color::Red, std::uint32_t idle = 0) {
    std::string board(90, '.');
    for (auto [point, code] : pieces) board[static_cast<std::size_t>(square(point))] = code;
    return Position(board, turn, idle);
}
void play(RepetitionHistory& h, std::initializer_list<const char*> moves) {
    for (auto move : moves) h.append(parse_move(move));
}
void occurrence_and_checks() {
    RepetitionHistory quiet(position({{"e0", 'K'}, {"d9", 'k'}}));
    play(quiet, {"e0f0", "d9d8", "f0e0", "d8d9"});
    expect(quiet.repetition().status == RepetitionStatus::NotRepeated, "twofold is not root repetition");
    play(quiet, {"e0f0", "d9d8", "f0e0", "d8d9"});
    auto r = quiet.repetition();
    expect(r.status == RepetitionStatus::ChaseRequired && r.begin == 0 && r.end == 8,
           "third occurrence requests explicit chase evidence");
    std::vector<ChaseTargets> empty(8);
    expect(quiet.with_chase_evidence(empty).status == RepetitionStatus::Draw, "empty evidence draws");
    rejects([&] { (void)quiet.with_chase_evidence(std::span(empty).first(4)); }, "must classify both cycles");
    RepetitionHistory checking(position({{"d0", 'K'}, {"e9", 'k'}, {"e7", 'R'}}, Color::Black, 72));
    for (int i = 0; i < 2; ++i) play(checking, {"e9f9", "e7f7", "f9e9", "f7e7"});
    r = checking.repetition();
    expect(r.status == RepetitionStatus::RedLoses && r.perpetual_check[0] && !r.perpetual_check[1],
           "red perpetual checking responsibility");
    expect(checking.current().no_capture_plies() == 80, "checking repetition does not become clock draw");
    rejects([&] { (void)checking.with_chase_evidence(empty); }, "no chase override of check verdict");
    RepetitionHistory unequal(position({{"d0", 'K'}, {"e9", 'k'}, {"e7", 'R'}}, Color::Black));
    play(unequal, {"e9f9", "e7e6", "f9f8", "e6e7", "f8f9", "e7f7", "f9e9", "f7e7", "e9f9"});
    r = unequal.repetition();
    expect(r.begin == 1 && r.end == 9 && r.status == RepetitionStatus::Draw && r.any_check,
           "full second-earlier interval prevents nearest-cycle false checking loss");
}
void physical_ids_and_reduction() {
    RepetitionHistory exchange(position({{"e0", 'K'}, {"d9", 'k'}, {"a1", 'R'}, {"b2", 'R'}}));
    const auto a = square("a1"), b = square("b2");
    auto cycle = [&] { play(exchange, {"a1a2", "d9d8", "b2b1", "d8d9", "a2b2", "d9d8", "b1a1", "d8d9"}); };
    cycle();
    expect(exchange.physical_id(8, a) == b && exchange.physical_id(8, b) == a, "IDs follow exchanged rooks");
    expect(exchange.repetition().status == RepetitionStatus::NotRepeated, "ID swap does not erase board occurrence");
    cycle();
    expect(exchange.repetition().begin == 0 && exchange.repetition().status == RepetitionStatus::ChaseRequired,
           "repetition compares public types, not physical IDs");
    expect(exchange.physical_id(16, a) == a, "IDs restored after second exchange");
    RepetitionHistory chase(position({{"d0", 'K'}, {"e9", 'k'}, {"a1", 'R'}, {"b3", 'n'}, {"h7", 'n'}}));
    for (int i = 0; i < 2; ++i) play(chase, {"a1b1", "b3a5", "b1a1", "a5b3"});
    std::vector<ChaseTargets> evidence(8);
    for (std::size_t i = 0; i < 8; i += 2) evidence[i].set(static_cast<std::size_t>(square("b3")));
    expect(chase.with_chase_evidence(evidence).status == RepetitionStatus::RedLoses, "fixed physical target intersection");
    evidence[2].reset(); evidence[2].set(static_cast<std::size_t>(square("h7")));
    expect(chase.with_chase_evidence(evidence).status == RepetitionStatus::Draw, "same-type targets cannot be merged");
    evidence[2] = evidence[0];
    for (std::size_t i = 1; i < 8; i += 2) evidence[i].set(static_cast<std::size_t>(square("a1")));
    expect(chase.with_chase_evidence(evidence).status == RepetitionStatus::Draw, "both supplied chasers draw");
    for (std::size_t i = 0; i < 8; i += 2) evidence[i].reset();
    expect(chase.with_chase_evidence(evidence).status == RepetitionStatus::BlackLoses, "black supplied responsibility");
    for (int invalid : {square("d0"), square("e9"), square("c4"), square("a1")}) {
        evidence[0].reset(); evidence[0].set(static_cast<std::size_t>(invalid));
        rejects([&] { (void)chase.with_chase_evidence(evidence); }, "invalid target identity rejected");
    }
}
void monotonic_boundaries_and_errors() {
    RepetitionHistory reveal(position({{"e0", 'K'}, {"d9", 'k'}, {"a3", 'X'}}, Color::Red, 79));
    const auto old = reveal.current().public_board();
    rejects([&] { reveal.append(parse_move("a3a4")); }, "missing reveal rejected atomically");
    expect(reveal.size() == 1 && reveal.repetition_boundary() == 0 && reveal.current().public_board() == old,
           "rejected append preserves position and history");
    reveal.append(parse_move("a3a4"), Kind::Soldier);
    expect(reveal.repetition_boundary() == 1 && reveal.current().no_capture_plies() == 80,
           "reveal resets repetition boundary but not capture clock");
    expect(reveal.physical_id(1, square("a4")) == square("a3"), "reveal preserves physical identity");
    RepetitionHistory capture(position({{"e0", 'K'}, {"d9", 'k'}, {"a1", 'R'}, {"a2", 'p'}}, Color::Red, 79));
    capture.append(parse_move("a1a2"));
    expect(capture.repetition_boundary() == 1 && capture.current().no_capture_plies() == 0,
           "capture resets both boundaries");
    expect(capture.physical_id(1, square("a2")) == square("a1") && capture.physical_id(1, square("a1")) == -1,
           "captured ID disappears without ID recycling");
    rejects([&] { (void)capture.physical_id(2, 0); }, "invalid snapshot rejected");
    rejects([&] { (void)capture.physical_id(0, -1); }, "invalid square rejected");
}
void c_api_atomicity() {
    auto board = position({{"e0", 'K'}, {"d9", 'k'}}).public_board();
    int status = 99, bits = 99;
    std::size_t begin = 99, end = 99;
    char error[128]{};
    const std::uint16_t illegal = static_cast<std::uint16_t>(square("e0")*90+square("a5"));
    const char reveal = 0;
    expect(jq_repetition_replay(board.data(), 90, 0, 0, &illegal, &reveal, 1,
            &status, &begin, &end, &bits, error, sizeof(error)) == JQ_INVALID, "invalid replay rejected");
    expect(status == 99 && begin == 99 && end == 99 && bits == 99, "failed replay does not write outputs");
    expect(jq_repetition_replay(board.data(), 90, 0, 0, nullptr, nullptr, 0,
            &status, &begin, &end, &bits, error, sizeof(error)) == JQ_OK, "empty diagnostic replay");
    expect(status == 0 && begin == 0 && end == 0 && bits == 0, "empty replay reports no repetition");
}
}  // namespace
int main() {
    try {
        occurrence_and_checks(); physical_ids_and_reduction(); monotonic_boundaries_and_errors(); c_api_atomicity();
        std::cout << "Native repetition assertions passed: " << checks << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Native repetition assertion failed after " << checks << ": " << error.what() << '\n';
        return 1;
    }
}
