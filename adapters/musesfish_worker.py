"""Original diagnostic JSON bridge; external GPL code runs only in this child.

Not admitted for matches. It returns pseudo moves / a fixed-depth search probe,
not oracle-approved moves. No source implementation is copied from the opponent.
"""
import argparse
from collections import Counter
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jieqi.observation_wire import decode_observation, exact_fields, public_history, strict_json_loads
from jieqi.setup import Color, POOL_KINDS, dark_role

PIN = '3de6c17ae6dafa035b5eea5ec7d6b7f39118aab6'
ENTRY = 'musesfish_pvs_20210528_fixed.py'
MAX_REQUEST_BYTES = 1024 * 1024  # Resource rejection, never a game result.
ROLE_CODE = {'R': 'D', 'N': 'E', 'B': 'F', 'A': 'G', 'C': 'H', 'P': 'I'}


def mailbox(public_board):
    # The public protocol has 9x10 points; this external API uses a 16x16 mailbox.
    chars = [' '] * 256
    for row in range(15):
        chars[row * 16 + 15] = '\n'
    for index, char in enumerate(public_board):
        rank, file = divmod(index, 9)
        if char in 'Xx':
            color = Color.RED if char == 'X' else Color.BLACK
            code = ROLE_CODE[dark_role(color, index).value]
            char = code if color is Color.RED else code.lower()
        chars[(12 - rank) * 16 + 3 + file] = char
    return ''.join(chars)


class TruthAccessForbidden(RuntimeError):
    pass


class TruthGuard:
    def __init__(self):
        self.attempts = 0

    def fail(self, *args, **kwargs):
        self.attempts += 1
        raise TruthAccessForbidden('external UI/referee truth API is disabled')

    __getitem__ = __getattr__ = __iter__ = __len__ = fail


