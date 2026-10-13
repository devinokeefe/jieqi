#include "eval.h"
#include "nnue.h"
#include "search.h"

#include <chrono>
#include <cstdio>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

namespace jq {

void selfplay(std::istringstream& is);

namespace {

std::mutex outMutex;
void out(const std::string& s) {
    std::lock_guard<std::mutex> lock(outMutex);
    std::cout << s << std::endl;
}

const char* BENCH_FENS[] = {
    "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1",
    "xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/4P4/X1X3X1X/1X5X1/9/XXXXKXXXX b R2A2C2P4N2B2r2a2c2p5n2b2 1 1",
    "r1xxkxxxx/9/1x5c1/x1x1x1x1x/9/9/X1X1X1X1X/1C5X1/9/XXXXKXXXX w R2A2C1P5N2B2r1a2c1p5n2b2 2 2",
    "2xakxxxx/4r4/1x5c1/x1x1x1x1p/9/2P6/X1X1X1X1X/1C5X1/9/XXXXKXXXX w R2A2C1P4N2B2r1a1c1p4n2b2 0 4",
    "4k4/9/9/9/9/9/9/9/4A4/3RK4 w - 0 1",
    "3ak4/4a4/9/9/9/9/9/9/9/3RK4 w - 0 1",
};

struct Engine {
    Position pos;
    Searcher searcher{1, 64};
    std::thread thread;
    std::string evalFile;

    Engine() { pos.set_fen(START_FEN); }
    ~Engine() { wait(); }
    void wait() {
        if (thread.joinable()) {
            searcher.stop();
            thread.join();
        }
    }

    void cmd_uci() {
        out("id name jqe 0.1");
        out("id author jqe authors");
        out("option name Hash type spin default 64 min 1 max 16384");
        out("option name Threads type spin default 1 min 1 max 256");
        out("option name EvalFile type string default <empty>");
        out("option name Clear Hash type button");
        out("option name NNUEQuant type check default true");
        for (const Param& p : params())
            out("option name " + std::string(p.name) + " type spin default " + std::to_string(*p.value) +
                " min " + std::to_string(p.lo) + " max " + std::to_string(p.hi));
        out("uciok");
    }

    void cmd_setoption(std::istringstream& is) {
        std::string tok, name, value;
        is >> tok;  // "name"
        while (is >> tok && tok != "value") name += (name.empty() ? "" : " ") + tok;
        while (is >> tok) value += (value.empty() ? "" : " ") + tok;
        wait();
        if (name == "Hash") searcher.resize_hash(std::size_t(std::max(1, std::stoi(value))));
        else if (name == "Threads") searcher.set_threads(std::stoi(value));
        else if (name == "Clear Hash") searcher.clear();
        else if (name == "NNUEQuant") { nnue::set_quantized(value == "true"); searcher.clear(); }
        else if (name == "EvalFile") {
            evalFile = value;
            std::string err;
            if (value.empty() || value == "<empty>") nnue::unload();
            else if (!nnue::load(value, &err)) out("info string EvalFile load failed: " + err);
            else out("info string EvalFile loaded " + value);
            searcher.clear();
        } else {
            for (Param& p : params())
                if (name == p.name) {
                    *p.value = std::clamp(std::stoi(value), p.lo, p.hi);
                    search::init();
                    return;
                }
            out("info string unknown option " + name);
        }
    }

    void cmd_position(std::istringstream& is) {
        std::string tok, fen;
        is >> tok;
        if (tok == "startpos") {
            fen = START_FEN;
            is >> tok;
        } else if (tok == "fen") {
            while (is >> tok && tok != "moves") fen += (fen.empty() ? "" : " ") + tok;
        } else
            return;
        std::string err;
        Position p;
        if (!p.set_fen(fen, &err)) {
            out("info string bad fen: " + err);
            return;
        }
        if (tok == "moves")
            while (is >> tok)
                if (!p.apply_token(tok, &err)) {
                    out("info string bad move " + tok + ": " + err);
                    break;
                }
        pos = p;
    }

    void cmd_go(std::istringstream& is) {
        Limits lim;
        std::string tok;
        while (is >> tok) {
            if (tok == "depth") is >> lim.depth;
            else if (tok == "nodes") is >> lim.nodes;
            else if (tok == "movetime") is >> lim.movetime;
            else if (tok == "wtime") is >> lim.time[RED];
            else if (tok == "btime") is >> lim.time[BLACK];
            else if (tok == "winc") is >> lim.inc[RED];
            else if (tok == "binc") is >> lim.inc[BLACK];
            else if (tok == "movestogo") is >> lim.movestogo;
            else if (tok == "infinite") lim.infinite = true;
            else if (tok == "searchmoves")
                while (is >> tok) lim.searchMoves.push_back(parse_move_coords(tok));
        }
        wait();
        Position root = pos;
        searcher.prepare();  // a stop that arrives before the search thread runs must not be lost
        thread = std::thread([this, root, lim] {
            static const std::function<void(const std::string&)> info = [](const std::string& s) { out(s); };
            const SearchResult r = searcher.go(root, lim, info, false);
            out(r.best == MOVE_NONE ? "bestmove (none)" : "bestmove " + move_str(r.best));
        });
    }

