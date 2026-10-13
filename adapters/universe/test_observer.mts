// Unit checks for observer.mts (original code, jieqi project). Run: ./run_tests.sh
import { pathToFileURL } from 'node:url';
import {
  START_FEN,
  buildState,
  debugSummary,
  flip,
  loadUniverse,
  parseSquare,
  publicBoard,
  toGame,
  moveText,
} from './observer.mts';

const dir = process.argv[process.argv.indexOf('--universe') + 1] as string;
const U = await loadUniverse(/^[a-z]+:\/\//i.test(dir) ? dir : pathToFileURL(dir).href);

let failures = 0;
let checks = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  checks += 1;
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    failures += 1;
    console.log(`FAIL ${label}\n  expected ${e}\n  actual   ${a}`);
  }
}
function throws(label: string, fn: () => unknown, pattern: RegExp): void {
  checks += 1;
  try {
    fn();
    failures += 1;
    console.log(`FAIL ${label}: did not throw`);
  } catch (error: any) {
    if (!pattern.test(String(error?.message))) {
      failures += 1;
      console.log(`FAIL ${label}: wrong error ${error?.message}`);
    }
  }
}
const at = (board: string, name: string): string => board[parseSquare(name)] as string;
const state = (tokens: string[]) => buildState(U, START_FEN, tokens);

// --- Coordinates -----------------------------------------------------------------------------------
check('flip e0 = universe red king square (x4,y9)', flip(parseSquare('e0')), 4 + 9 * 9);
check('flip e9 = universe black king square (x4,y0)', flip(parseSquare('e9')), 4);
check('flip b2 = universe red cannon square (x1,y7)', flip(parseSquare('b2')), 1 + 7 * 9);
check('flip is an involution', [...Array(90).keys()].every((s) => flip(flip(s)) === s), true);
{
  const s = state([]);
  check('start: public board', publicBoard(s),
    'XXXXKXXXX' + '.........' + '.X.....X.' + 'X.X.X.X.X' + '.........' +
    '.........' + 'x.x.x.x.x' + '.x.....x.' + '.........' + 'xxxxkxxxx');
  check('start: red king and its homeKind', [s.board.at(flip(parseSquare('e0'))).kind, s.board.at(flip(parseSquare('e0'))).color], ['K', 'red']);
  check('start: red b0 is a face-down horse-square piece', [s.board.at(flip(parseSquare('b0'))).hidden, s.board.at(flip(parseSquare('b0'))).homeKind], [true, 'H']);
  check('start: black h7 is a face-down cannon-square piece', [s.board.at(flip(parseSquare('h7'))).color, s.board.at(flip(parseSquare('h7'))).homeKind], ['black', 'C']);
  const d = debugSummary(U, s) as any;
  check('start: 44 legal moves for red', d.legal.length, 44);
  check('start: hidden horse b0 -> a2/c2 legal, rook a0 -> a1/a2 legal', ['b0a2', 'b0c2', 'a0a1', 'a0a2'].every((m) => d.legal.includes(m)), true);
  check('start: hidden advisor d0 may only go to e1', d.legal.filter((m: string) => m.startsWith('d0')), ['d0e1']);
  check('start: pools', d.pools, { red: 'AABBCCNNPPPPPRR', black: 'aabbccnnppppprr' });
}

// --- A reveal --------------------------------------------------------------------------------------
{
  const s = state(['h2e2C']);
  const b = publicBoard(s);
  const d = debugSummary(U, s) as any;
  check('reveal: side to move', s.side, 'black');
  check('reveal: h2 empty, e2 red cannon', [at(b, 'h2'), at(b, 'e2')], ['.', 'C']);
  check('reveal: revealed piece is face up with kind C', [s.board.at(flip(parseSquare('e2'))).hidden, s.board.at(flip(parseSquare('e2'))).kind], [false, 'C']);
  check('reveal: pools (black view)', d.pools, { red: 'AABBCNNPPPPPRR', black: 'aabbccnnppppprr' });
  check('reveal: half-move clock', s.halfMove, 1);
  check('reveal: padded token is equivalent', publicBoard(state(['h2e2Cx'])), b);
}