def load_external(path, seed, *, source_files=None):
    def git(*args):
        result = subprocess.run(['git', '-C', str(path), *args], text=True, capture_output=True)
        if result.returncode:
            raise ValueError('opponent Git validation failed: ' + result.stderr.strip())
        return result.stdout.strip()
    if source_files is None:
        if git('rev-parse', 'HEAD') != PIN or git('status', '--porcelain', '--untracked-files=all'):
            raise ValueError('opponent pin/clean-tree gate failed')
    else:
        for name, expected in source_files.items():
            if name not in (ENTRY, 'board/__init__.py', 'board/board.py', 'board/common.py',
                            'board/common_20210528_fixed.py', 'board/library.py'):
                raise ValueError('unexpected external source file')
            if hashlib.sha256((path/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('external source pin mismatch')
        # Explicitly load this source-only package without allowing the repository
        # directory, Git metadata, logs, records or unrelated data to be read.
        package_spec=importlib.util.spec_from_file_location('board',path/'board/__init__.py')
        package=importlib.util.module_from_spec(package_spec)
        sys.modules['board']=package;package_spec.loader.exec_module(package)
        for name in ('common','board','common_20210528_fixed','library'):
            spec=importlib.util.spec_from_file_location('board.'+name,path/('board/'+name+'.py'))
            part=importlib.util.module_from_spec(spec);sys.modules[spec.name]=part
            spec.loader.exec_module(part);setattr(package,name,part)
    random.seed(seed)  # Only unrelated module initialization, never the referee deal.
    sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location('_external_musesfish', path / ENTRY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    guard = TruthGuard()
    module.B = module.mapping = guard
    module.Position.mymove_check = guard.fail
    module.board.Board = guard.fail
    for name in ('main', 'printmapping', 'print_pos', 'translate_eat'):
        setattr(module, name, guard.fail)
    return module, guard


def position(module, board, turn):
    result = module.Position(mailbox(board), 0, True).set()
    return result if turn is Color.RED else result.rotate()


def canonical_move(module, move, turn):
    if turn is Color.BLACK:
        move = tuple(254 - point for point in move)
    return module.render(move[0]) + module.render(move[1])


def prepare(request, opponent, initialization_seed, *, loaded=None):
    exact_fields(request, {'schema', 'operation', 'observation', 'depth'}, 'request')
    if request['schema'] != 'jieqi-musesfish-diagnostic-v0':
        raise ValueError('unsupported request schema')
    operation, depth = request['operation'], request['depth']
    if type(depth) is not int or not (
        (operation == 'inspect' and depth == 0) or (operation in ('depth_probe','legal_depth_probe') and 1 <= depth <= 3)
    ):
        raise ValueError('unsupported operation/depth')
    obs = decode_observation(request['observation'])
    if obs.viewer is not obs.turn:
        raise ValueError('worker only accepts the acting player observation')
    engine, guard = load_external(opponent, initialization_seed) if loaded is None else loaded
    # Replace every search pool from the actor's candidates, including its own
    # unknown captured pieces. Never estimate using the referee's true live pool.
    engine.r = {k.value: n for k, n in zip(POOL_KINDS, obs.pool(Color.RED).candidates)}
    engine.b = {k.lower(): n for k, n in obs.pool(Color.BLACK).to_dict()['candidates'].items()}
    engine.di = {True: dict(engine.r), False: dict(engine.b)}
    engine.sumall = {side: sum(pool.values()) for side, pool in engine.di.items()}
    history = public_history(obs)
    # Retain the source CLI's red-oriented public cache convention. Its search
    # repetition heuristic is NOT the selected referee's adjudication rule.
    engine.cache = dict(Counter(mailbox(board) for board, _ in history))
    engine.forbidden_moves = set()
    pos = position(engine, obs.board, obs.turn)
    moves = sorted(canonical_move(engine, move, obs.turn) for move in pos.gen_moves())
    pos.set()  # gen_moves mutates evaluator counters in this pinned source.
    searcher = engine.Searcher()
    searcher.calc_average()
    searcher.history = {position(engine, board, turn) for board, turn in history}
    digest_state = {'mailbox': pos.board, 'turn': pos.turn, 'r': engine.r, 'b': engine.b,
                    'di': engine.di, 'sumall': engine.sumall, 'history_cache': engine.cache}
    result = {
        'schema': 'jieqi-musesfish-diagnostic-result-v0', 'status': 'ok', 'operation': operation,
        'opponent_commit': PIN, 'observation_sha256': obs.cache_key(),
        'engine_input_sha256': hashlib.sha256(json.dumps(digest_state, sort_keys=True).encode()).hexdigest(),
        'engine_pool_candidates': {'red': engine.r, 'black': engine.b},
        'pseudo_moves': moves, 'pseudo_move_count': len(moves), 'requested_depth': depth,
        'candidate_move': None, 'relative_search_score': None, 'search_nodes': 0,
        'fair_match_admission': False, 'native_legality_checked': False,
        'hidden_truth_read_attempts': 0,
    }
    return obs,engine,guard,pos,searcher,result


def apply_legal_root_mask(obs,engine,pos,result,native):
    if native is None:raise ValueError('pinned native rules required for legal-root profile')
    legal=set(native.legal_moves(obs.board,obs.turn))
    root_moves=list(pos.gen_moves());pos.set()
    rejected={move for move in root_moves if canonical_move(engine,move,obs.turn) not in legal}
    engine.forbidden_moves.update(rejected)
    result.update(root_filter_profile='native-public-root-v1',legal_root_moves=sorted(legal),
        root_mask_rejections=len(rejected),native_legality_checked=True)
    return root_moves,legal


def evaluate(request, opponent, initialization_seed, *, loaded=None, native=None):
    obs,engine,guard,pos,searcher,result=prepare(request,opponent,initialization_seed,loaded=loaded)
    operation,depth=request['operation'],request['depth']
    if operation in ('depth_probe','legal_depth_probe'):
        engine.generate_forbiddenmoves(pos)
        if operation == 'legal_depth_probe':
            apply_legal_root_mask(obs,engine,pos,result,native)
        score = searcher.alphabeta(pos, -engine.MATE_UPPER, engine.MATE_UPPER, depth)
        move = searcher.tp_move.get(pos)
        result.update(candidate_move=canonical_move(engine, move, obs.turn) if move else None,
                      relative_search_score=score, search_nodes=searcher.nodes)
    result['hidden_truth_read_attempts'] = guard.attempts
    if guard.attempts:
        raise TruthAccessForbidden('search attempted an external UI/referee truth read')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opponent', type=Path,
                        default=Path(os.environ.get('JIEQI_OPPONENTS') or Path.home() / 'jieqi-opponents') / 'musesfish')
    parser.add_argument('--initialization-seed', type=int, default=0)
    args = parser.parse_args()
    start = time.perf_counter()
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError('request byte limit exceeded')
        request = strict_json_loads(raw)
        with contextlib.redirect_stdout(sys.stderr):
            result = evaluate(request, args.opponent.resolve(strict=True), args.initialization_seed)
        code = 0
    except Exception as error:
        result = {'schema': 'jieqi-musesfish-diagnostic-result-v0', 'status': 'error',
                  'error_type': type(error).__name__, 'error': str(error), 'fair_match_admission': False}
        code = 2
    result['worker_elapsed_seconds'] = time.perf_counter() - start
    print(json.dumps(result, sort_keys=True), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