    void cmd_bench(std::istringstream& is) {
        int depth = 7;
        is >> depth;
        wait();
        uint64_t nodes = 0;
        const auto t0 = std::chrono::steady_clock::now();
        searcher.clear();
        for (const char* f : BENCH_FENS) {
            Position p;
            p.set_fen(f);
            Limits lim;
            lim.depth = depth;
            const SearchResult r = searcher.go(p, lim, [](const std::string&) {});
            nodes += r.nodes;
            out("bench " + std::string(f) + " -> " + move_str(r.best) + " score " + std::to_string(r.score) +
                " nodes " + std::to_string(r.nodes));
        }
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
        out("Nodes searched: " + std::to_string(nodes));
        out("Nodes/second  : " + std::to_string(nodes * 1000 / uint64_t(std::max<int64_t>(1, ms))));
        out("Time (ms)     : " + std::to_string(ms));
    }
};

}  // namespace

int uci_loop(int argc, char** argv) {
    Engine engine;
    std::string line;
    // Command-line arguments are executed as one command (e.g. `jqe bench 8`), then exit.
    const bool once = argc > 1;
    if (once) {
        for (int i = 1; i < argc; ++i) line += (i > 1 ? " " : "") + std::string(argv[i]);
    }
    while (once || std::getline(std::cin, line)) {
        std::istringstream is(line);
        std::string cmd;
        is >> cmd;
        if (cmd == "uci") engine.cmd_uci();
        else if (cmd == "isready") { out("readyok"); }
        else if (cmd == "ucinewgame") { engine.wait(); engine.searcher.clear(); }
        else if (cmd == "setoption") engine.cmd_setoption(is);
        else if (cmd == "position") { engine.wait(); engine.cmd_position(is); }
        else if (cmd == "go") engine.cmd_go(is);
        else if (cmd == "stop") engine.wait();
        else if (cmd == "quit") break;
        else if (cmd == "d") out(engine.pos.pretty());
        else if (cmd == "moves") {  // legal moves of the current position (diagnostics)
            Move ms[MAX_MOVES];
            const int n = engine.pos.gen_legal(ms);
            std::string line2 = "moves";
            for (int i = 0; i < n; ++i) line2 += " " + move_str(ms[i]);
            out(line2);
        }
        else if (cmd == "eval") out("classical " + std::to_string(classical_eval(engine.pos)) + " eval " + std::to_string(evaluate(engine.pos)));
        else if (cmd == "perft") {
            int d = 1;
            is >> d;
            Position p = engine.pos;
            const auto t0 = std::chrono::steady_clock::now();
            const uint64_t n = search::perft(p, d);
            const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - t0).count();
            out("perft " + std::to_string(d) + " " + std::to_string(n) + " (" + std::to_string(ms) + " ms)");
        } else if (cmd == "see") {
            std::string mv;
            is >> mv;
            const Move m = parse_move_coords(mv);
            out("see " + mv + " " + std::to_string(search::see_value(engine.pos, m)));
        } else if (cmd == "perftc") {
            int d = 1;
            is >> d;
            Position p = engine.pos;
            uint64_t leaves = 0;
            const double mass = search::perft_chance(p, d, leaves);
            char buf[128];
            std::snprintf(buf, sizeof buf, "perftc %d leaves %llu expected %.6f", d, (unsigned long long)leaves, mass);
            out(buf);
        } else if (cmd == "nnbench") {
            if (!nnue::loaded()) { out("info string no net"); continue; }
            Position p = engine.pos;
            Move ml[MAX_MOVES];
            const int n = p.gen_legal(ml);
            static nnue::Accumulator a0, a1;
            if (is.str().find("ftz") != std::string::npos) nnue::set_flush_denormals();
            nnue::Dirty d;
            nnue::refresh(p, a0);
            const int iters = 1000000;
            auto t0 = std::chrono::steady_clock::now();
            int64_t sink = 0;
            for (int i = 0; i < iters; ++i) sink += nnue::evaluate(a0, p.stm);
            auto t1 = std::chrono::steady_clock::now();
            for (int i = 0; i < iters; ++i) {
                Move m = ml[i % n];
                if (p.is_dark_move(m)) m = make_move(from_sq(m), to_sq(m), SOLDIER);
                nnue::make_dirty(p, m, d);
                nnue::update(a0, a1, d);
                sink += int64_t(a1.v[0][0]);
            }
            auto t2 = std::chrono::steady_clock::now();
            for (int i = 0; i < iters / 10; ++i) { nnue::refresh(p, a1); sink += int64_t(a1.v[1][1]); }
            auto t3 = std::chrono::steady_clock::now();
            auto ns = [&](auto x, auto y, int k) { return std::chrono::duration<double, std::nano>(y - x).count() / k; };
            out("nnbench evaluate " + std::to_string(ns(t0, t1, iters)) + " ns, update " + std::to_string(ns(t1, t2, iters)) +
                " ns, refresh " + std::to_string(ns(t2, t3, iters / 10)) + " ns (sink " + std::to_string(sink & 1) + ")");
        } else if (cmd == "bench") engine.cmd_bench(is);
        else if (cmd == "selfplay") { engine.wait(); selfplay(is); }
        else if (!cmd.empty()) out("info string unknown command " + cmd);
        if (once) {
            engine.wait();
            break;
        }
    }
    engine.wait();
    return 0;
}

}  // namespace jq
