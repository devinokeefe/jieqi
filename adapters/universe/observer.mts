// Observer-state reconstruction for the universe-st/Jieqi adapter (original code, jieqi project).
//
// The match harness tells each engine only what that player saw: the start FEN plus one token per
// ply, `from to [reveal] [victim]`, where the reveal letter (mover's case) is public and the victim
// letter (victim's case) is present only in the capturer's own view. This module rebuilds that
// player's information state from the tokens alone and expresses it in the objects the universe AI
// consumes (`Board`, `Knowledge`, `JieqiGame`). The universe modules are passed in at runtime (see
// `loadUniverse`); nothing from that MIT checkout is copied here.
//
// Coordinates. Ours: index = rank * 9 + file, file a..i = 0..8, rank 0 = red home rank.
// Universe: index = y * 9 + x, x = file, y = 0 the black home rank, y = 9 the red home rank.
// So x = file and y = 9 - rank, and the conversion is its own inverse (`flip`).
//
// Hidden identities. A face-down piece is stored with `kind = homeKind` (the kind of the start square
// it stands on). That is public information and is never claimed to be its identity: the universe
// engine overwrites the kind of every face-down piece of both colours with a fresh draw from the
// observer's pools before searching each sampled world (ai/engine.ts `searchWorlds` -> core/info.ts
// `sampleWorld`). Root move generation, check and repetition use only `homeKind`, occupancy and the
// position key, so the placeholder never reaches an evaluation. `test_observer.mts` checks that a
// different placeholder filling gives a bit-identical decision.

import { registerHooks } from 'node:module';

export const START_FEN =
  'xxxxkxxxx/9/1x5x1/x1x1x1x1x/9/9/X1X1X1X1X/1X5X1/9/XXXXKXXXX w R2A2C2P5N2B2r2a2c2p5n2b2 0 1';

type Color = 'red' | 'black';
type UKind = 'K' | 'A' | 'E' | 'H' | 'R' | 'C' | 'P';

/** Our identity letters (R N B A C P K) to universe kinds (R H E A C P K). H/E accepted as aliases. */
const TO_U: Record<string, UKind> = { R: 'R', N: 'H', H: 'H', B: 'E', E: 'E', A: 'A', C: 'C', P: 'P', K: 'K' };
const FROM_U: Record<UKind, string> = { R: 'R', H: 'N', E: 'B', A: 'A', C: 'C', P: 'P', K: 'K' };
const ARMY: Record<UKind, number> = { K: 0, A: 2, E: 2, H: 2, R: 2, C: 2, P: 5 };
const KIND_ORDER: UKind[] = ['R', 'H', 'E', 'A', 'C', 'P'];
const other = (c: Color): Color => (c === 'red' ? 'black' : 'red');

/** Our square index <-> universe square index (self-inverse). */
export const flip = (sq: number): number => (9 - Math.floor(sq / 9)) * 9 + (sq % 9);

export function parseSquare(text: string): number {
  const f = text.charCodeAt(0) - 97;
  const r = text.charCodeAt(1) - 48;
  if (text.length !== 2 || f < 0 || f > 8 || r < 0 || r > 9) throw new Error(`bad square '${text}'`);
  return r * 9 + f;
}

export const squareName = (sq: number): string => String.fromCharCode(97 + (sq % 9)) + String(Math.floor(sq / 9));

/** Universe move -> our 4-character move text. */
export const moveText = (m: { from: number; to: number }): string => squareName(flip(m.from)) + squareName(flip(m.to));

// ---------------------------------------------------------------------------------------------------
// Loading the universe modules (read-only checkout, imported in place).

let hookInstalled = false;

/**
 * The universe sources import siblings without a file extension (`from './board'`), which their
 * bundler resolves and Node's ESM resolver does not. This in-process resolve hook retries such a
 * relative specifier with `.ts` appended, only for importers inside the universe checkout.
 */
