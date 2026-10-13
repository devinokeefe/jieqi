"""Observation-only timed bridge; external GPL code remains outside this package."""
import argparse,contextlib,hashlib,json,sys,time
from pathlib import Path
from adapters.musesfish_worker import PIN,load_external,prepare,apply_legal_root_mask,canonical_move
from jieqi.native import NativeRules
from jieqi.observation_wire import strict_json_loads
from jieqi.timed_iterations import completed_iterations
PROFILE='musesfish-native-public-root-timed-v1'

def evaluate_timed(payload,loaded,native,opponent,milliseconds):
    start=time.monotonic_ns()
    request=dict(schema='jieqi-musesfish-diagnostic-v0',operation='legal_depth_probe',depth=1,observation=payload)
    obs,engine,guard,pos,searcher,result=prepare(request,opponent,0,loaded=loaded)
    engine.generate_forbiddenmoves(pos)
    root_moves,legal=apply_legal_root_mask(obs,engine,pos,result,native)
    eligible=[m for m in root_moves if m not in engine.forbidden_moves]
    # Keep the external heuristic exclusions. Exhaustion is an explicit failure,
    # never an unlogged heuristic override or a truth-derived replacement.
    if legal and not eligible:raise ValueError('external root heuristics exclude all legal candidates')
    fallback=max(eligible,key=pos.value) if eligible else None
    pos.set()
    def search_one(depth):
        score=searcher.alphabeta(pos,-engine.MATE_UPPER,engine.MATE_UPPER,depth)
        move=searcher.tp_move.get(pos)
        if move is not None and canonical_move(engine,move,obs.turn) not in legal:
            raise ValueError('external completed iteration returned illegal root')
        return move,score
    timed=completed_iterations(search_one,fallback,deadline_ns=start+milliseconds*1000000)
    result.update(profile=PROFILE,operation='timed_search',requested_depth=None,
        candidate_move=canonical_move(engine,timed['move'],obs.turn) if timed['move'] else None,
        relative_search_score=timed['score'],search_nodes=searcher.nodes,
        completed_depth=timed['completed_depth'],selected_depth=timed['selected_depth'],selection=timed['selection'],
        interrupted=timed['interrupted'],requested_ms=milliseconds,worker_wall_ns=time.monotonic_ns()-start,
        hidden_truth_read_attempts=guard.attempts)
    if guard.attempts:raise ValueError('truth access attempted')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--opponent',type=Path,required=True)
    p.add_argument('--source-files',required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--library-sha256',required=True);args=p.parse_args()
    if hashlib.sha256(args.library.read_bytes()).hexdigest()!=args.library_sha256:raise ValueError('native pin mismatch')
    native=NativeRules(args.library)
    with contextlib.redirect_stdout(sys.stderr):loaded=load_external(args.opponent,0,source_files=json.loads(args.source_files))
    obs=None
    while True:
        line=sys.stdin.buffer.readline(1048577)
        if not line:return 0
        if len(line)>1048576 or not line.endswith(b'\n'):raise ValueError('input limit or incomplete frame')
        command=line.decode('ascii').rstrip('\n')
        if command=='uci':
            print('id name '+PROFILE)
            print('option name Threads type spin default 1 min 1 max 1')
            print('option name Hash type spin default 16 min 16 max 16');print('uciok',flush=True)
        elif command in ('setoption name Threads value 1','setoption name Hash value 16'):pass
        elif command=='ucinewgame':obs=None
        elif command=='isready':print('readyok',flush=True)
        elif command.startswith('observation '):
            if obs is not None:raise ValueError('unconsumed observation')
            obs=command[len('observation '):]
        elif command.startswith('go movetime '):
            requested=command[len('go movetime '):]
            if not requested.isdecimal() or not 1<=int(requested)<=60000 or obs is None:raise ValueError('invalid go')
            # JSON and observer replay both occur within the parent move clock.
            with contextlib.redirect_stdout(sys.stderr):
                result=evaluate_timed(strict_json_loads(obs),loaded,native,args.opponent,int(requested))
            obs=None
            print('info string jieqi-audit '+json.dumps(result,sort_keys=True,separators=(',',':')))
            print('bestmove '+(result['candidate_move'] or '0000'),flush=True)
        elif command=='quit':return 0
        else:raise ValueError('unsupported command')
if __name__=='__main__':raise SystemExit(main())
