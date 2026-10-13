// UCI-style front end that lets the jieqi match harness play the universe-st/Jieqi AI (MIT, imported
// read-only from its checkout at runtime). Original code, jieqi project. Run through ./run.sh.
//
// One process per game, as engine/tools/match.py expects. Every `position` is rebuilt from the start
// FEN and this side's own move tokens only (observer.mts), so the AI never sees a hidden identity the
// player could not know. `go movetime N` runs the universe PIMC decision at increasing fixed depths
// (1, 2, ... up to the preset depth) inside a shared wall-clock budget; see README.md.

import { createInterface } from 'node:readline';
import { appendFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import {
  START_FEN,
  buildState,
  debugSummary,
  loadUniverse,
  moveText,
  toGame,
  type ObserverState,
} from './observer.mts';

const NAME = 'universe-jieqi 1.7.1 (3579f28) offline adapter';

function argValue(flag: string): string | undefined {
  const i = process.argv.indexOf(flag);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const universeDir = argValue('--universe');
const wslRoot = argValue('--wsl-root') ?? ''; // e.g. \\wsl.localhost\Ubuntu\ for Linux log paths
if (!universeDir) {
  process.stdout.write('info string error: --universe <dir> is required\n');
  process.exit(2);
}
const rootUrl = /^[a-z]+:\/\//i.test(universeDir) ? universeDir : pathToFileURL(universeDir).href;

let U: any = null;
let loadError: unknown = null;
const loading: Promise<void> = loadUniverse(rootUrl).then(
  (mod) => {
    U = mod;
  },
  (error) => {
    loadError = error;
  },
);

const options = {
  Difficulty: 'hard',
  Deepening: true, // false = one decision at the preset depth (the app's behaviour), time-capped
  MaxDepth: 0, // 0 = no cap with Deepening (time-bound), preset depth without
  Worlds: 0, // 0 = preset worlds
  MinWorlds: 0, // 0 = ceil(worlds / 3)
  Noise: -1, // centipawns, -1 = preset
  EpsilonPermille: -1, // -1 = preset
  Seed: 0, // 0 = fresh random seed per move
  MoveOverhead: 15, // ms kept back from movetime
  LogFile: '',
};

function setOption(name: string, value: string): void {
  const key = Object.keys(options).find((k) => k.toLowerCase() === name.toLowerCase()) as keyof typeof options | undefined;
  if (!key) return; // Hash, Threads and anything else: accepted and ignored
  if (typeof options[key] === 'boolean') {
    (options as any)[key] = value.toLowerCase() === 'true';
  } else if (typeof options[key] === 'number') {
    const n = Number(value);
    if (Number.isFinite(n)) (options as any)[key] = n;
  } else if (key === 'Difficulty') {
    if (value === 'easy' || value === 'normal' || value === 'hard') options.Difficulty = value;
  } else {
    (options as any)[key] = value === '<empty>' ? '' : value;
  }
}

function send(line: string): void {
  process.stdout.write(line + '\n');
}

function log(record: Record<string, unknown>): void {
  if (!options.LogFile) return;
  let path = options.LogFile;
  if (path.startsWith('/') && wslRoot) path = wslRoot.replace(/[\\/]+$/, '') + path.replace(/\//g, '\\');
  try {
    appendFileSync(path, JSON.stringify(record) + '\n');
  } catch {
    // logging is best effort
  }
}

// --------------------------------------------------------------------------------------------------
// Position cache: the harness resends the whole game every move; only new tokens are re-validated.

let positionFen = START_FEN;
let positionTokens: string[] = [];
let validatedFen = '';
let validatedTokens: string[] = [];
let ruleNotesSeen = new Set<string>();

function parsePosition(args: string[]): void {
  let i = 0;
  let fen = START_FEN;
  if (args[0] === 'startpos') i = 1;
  else if (args[0] === 'fen') {
    const parts: string[] = [];
    i = 1;
    while (i < args.length && args[i] !== 'moves') parts.push(args[i++] as string);
    fen = parts.join(' ');
  }
  const tokens: string[] = [];
  if (args[i] === 'moves') for (i += 1; i < args.length; i++) tokens.push(args[i] as string);
  positionFen = fen;
  positionTokens = tokens;
}

function currentState(): ObserverState {
  let validateFrom = 0;
  if (positionFen === validatedFen && validatedTokens.every((t, k) => positionTokens[k] === t)) {
    validateFrom = validatedTokens.length;
  } else {
    ruleNotesSeen = new Set();
  }
  const state = buildState(U, positionFen, positionTokens, { validateFrom });
  validatedFen = positionFen;
  validatedTokens = positionTokens.slice();
  return state;
}

// --------------------------------------------------------------------------------------------------
// Thinking.

interface GoLimits {
  budgetMs: number; // wall-clock budget for the whole decision (Infinity for go depth)
  fixedDepth: number; // > 0: search only this depth
  nodes: number; // node budget per decision (Infinity = none)
}

function parseGo(args: string[], side: 'red' | 'black'): GoLimits {
  const num = (key: string): number | undefined => {
    const i = args.indexOf(key);
    if (i < 0 || i + 1 >= args.length) return undefined;
    const n = Number(args[i + 1]);
    return Number.isFinite(n) ? n : undefined;
  };
  const movetime = num('movetime');
  const depth = num('depth');
  const nodes = num('nodes');
  const time = num(side === 'red' ? 'wtime' : 'btime');
  const inc = num(side === 'red' ? 'winc' : 'binc') ?? 0;
  let budgetMs = Infinity;
  if (movetime !== undefined) budgetMs = movetime * 0.9 - options.MoveOverhead;
  else if (time !== undefined) budgetMs = Math.min(time / 25 + inc * 0.75, time / 4) - options.MoveOverhead;
  else if (depth === undefined && nodes === undefined) budgetMs = 1000;
  return {
    budgetMs: Math.max(5, budgetMs),
    fixedDepth: depth !== undefined ? Math.max(1, Math.floor(depth)) : 0,
    nodes: nodes !== undefined ? Math.max(1, nodes) : Infinity,
  };
}

let seedCounter = 0;
function seedFor(ply: number, depth: number): number {
  if (options.Seed) return (options.Seed * 1000003 + ply * 101 + depth) >>> 0;
  seedCounter += 1;
  return (Math.floor(Math.random() * 0xffffffff) ^ (Date.now() + seedCounter * 7919)) >>> 0;
}

function think(state: ObserverState, limits: GoLimits): Record<string, any> {
  const started = Date.now();
  const deadline = started + limits.budgetMs;
  const preset = U.DIFFICULTY[options.Difficulty];
  const worlds = options.Worlds > 0 ? options.Worlds : preset.worlds;
  // Deepening runs until the budget is spent (the search clamps depth at 46); MaxDepth > 0 caps it,
  // e.g. MaxDepth=4 for the app's hard depth. Without deepening: one decision at the preset depth.
  const maxDepth = limits.fixedDepth || (options.MaxDepth > 0 ? options.MaxDepth : options.Deepening ? 46 : preset.depth);
  const minWorlds = options.MinWorlds > 0 ? Math.min(options.MinWorlds, worlds) : Math.ceil(worlds / 3);
  const base = {
    difficulty: options.Difficulty,
    worlds,
    nodeBudget: Number.isFinite(limits.nodes) ? limits.nodes : Number.MAX_SAFE_INTEGER,
    ...(options.Noise >= 0 ? { noiseCp: options.Noise } : {}),
    ...(options.EpsilonPermille >= 0 ? { epsilon: options.EpsilonPermille / 1000 } : {}),
  };

  let game = toGame(U, state);
  let forcedRepeat = false;
  if (game.selectableMoves().length === 0) {
    if (game.legalMoves().length === 0) return { move: null, started };
    // Every legal move recreates a position for the third time (the universe rules forbid all of
    // them and would call this a loss). Our referee adjudicates repetition itself, so play on: forget
    // the repetition history and let the AI choose among the legal moves.
    game.repetitions = new Map();
    forcedRepeat = true;
  }

  // A single allowed move needs no thinking time: one shallow decision supplies the info line.
  const onlyMove = game.selectableMoves().length === 1;
  const lastDepth = onlyMove ? 1 : maxDepth;

  let best: any = null;
  let bestDepth = 0;
  let nodes = 0;
  const trace: string[] = [];
  const firstDepth = limits.fixedDepth || (options.Deepening ? 1 : maxDepth);
  for (let depth = firstDepth; depth <= Math.max(firstDepth, lastDepth); depth++) {
    const remaining = deadline - Date.now();
    if (best && remaining < 3) break;
    const timeLimitMs = Number.isFinite(remaining) ? Math.max(1, Math.floor(remaining)) : 2_000_000_000;
    const decision = U.chooseMove(game, { ...base, depth, timeLimitMs, seed: seedFor(state.plies, depth) });
    if (!decision) break;
    nodes += decision.nodes;
    trace.push(`${depth}:${decision.worlds}`);
    if (!best || decision.worlds >= minWorlds) {
      best = decision;
      bestDepth = depth;
    }
    if (decision.worlds < worlds) break; // ran out of time (or nodes) at this depth
  }
  return { move: best ? best.move : null, best, bestDepth, nodes, trace, forcedRepeat, started, worlds };
}

function scoreText(score: number): string {
  const MATE = 100000;
  if (Math.abs(score) >= MATE - 1000) {
    const plies = MATE - Math.abs(score);
    const moves = Math.max(1, Math.ceil(plies / 2));
    return `mate ${score > 0 ? moves : -moves}`;
  }
  return `cp ${Math.max(-20000, Math.min(20000, Math.round(score)))}`;
}

function go(args: string[]): void {
  let state: ObserverState;
  try {
    state = currentState();
  } catch (error: any) {
    send(`info string error: ${error?.message ?? error}`);
    log({ t: new Date().toISOString(), error: String(error?.message ?? error), tokens: positionTokens.length });
    send('bestmove (none)');
    return;
  }
  const limits = parseGo(args, state.side);
  let result: Record<string, any>;
  try {
    result = think(state, limits);
  } catch (error: any) {
    // Never leave the harness waiting: report the failure and fall back to a legal move.
    send(`info string error: search failed: ${error?.message ?? error}`);
    log({ t: new Date().toISOString(), ply: state.plies, error: String(error?.stack ?? error) });
    const legal = toGame(U, state).legalMoves();
    send(`bestmove ${legal.length ? moveText(legal[0]) : '(none)'}`);
    return;
  }
  const elapsed = Date.now() - result.started;
  if (!result.move) {
    send('bestmove (none)');
    log({ t: new Date().toISOString(), ply: state.plies, side: state.side, move: null });
    return;
  }
  const text = moveText(result.move);
  const best = result.best;
  send(
    `info depth ${result.bestDepth} nodes ${result.nodes} time ${elapsed} ` +
      `nps ${elapsed > 0 ? Math.round((result.nodes * 1000) / elapsed) : 0} score ${scoreText(best.score)} pv ${text}`,
  );
  send(`info string worlds ${best.worlds}/${result.worlds} depths ${result.trace.join(',')} reason ${best.reason}` +
    (result.forcedRepeat ? ' forced-repeat' : ''));
  const newNotes = state.ruleNotes.filter((n) => !ruleNotesSeen.has(n));
  for (const note of newNotes) {
    ruleNotesSeen.add(note);
    send(`info string rule-difference ${note}`);
  }
  send(`bestmove ${text}`);
  log({
    t: new Date().toISOString(),
    ply: state.plies,
    side: state.side,
    budget: Number.isFinite(limits.budgetMs) ? Math.round(limits.budgetMs) : null,
    elapsed,
    depth: result.bestDepth,
    trace: result.trace.join(','),
    worlds: best.worlds,
    nodes: result.nodes,
    score: Math.round(best.score),
    move: text,
    reason: best.reason,
    forcedRepeat: result.forcedRepeat || undefined,
    ruleNotes: newNotes.length ? newNotes : undefined,
  });
}

// --------------------------------------------------------------------------------------------------
// Protocol loop. Commands are handled strictly in order; `go` blocks until its bestmove is written.

async function handle(line: string): Promise<void> {
  const words = line.trim().split(/\s+/).filter(Boolean);
  const command = words[0];
  if (!command) return;
  switch (command) {
    case 'uci':
      send(`id name ${NAME}`);
      send('id author universe-st (AI, MIT); adapter by the jieqi project');
      send('option name Difficulty type combo default hard var easy var normal var hard');
      send('option name Deepening type check default true');
      send('option name MaxDepth type spin default 0 min 0 max 46');
      send('option name Worlds type spin default 0 min 0 max 10000');
      send('option name MinWorlds type spin default 0 min 0 max 10000');
      send('option name Noise type spin default -1 min -1 max 1000');
      send('option name EpsilonPermille type spin default -1 min -1 max 1000');
      send('option name Seed type spin default 0 min 0 max 2147483647');
      send('option name MoveOverhead type spin default 15 min 0 max 5000');
      send('option name LogFile type string default <empty>');
      send('uciok');
      return;
    case 'setoption': {
      const nameAt = words.indexOf('name');
      const valueAt = words.indexOf('value');
      if (nameAt < 0) return;
      const name = words.slice(nameAt + 1, valueAt < 0 ? undefined : valueAt).join(' ');
      const value = valueAt < 0 ? '' : words.slice(valueAt + 1).join(' ');
      setOption(name, value);
      return;
    }
    case 'isready':
      await loading;
      if (loadError) send(`info string error: cannot load universe modules: ${String(loadError)}`);
      send('readyok');
      return;
    case 'ucinewgame':
      validatedFen = '';
      validatedTokens = [];
      ruleNotesSeen = new Set();
      return;
    case 'position':
      parsePosition(words.slice(1));
      return;
    case 'go':
      await loading;
      if (!U) {
        send(`info string error: universe modules unavailable: ${String(loadError)}`);
        send('bestmove (none)');
        return;
      }
      go(words.slice(1));
      return;
    case 'd':
      await loading;
      try {
        send('debug ' + JSON.stringify(debugSummary(U, buildState(U, positionFen, positionTokens))));
      } catch (error: any) {
        send('debug ' + JSON.stringify({ error: String(error?.message ?? error) }));
      }
      return;
    case 'stop':
    case 'ponderhit':
      return; // searches are synchronous: bestmove has already been sent
    case 'quit':
      process.exit(0);
    default:
      return;
  }
}

let queue: Promise<void> = Promise.resolve();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity, terminal: false });
rl.on('line', (line) => {
  queue = queue.then(() => handle(line)).catch((error) => {
    send(`info string error: ${String(error?.message ?? error)}`);
  });
});
rl.on('close', () => {
  queue.then(() => process.exit(0));
});
