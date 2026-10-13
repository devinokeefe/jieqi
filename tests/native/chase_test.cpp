#include "jieqi/repetition.hpp"
#include "jieqi/c_api.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
using namespace jieqi;
namespace {
int checks=0;
void expect(bool value,const char* label) { ++checks; if(!value) throw std::runtime_error(label); }
template<class F> void rejects(F f,const char* label) {
    bool failed=false;try {f();}catch(const std::exception&) {failed=true;}expect(failed,label);
}
Position position(std::initializer_list<std::pair<const char*,char>> pieces, Color turn=Color::Red, std::uint32_t idle=0) {
    std::string board(90,'.');for(auto [point,code]:pieces) board[static_cast<std::size_t>(square(point))]=code;
    return Position(board,turn,idle);
}
void threat_cases() {
    for(char minor: {'A','B'}) for(char target: {'r','n','c'}) {
        auto p=position({{"d0",'K'},{"f9",'k'},{"b3",minor},{minor=='A'?"c4":"d5",target},{minor=='A'?"i4":"i5",'r'}});
        const auto before=p.public_board();
        expect(p.chase_targets(Color::Red)[static_cast<std::size_t>(square(minor=='A'?"c4":"d5"))],"protected major exception");
        expect(p.public_board()==before,"threat query preserves board");
    }
    auto p=position({{"d0",'K'},{"f9",'k'},{"b3",'N'},{"c5",'n'}});
    expect(!p.chase_targets(Color::Red)[static_cast<std::size_t>(square("c5"))],"symmetric horse exemption");
    p=position({{"d0",'K'},{"f9",'k'},{"b3",'N'},{"c5",'n'},{"c4",'P'}});
    expect(p.chase_targets(Color::Red)[static_cast<std::size_t>(square("c5"))],"asymmetric horse leg");
    p=position({{"d0",'X'},{"e0",'K'},{"f9",'k'},{"c1",'r'}});
    expect(!p.is_legal(parse_move("d0c1")),"ordinary dark advisor cannot leave palace");
    expect(p.chase_targets(Color::Red)[static_cast<std::size_t>(square("c1"))],"chase uses advisor positional type");
    p=position({{"d0",'K'},{"f9",'k'},{"a3",'R'},{"b3",'n'},{"b9",'r'},{"a9",'R'}});
    expect(p.chase_targets(Color::Red)[static_cast<std::size_t>(square("b3"))],"pinned defender cannot recapture");
    p=position({{"d0",'K'},{"f9",'k'},{"d3",'N'},{"d8",'r'},{"e5",'p'}});
    expect(!p.chase_targets(Color::Red)[static_cast<std::size_t>(square("e5"))],"pinned attacker filtered");
    rejects([&]{(void)p.chase_targets(static_cast<Color>(99));},"invalid actor");
}
void strict_terminal() {
    RepetitionHistory chase(position({{"d0",'K'},{"e9",'k'},{"a1",'R'},{"b3",'n'},{"h7",'n'}}));
    for(int i=0;i<2;++i) for(auto m:{"a1b1","b3a5","b1a1","a5b3"}) chase.append_game(parse_move(m));
    expect(chase.terminal_status()==GameStatus::RedLoses,"actual chase responsibility");
    auto size=chase.size();auto board=chase.current().public_board();
    rejects([&]{chase.append_game(parse_move("a1b1"));},"cannot continue chase loss");
    expect(chase.size()==size && chase.current().public_board()==board,"terminal rejection atomic");
    RepetitionHistory clock(position({{"e0",'K'},{"d9",'k'},{"a3",'X'}},Color::Red,79));
    clock.append_game(parse_move("a3a4"),Kind::Horse);
    expect(clock.terminal_status()==GameStatus::Draw,"noncapture reveal reaches draw clock");
    rejects([&]{clock.append_game(parse_move("d9d8"));},"clock cannot be advanced");
    rejects([&]{(void)clock.terminal_status(0);},"zero clock limit invalid");
    RepetitionHistory mate(position({{"e0",'K'},{"d9",'k'},{"d1",'r'},{"f1",'r'}},Color::Red,80));
    expect(mate.terminal_status()==GameStatus::RedLoses,"stalemate before clock draw");
}
void abi_errors() {
    const auto board=position({{"e0",'K'},{"d9",'k'}}).public_board();
    std::array<unsigned char,90> out;out.fill(99);char error[256]{};int result=99;
    expect(jq_chase_targets(board.data(),90,0,out.data(),89,error,sizeof(error))==JQ_BUFFER_TOO_SMALL,"short mask output");
    expect(out[0]==99 && out[89]==99,"short output unchanged");
    expect(jq_chase_targets(board.data(),90,0,nullptr,90,error,sizeof(error))==JQ_INVALID,"null chase output");
    expect(jq_chase_targets(board.data(),90,0,out.data(),90,error,sizeof(error))==JQ_OK,"quiet king chase query");
    expect(out[0]==0 && out[89]==0,"quiet empty mask");
    const std::uint16_t move=static_cast<std::uint16_t>(square("e0")*90+square("f0"));const char reveal=0;
    expect(jq_game_replay(board.data(),90,0,80,&move,&reveal,1,80,&result,error,sizeof(error))==JQ_INVALID,"strict ABI rejects terminal continuation");
    expect(result==99,"failed replay preserves output");
    expect(jq_game_replay(board.data(),90,0,80,nullptr,nullptr,0,80,&result,error,sizeof(error))==JQ_OK && result==1,"empty terminal replay");
}
}
int main() {
    try {threat_cases();strict_terminal();abi_errors();std::cout<<"Native chase assertions passed: "<<checks<<'\n';return 0;}
    catch(const std::exception& e) {std::cerr<<"Native chase assertion failed after "<<checks<<": "<<e.what()<<'\n';return 1;}
}