export function installResolveHook(rootUrl: string): void {
  if (hookInstalled) return;
  hookInstalled = true;
  const prefix = rootUrl.toLowerCase();
  registerHooks({
    resolve(specifier: string, context: any, nextResolve: any) {
      try {
        return nextResolve(specifier, context);
      } catch (error: any) {
        const parent = String(context?.parentURL ?? '').toLowerCase();
        if (
          error?.code === 'ERR_MODULE_NOT_FOUND' &&
          parent.startsWith(prefix) &&
          /^\.{1,2}\//.test(specifier) &&
          !/\.[a-z]+$/i.test(specifier)
        ) {
          return nextResolve(specifier + '.ts', context);
        }
        throw error;
      }
    },
  });
}

export async function loadUniverse(rootUrl: string): Promise<any> {
  const base = rootUrl.endsWith('/') ? rootUrl : rootUrl + '/';
  installResolveHook(base);
  const [board, info, moves, rules, engine, types] = await Promise.all([
    import(base + 'src/core/board.ts'),
    import(base + 'src/core/info.ts'),
    import(base + 'src/core/moves.ts'),
    import(base + 'src/core/rules.ts'),
    import(base + 'src/ai/engine.ts'),
    import(base + 'src/core/types.ts'),
  ]);
  return {
    Board: board.Board,
    HOME_KIND_BY_SQUARE: board.HOME_KIND_BY_SQUARE,
    createKnowledge: info.createKnowledge,
    poolsFor: info.poolsFor,
    generateMoves: moves.generateMoves,
    isKingSafeAfter: moves.isKingSafeAfter,
    JieqiGame: rules.JieqiGame,
    chooseMove: engine.chooseMove,
    DIFFICULTY: engine.DIFFICULTY,
    ARMY_LIST: types.ARMY_LIST,
  };
}

// ---------------------------------------------------------------------------------------------------
// Reconstruction.

export interface ObserverState {
  /** Universe board; face-down pieces carry `kind = homeKind` (placeholder, see header). */
  board: any;
  knowledge: any;
  side: Color;
  halfMove: number;
  /** Position key -> occurrences, including the current position (keys use the placeholders). */
  repetitions: Map<number, number>;
  lastMove: { from: number; to: number } | null;
  plies: number;
  /** Victim identities learned per capturing side (only the observer's own should ever be non-zero). */
  learnedCount: Record<Color, number>;
  /** Harness moves that the universe move generator does not list as legal (rule differences). */
  ruleNotes: string[];
}

export interface BuildOptions {
  /** Validate token moves with index >= this against the universe generator (default 0: all). */
  validateFrom?: number;
  /** Test hook: choose the placeholder kind of a face-down piece (default: its homeKind). */
  placeholder?: (uSquare: number, color: Color, homeKind: UKind) => UKind;
}

function parsePool(field: string | undefined): Record<Color, Record<UKind, number>> | null {
  if (!field || field === '-') return null;
  const out: Record<Color, Record<UKind, number>> = {
    red: { K: 0, A: 0, E: 0, H: 0, R: 0, C: 0, P: 0 },
    black: { K: 0, A: 0, E: 0, H: 0, R: 0, C: 0, P: 0 },
  };
  const re = /([A-Za-z])(\d*)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(field))) {
    const letter = m[1] as string;
    const kind = TO_U[letter.toUpperCase()];
    if (!kind || kind === 'K') throw new Error(`bad pool letter '${letter}'`);
    const color: Color = letter === letter.toUpperCase() ? 'red' : 'black';
    out[color][kind] += m[2] ? Number(m[2]) : 1;
  }
  return out;
}