// --- Capture of a face-down piece, seen from both sides ---------------------------------------------
// Ply 1: red's hidden cannon-square piece b2 jumps the screen b7 and takes black's face-down b9,
//        turning out to be a rook; red (the capturer) learns the victim was a horse.
// Ply 2: black's hidden cannon-square piece h7 takes red's face-down h0 and is revealed as a cannon;
//        black learns its victim was a horse.
// Ply 3: red's face-down a0 steps to a1 and is revealed as a soldier.
{
  const red = state(['b2b9Rn', 'h7h0c']);
  const b = publicBoard(red);
  const d = debugSummary(U, red) as any;
  check('red view: side to move', red.side, 'red');
  check('red view: squares', [at(b, 'b2'), at(b, 'b9'), at(b, 'h7'), at(b, 'h0')], ['.', 'R', '.', 'c']);
  // Red's own pool keeps the horse lost face down on h0 (red never sees it); black's pool loses the
  // revealed cannon and the horse red learned by capturing b9.
  check('red view: pools', d.pools, { red: 'AABBCCNNPPPPPR', black: 'aabbcnppppprr' });
  check('red view: hidden counts', [red.board.hiddenSquares('red').length, red.board.hiddenSquares('black').length], [13, 13]);
  check('red view: learned', d.learned, { red: 1, black: 0 });
  check('red view: capture resets the clock', red.halfMove, 0);
  check('red view: no rule differences', red.ruleNotes, []);

  const black = state(['b2b9R', 'h7h0cN', 'a0a1P']);
  const bb = publicBoard(black);
  const db = debugSummary(U, black) as any;
  check('black view: side to move', black.side, 'black');
  check('black view: squares', [at(bb, 'b9'), at(bb, 'h0'), at(bb, 'a0'), at(bb, 'a1')], ['R', 'c', '.', 'P']);
  // Black does not learn what it lost on b9; it does know red lost a horse on h0.
  check('black view: pools', db.pools, { red: 'AABBCCNPPPPR', black: 'aabbcnnppppprr' });
  check('black view: hidden counts', [black.board.hiddenSquares('red').length, black.board.hiddenSquares('black').length], [12, 13]);
  check('black view: learned', db.learned, { red: 0, black: 1 });
  check('black view: clock after a non-capture', black.halfMove, 1);
  check('same public board from both views at ply 2', publicBoard(state(['b2b9R', 'h7h0cN'])), b);
}

// --- Repetition bookkeeping ------------------------------------------------------------------------
{
  const shuffle = ['e0e1', 'e9e8', 'e1e0', 'e8e9'];
  const twice = state([...shuffle, ...shuffle]);
  const d = debugSummary(U, twice) as any;
  check('repetition: start position seen three times', d.repetition, 3);
  check('repetition: e0e1 legal but forbidden (third occurrence)', [d.legal.includes('e0e1'), d.selectable.includes('e0e1')], [true, false]);
  const once = debugSummary(U, state(shuffle)) as any;
  check('repetition: after one cycle e0e1 still selectable', [once.repetition, once.selectable.includes('e0e1')], [2, true]);
}

// --- Malformed or inconsistent tokens --------------------------------------------------------------
throws('face-down mover without reveal letter', () => state(['h2e2']), /without reveal/);
throws('victim letter on a face-up target', () => state(['b2b9Rn', 'a9b9rR']), /unexpected victim letter/);
throws('moving the opponent piece', () => state(['a6a5p']), /no red piece/);
throws('reveal letter on a face-up mover', () => state(['e0e1R']), /unexpected reveal letter/);
throws('king letter is never an identity', () => state(['h2e2K']), /bad identity letter/);

// --- Placeholders do not influence the decision ----------------------------------------------------
// Same observer state, two different fillings of the face-down kinds (the default homeKind and an
// arbitrary "every hidden piece is a rook"), same seed: the universe engine must decide identically,
// because it resamples every face-down identity from the observer's pools before each world.
{
  const tokens = ['h2e2C', 'h7e7c', 'b0c2N', 'b9c7n', 'e2e6', 'c7e6'];
  const a = buildState(U, START_FEN, tokens);
  const b = buildState(U, START_FEN, tokens, { placeholder: () => 'R' });
  check('placeholder test: states differ only in hidden kinds', publicBoard(a), publicBoard(b));
  const opts = { difficulty: 'hard', depth: 3, worlds: 8, nodeBudget: Number.MAX_SAFE_INTEGER, timeLimitMs: 1e9, seed: 12345 };
  const da = U.chooseMove(toGame(U, a), opts);
  const db = U.chooseMove(toGame(U, b), opts);
  const view = (d: any) => ({ move: moveText(d.move), score: d.score, nodes: d.nodes, cands: d.candidates.map((c: any) => [moveText(c.move), c.score]) });
  check('placeholder test: identical decision', view(db), view(da));
  check('placeholder test: decision is a legal move', toGame(U, a).legalMoves().some((m: any) => m.from === da.move.from && m.to === da.move.to), true);
}

console.log(`${checks - failures}/${checks} checks passed`);
process.exit(failures ? 1 : 0);
