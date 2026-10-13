"""Original Linux wall-clock interruption around opaque external search calls."""
import signal
import time

class SearchDeadline(BaseException):
    pass

def completed_iterations(search_one, fallback, *, deadline_ns, max_depth=7):
    """Retain only completed iterations; never consume a partial external table.

    Call from the single actor main thread. Preparation time is already charged
    in deadline_ns. The separate parent hard clock remains authoritative.
    """
    if type(max_depth) is not int or not 1<=max_depth<=64:raise ValueError('invalid depth cap')
    if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):raise ValueError('timer already owned')
    result=dict(move=fallback,score=None,completed_depth=0,selected_depth=0,
                interrupted=False,selection='static_legal_fallback')
    remaining=(deadline_ns-time.monotonic_ns())/1e9
    if remaining<=0:
        result['interrupted']=True;return result
    old=signal.getsignal(signal.SIGALRM)
    def interrupt(*_):raise SearchDeadline()
    signal.signal(signal.SIGALRM,interrupt)
    try:
        signal.setitimer(signal.ITIMER_REAL,remaining)
        for depth in range(1,max_depth+1):
            move,score=search_one(depth)
            result['completed_depth']=depth
            if move is not None:
                result.update(move=move,score=score,selected_depth=depth,selection='completed_iteration')
    except SearchDeadline:
        result['interrupted']=True
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,old)
    return result