export function buildState(U: any, fen: string, tokens: readonly string[], options: BuildOptions = {}): ObserverState {
  const fields = fen.trim().split(/\s+/);
  const rows = (fields[0] ?? '').split('/');
  if (rows.length !== 10) throw new Error('FEN must have 10 ranks');
  const board = new U.Board();
  let id = 1;
  const onBoardRevealed: Record<Color, Record<UKind, number>> = {
    red: { K: 0, A: 0, E: 0, H: 0, R: 0, C: 0, P: 0 },
    black: { K: 0, A: 0, E: 0, H: 0, R: 0, C: 0, P: 0 },
  };
  for (let row = 0; row < 10; row++) {
    const rank = 9 - row; // FEN lists rank 9 (black home) first
    let file = 0;
    for (const ch of rows[row] as string) {
      if (ch >= '1' && ch <= '9') {
        file += Number(ch);
        continue;
      }
      if (file > 8) throw new Error(`FEN rank ${rank} overflows`);
      const color: Color = ch === ch.toUpperCase() ? 'red' : 'black';
      const u = flip(rank * 9 + file);
      if (ch === 'X' || ch === 'x') {
        const homeKind = U.HOME_KIND_BY_SQUARE.get(u) as UKind | undefined;
        const homeSide: Color = Math.floor(u / 9) >= 5 ? 'red' : 'black';
        if (!homeKind || homeKind === 'K' || homeSide !== color) {
          throw new Error(`face-down piece on ${squareName(rank * 9 + file)} is not on its own start square`);
        }
        const kind = options.placeholder ? options.placeholder(u, color, homeKind) : homeKind;
        board.squares[u] = { id: id++, color, kind, homeKind, hidden: true };
      } else {
        const kind = TO_U[ch.toUpperCase()];
        if (!kind) throw new Error(`bad FEN piece '${ch}'`);
        board.squares[u] = { id: id++, color, kind, homeKind: kind, hidden: false };
        onBoardRevealed[color][kind] += 1;
      }
      file += 1;
    }
    if (file !== 9) throw new Error(`FEN rank ${rank} has ${file} files`);
  }
  const side: Color = fields[1] === 'b' ? 'black' : 'red';
  board.side = side;
  board.rehash();
  if (board.kingSq.red < 0 || board.kingSq.black < 0) throw new Error('FEN needs both kings');

  // Pool arithmetic: universe pools are `ARMY - revealed[c] - learned[observer]`. Whatever the FEN's
  // pool field says is already accounted for goes into `revealed` so the pools come out equal to it.
  const knowledge = U.createKnowledge();
  const pool = parsePool(fields[2]);
  for (const color of ['red', 'black'] as const) {
    for (const kind of KIND_ORDER) {
      const remaining = pool ? pool[color][kind] : ARMY[kind] - onBoardRevealed[color][kind];
      const accounted = ARMY[kind] - remaining;
      if (accounted < 0) throw new Error(`pool lists too many ${color} ${kind}`);
      for (let i = 0; i < accounted; i++) knowledge.revealed[color].push(kind);
    }
  }
  const halfMoveField = Number(fields[3]);
  let halfMove = Number.isFinite(halfMoveField) ? halfMoveField : 0;

  const repetitions = new Map<number, number>();
  const bump = (): void => {
    repetitions.set(board.key, (repetitions.get(board.key) ?? 0) + 1);
  };
  bump();

  const learnedCount: Record<Color, number> = { red: 0, black: 0 };
  const ruleNotes: string[] = [];
  const validateFrom = options.validateFrom ?? 0;
  let lastMove: { from: number; to: number } | null = null;
  let toMove: Color = side;

  tokens.forEach((token, ply) => {
    const m = /^([a-i][0-9])([a-i][0-9])([A-Za-z-]*)$/.exec(token);
    if (!m) throw new Error(`bad move token '${token}' at ply ${ply + 1}`);
    const from = flip(parseSquare(m[1] as string));
    const to = flip(parseSquare(m[2] as string));
    const mover = board.squares[from];
    if (!mover || mover.color !== toMove) throw new Error(`token '${token}' (ply ${ply + 1}): no ${toMove} piece on ${m[1]}`);
    const victim = board.squares[to];
    if (victim && victim.color === toMove) throw new Error(`token '${token}' (ply ${ply + 1}): captures own piece`);

    let reveal: UKind | null = null;
    let learned: UKind | null = null;
    for (const ch of m[3] as string) {
      if (ch === 'x' || ch === 'X' || ch === '-') continue; // classical padding
      const kind = TO_U[ch.toUpperCase()];
      if (!kind || kind === 'K') throw new Error(`token '${token}': bad identity letter '${ch}'`);
      const letterColor: Color = ch === ch.toUpperCase() ? 'red' : 'black';
      if (letterColor === toMove) {
        if (!mover.hidden || reveal) throw new Error(`token '${token}': unexpected reveal letter`);
        reveal = kind;
      } else {
        if (!victim || !victim.hidden || learned) throw new Error(`token '${token}': unexpected victim letter`);
        learned = kind;
      }
    }
    if (mover.hidden && !reveal) throw new Error(`token '${token}': face-down mover without reveal letter`);

    if (ply >= validateFrom) {
      const legal = U.generateMoves(board, toMove, []).filter((mv: any) => U.isKingSafeAfter(board, toMove, mv));
      if (!legal.some((mv: any) => mv.from === from && mv.to === to)) {
        ruleNotes.push(`ply ${ply + 1} ${token}: not legal for the universe move generator`);
      }
    }

    if (reveal) knowledge.revealed[toMove].push(reveal);
    if (learned) {
      knowledge.learned[toMove].push({ color: other(toMove), kind: learned });
      learnedCount[toMove] += 1;
    }
    board.squares[from] = null;
    board.squares[to] = mover.hidden ? { ...mover, kind: reveal, hidden: false } : mover;
    toMove = other(toMove);
    board.side = toMove;
    board.rehash();
    halfMove = victim ? 0 : halfMove + 1;
    lastMove = { from, to };
    bump();
  });

  // Every face-down piece must be fillable from the observer's pools, otherwise the engine's world
  // sampler would leave a placeholder in place.
  const pools = U.poolsFor(knowledge, toMove);
  for (const color of ['red', 'black'] as const) {
    const hidden = board.hiddenSquares(color).length;
    if (pools[color].length < hidden) {
      throw new Error(`inconsistent tokens: ${color} has ${hidden} face-down pieces but only ${pools[color].length} unknown identities`);
    }
  }

  return { board, knowledge, side: toMove, halfMove, repetitions, lastMove, plies: tokens.length, learnedCount, ruleNotes };
}

