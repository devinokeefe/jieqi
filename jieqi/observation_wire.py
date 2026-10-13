"""Strict observation decoding by replaying PUBLIC events, never referee truth.

This checks the wire/knowledge ledger, not move geometry or game termination.
"""
import json

from .records import CaptureVisibility, Observation, ObservedMove, PoolKnowledge
from .setup import Color, Kind, POOL_KINDS, INVENTORY, square, start_squares


TOP = {'schema', 'viewer', 'side_to_move', 'board', 'pools', 'history', 'ply',
       'no_capture_plies', 'capture_visibility', 'counter_policy'}
EVENT = {'from', 'to', 'actor', 'revealed_mover', 'captured', 'captured_was_hidden', 'captured_identity'}
POOL = {'color', 'candidates', 'live_hidden_count', 'unknown_captured_count'}


def exact_fields(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError('unexpected ' + label + ' fields')


def public_start_board():
    board = ['.'] * 90
    for color in Color:
        for index in start_squares(color):
            board[index] = 'X' if color is Color.RED else 'x'
    board[square('e0')], board[square('e9')] = 'K', 'k'
    return ''.join(board)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def strict_json_loads(text):
    return json.loads(text, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))


def decode_observation(data):
    exact_fields(data, TOP, 'observation')
    if data['schema'] != 'jieqi-observation-v1' or data['counter_policy'] != 'capture_only_all_plies':
        raise ValueError('unsupported observation version/counter policy')
    viewer, turn = Color(data['viewer']), Color(data['side_to_move'])
    visibility = CaptureVisibility(data['capture_visibility'])
    if type(data['board']) is not str or len(data['board']) != 90:
        raise ValueError('invalid board length/type')
    if type(data['history']) is not list or type(data['pools']) is not list or len(data['pools']) != 2:
        raise ValueError('invalid history/pool list')
    for key in ('ply', 'no_capture_plies'):
        if type(data[key]) is not int or data[key] < 0:
            raise ValueError('invalid counter type/value')
    for pool in data['pools']:
        exact_fields(pool, POOL, 'pool')
        exact_fields(pool['candidates'], {k.value for k in POOL_KINDS}, 'candidate')
        for count in [*pool['candidates'].values(), pool['live_hidden_count'], pool['unknown_captured_count']]:
            if type(count) is not int or count < 0:
                raise ValueError('invalid pool count')
    board = list(public_start_board())
    counts = {color: list(INVENTORY) for color in Color}
    unknown = {color: 0 for color in Color}
    events, counter = [], 0
    for ply, raw in enumerate(data['history']):
        exact_fields(raw, EVENT, 'event')
        actor = Color.RED if ply % 2 == 0 else Color.BLACK
        if raw['actor'] != actor.value:
            raise ValueError('history turn mismatch')
        origin, destination = square(raw['from']), square(raw['to'])
        mover, target = board[origin], board[destination]
        if origin == destination or mover == '.' or mover.isupper() != (actor is Color.RED):
            raise ValueError('invalid structural mover')
        captured = target != '.'
        if captured and (target.isupper() == mover.isupper() or target.upper() == 'K'):
            raise ValueError('invalid structural target')
        hidden_target = target.upper() == 'X'
        if type(raw['captured']) is not bool or type(raw['captured_was_hidden']) is not bool:
            raise ValueError('capture flags must be booleans')
        if raw['captured'] != captured or raw['captured_was_hidden'] != hidden_target:
            raise ValueError('capture flags disagree with public board')
        reveal = raw['revealed_mover']
        if mover.upper() == 'X':
            if type(reveal) is not str or reveal not in {k.value for k in POOL_KINDS}:
                raise ValueError('missing/invalid public mover reveal')
            counts[actor][POOL_KINDS.index(Kind(reveal))] -= 1
        elif reveal is not None:
            raise ValueError('bright piece cannot reveal again')
        identity = raw['captured_identity']
        if hidden_target:
            can_know = visibility is CaptureVisibility.BOTH or (
                visibility is CaptureVisibility.CAPTURER_ONLY and viewer is actor)
            if can_know:
                if type(identity) is not str or identity not in {k.value for k in POOL_KINDS}:
                    raise ValueError('missing/invalid visible capture identity')
                counts[actor.opponent][POOL_KINDS.index(Kind(identity))] -= 1
            else:
                if identity is not None:
                    raise ValueError('private capture identity leaked to viewer')
                unknown[actor.opponent] += 1
        elif identity != (target.upper() if captured else None):
            raise ValueError('bright/empty capture identity mismatch')
        board[origin] = '.'
        board[destination] = (reveal if actor is Color.RED else reveal.lower()) if reveal else mover
        counter = 0 if captured else counter + 1
        events.append(ObservedMove(origin, destination, actor, Kind(reveal) if reveal else None,
                                   captured, hidden_target, Kind(identity) if identity else None))
    pools = tuple(PoolKnowledge(color, tuple(counts[color]), board.count('X' if color is Color.RED else 'x'),
                                unknown[color]) for color in Color)
    for pool in pools:
        if min(pool.candidates) < 0 or sum(pool.candidates) != pool.live_hidden_count + pool.unknown_captured_count:
            raise ValueError('invalid candidate inventory')
    expected_turn = Color.RED if len(events) % 2 == 0 else Color.BLACK
    result = Observation(viewer, expected_turn, ''.join(board), pools, tuple(events), counter, visibility)
    if turn is not expected_turn or result.to_dict() != data:
        raise ValueError('observation differs from its public history')
    return result


def validate_observation(observation):
    """Validate an in-memory projection without lossy serialization repairs.

    Wire replay verifies the knowledge ledger. These shape/type checks first
    prevent to_dict's zip and list conversions from hiding malformed fields.
    This remains structural validation, not a move-legality approval.
    """
    if (not isinstance(observation, Observation) or
            not isinstance(observation.viewer, Color) or not isinstance(observation.turn, Color) or
            not isinstance(observation.capture_visibility, CaptureVisibility) or
            type(observation.pools) is not tuple or len(observation.pools) != 2 or
            type(observation.history) is not tuple):
        raise ValueError('invalid observation field types')
    for pool in observation.pools:
        if (not isinstance(pool, PoolKnowledge) or not isinstance(pool.color, Color) or
                type(pool.candidates) is not tuple or len(pool.candidates) != len(POOL_KINDS)):
            raise ValueError('invalid pool field types or candidate arity')
    for event in observation.history:
        if (not isinstance(event, ObservedMove) or not isinstance(event.actor, Color) or
                (event.revealed_mover is not None and not isinstance(event.revealed_mover, Kind)) or
                (event.captured_identity is not None and not isinstance(event.captured_identity, Kind))):
            raise ValueError('invalid observed event field types')
    # coordinate() and decode_observation check exact integer/boolean fields,
    # board contents, counts, visibility, ordering and full history consistency.
    return decode_observation(observation.to_dict())


def public_history(observation):
    """Initial state and every public post-reveal board, each paired with turn."""
    observation = validate_observation(observation)
    board = list(public_start_board())
    result = [(''.join(board), Color.RED)]
    for event in observation.history:
        mover = event.revealed_mover.value if event.revealed_mover else board[event.origin].upper()
        board[event.destination] = mover if event.actor is Color.RED else mover.lower()
        board[event.origin] = '.'
        result.append((''.join(board), event.actor.opponent))
    return tuple(result)
