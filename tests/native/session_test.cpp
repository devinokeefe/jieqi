#include "jieqi/c_api.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
int checks=0;
void expect(bool b,const char* message) {++checks;if(!b) throw std::runtime_error(message);}
int main() {
    try {
        std::string board(90,'.');board[4]='K';board[84]='k';board[27]='X';
        jq_game* game=nullptr;char error[256]{};
        expect(jq_game_create(board.data(),90,0,0,0,&game,error,256)==JQ_INVALID && game==nullptr,"invalid limit leaves null output");
        expect(jq_game_create(board.data(),90,0,79,80,&game,error,256)==JQ_OK && game!=nullptr,"create public history");
        std::array<char,90> out;out.fill('!');int side=99,status=99;uint32_t idle=99;size_t plies=99;
        expect(jq_game_snapshot(game,out.data(),89,&side,&idle,&plies,&status,error,256)==JQ_BUFFER_TOO_SMALL,"short snapshot");
        expect(out[0]=='!' && side==99 && idle==99 && plies==99 && status==99,"snapshot failure atomic");
        expect(jq_game_advance(game,27,36,0,error,256)==JQ_INVALID,"missing reveal rejected");
        expect(jq_game_snapshot(game,out.data(),90,&side,&idle,&plies,&status,error,256)==JQ_OK,"snapshot after rejected advance");
        expect(std::string(out.data(),90)==board && side==0 && idle==79 && plies==0 && status==0,"rejected advance preserves full state");
        expect(jq_game_advance(game,27,36,'N',error,256)==JQ_OK,"advance with public reveal");
        expect(jq_game_snapshot(game,out.data(),90,&side,&idle,&plies,&status,error,256)==JQ_OK,"terminal snapshot");
        expect(out[27]=='.' && out[36]=='N' && side==1 && idle==80 && plies==1 && status==1,"revealed clock terminal");
        expect(jq_game_advance(game,84,75,0,error,256)==JQ_INVALID,"no terminal continuation");
        jq_game_destroy(game);jq_game_destroy(nullptr);
        expect(jq_game_advance(nullptr,4,5,0,error,256)==JQ_INVALID,"null handle rejected");
        for(int i=0;i<100;++i) {
            game=nullptr;expect(jq_game_create(board.data(),90,0,0,80,&game,error,256)==JQ_OK,"repeated ownership");
            jq_game_destroy(game);
        }
        std::cout<<"Native session assertions passed: "<<checks<<'\n';return 0;
    } catch(const std::exception& e) {std::cerr<<"Session test failed: "<<e.what()<<'\n';return 1;}
}