/** A `JieqiGame` (standard mode) carrying exactly the observer's state, for `chooseMove`. */
export function toGame(U: any, state: ObserverState): any {
  // Same pattern as the universe test suite (test/ai.test.ts `gameOn`): create, then swap state in.
  const game = U.JieqiGame.create({ seed: 1, mode: 'standard' });
  game.board = state.board.clone();
  game.knowledge = state.knowledge;
  game.history = [];
  game.result = null;
  game.halfMoveClock = state.halfMove;
  game.lastMove = state.lastMove;
  game.repetitions = new Map(state.repetitions);
  return game;
}

/** 90-character public board in our index order ('.', 'X'/'x' face down, letters face up). */
export function publicBoard(state: ObserverState): string {
  let out = '';
  for (let sq = 0; sq < 90; sq++) {
    const p = state.board.squares[flip(sq)];
    if (!p) out += '.';
    else {
      const letter = p.hidden ? 'X' : FROM_U[p.kind as UKind];
      out += p.color === 'red' ? letter : letter.toLowerCase();
    }
  }
  return out;
}

/** Observer pools as sorted strings of our letters, e.g. {red: "AACCNNPPPPPRR", ...}. */
export function poolStrings(U: any, state: ObserverState): Record<Color, string> {
  const pools = U.poolsFor(state.knowledge, state.side);
  const fmt = (kinds: UKind[], color: Color): string => {
    const s = kinds.map((k) => FROM_U[k]).sort().join('');
    return color === 'red' ? s : s.toLowerCase();
  };
  return { red: fmt(pools.red, 'red'), black: fmt(pools.black, 'black') };
}

export function legalMoveTexts(U: any, state: ObserverState): string[] {
  const game = toGame(U, state);
  return game.legalMoves().map(moveText).sort();
}

export function debugSummary(U: any, state: ObserverState): Record<string, unknown> {
  const game = toGame(U, state);
  return {
    side: state.side,
    plies: state.plies,
    board: publicBoard(state),
    pools: poolStrings(U, state),
    learned: { red: state.learnedCount.red, black: state.learnedCount.black },
    halfMove: state.halfMove,
    repetition: state.repetitions.get(state.board.key) ?? 0,
    inCheck: game.inCheck(),
    legal: game.legalMoves().map(moveText).sort(),
    selectable: game.selectableMoves().map(moveText).sort(),
    ruleNotes: state.ruleNotes,
  };
}
