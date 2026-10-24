"""Two-hand window resizing: pinch with both hands, stretch or squeeze."""
from rotary.gestures import extract_features
from rotary.resize import ActiveWindow, Rect, TwoHandResize, WindowSizer, axis_for, target_rect
from tests.synth import make_hand

FPS = 30


def hands(left, right, pinch=(True, True), size=0.18):
    return [extract_features(make_hand(center=left, pinch=pinch[0], handed="Left", size=size), True),
            extract_features(make_hand(center=right, pinch=pinch[1], size=size), True)]


def run(r, frames, t0=0.0):
    """Feed (left, right[, pinch]) frames at 30 fps; return every event and the end time."""
    events, t = [], t0
    for fr in frames:
        events += r.update(hands(*fr), t)
        t += 1 / FPS
    return events, t


def names(events):
    return [e[0] for e in events]


def test_synthetic_pinch_reads_as_a_pinch():
    pinched = hands((0.4, 0.5), (0.9, 0.5))[0]
    open_ = hands((0.4, 0.5), (0.9, 0.5), pinch=(False, False))[0]
    assert pinched.pinch < 0.32 < 0.5 < open_.pinch


def test_hands_side_by_side_stretch_the_width():
    r = TwoHandResize()
    ev, t = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12)
    assert ("resize_start", "x") in ev
    assert r.busy
    ev, t = run(r, [((0.5 - 0.01 * i, 0.5), (0.9 + 0.01 * i, 0.5)) for i in range(1, 21)], t)
    sx, sy = [p for n, p in ev if n == "resize"][-1]
    assert sx > 1.5 and sy == 1.0
    ev, _ = run(r, [((0.3, 0.5), (1.1, 0.5), (False, False))] * 3, t)
    assert ("resize_end", "released") in ev and not r.busy


def test_squeezing_shrinks_and_one_above_the_other_is_the_height():
    r = TwoHandResize()
    ev, t = run(r, [((0.7, 0.2), (0.72, 0.8))] * 12)
    assert ("resize_start", "y") in ev
    ev, _ = run(r, [((0.7, 0.2 + 0.01 * i), (0.72, 0.8 - 0.01 * i)) for i in range(1, 16)], t)
    sx, sy = [p for n, p in ev if n == "resize"][-1]
    assert sx == 1.0 and sy < 0.7


def test_opposite_corners_change_both():
    r = TwoHandResize()
    ev, t = run(r, [((0.5, 0.3), (0.9, 0.7))] * 12)
    assert ("resize_start", "xy") in ev
    ev, _ = run(r, [((0.5 - 0.01 * i, 0.3 - 0.01 * i), (0.9 + 0.01 * i, 0.7 + 0.01 * i)) for i in range(1, 16)], t)
    sx, sy = [p for n, p in ev if n == "resize"][-1]
    assert sx > 1.3 and sy > 1.3


def test_one_hand_pinching_or_a_quick_pinch_does_nothing():
    r = TwoHandResize()
    ev, _ = run(r, [((0.5, 0.5), (0.9, 0.5), (True, False))] * 20)
    assert ev == [] and not r.busy
    ev, _ = run(r, [((0.5, 0.5), (0.9, 0.5))] * 4)            # under the hold time
    assert ev == []


def test_losing_a_hand_ends_it_and_pinching_again_carries_on_from_there():
    r = TwoHandResize()
    ev, t = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12)
    assert "resize_start" in names(ev)
    ev = []
    for _ in range(15):
        ev += r.update(hands((0.5, 0.5), (0.9, 0.5))[:1], t)
        t += 1 / FPS
    assert ("resize_end", "lost") in ev and not r.busy
    ev, _ = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12, t)       # like a clutch: grab again, stretch further
    assert "resize_start" in names(ev)


def test_a_cancelled_resize_waits_for_both_hands_to_let_go():
    r = TwoHandResize()
    ev, t = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12)
    assert r.cancel() == [("resize_end", "cancelled")]
    ev, t = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12, t)
    assert ev == []
    ev, t = run(r, [((0.5, 0.5), (0.9, 0.5), (False, False))] * 3, t)
    ev, _ = run(r, [((0.5, 0.5), (0.9, 0.5))] * 12, t)
    assert "resize_start" in names(ev)


def test_hands_touching_the_face_are_ignored():
    r = TwoHandResize()
    events, t = [], 0.0
    for _ in range(15):
        hs = hands((0.5, 0.5), (0.9, 0.5))
        hs[0].at_face = True
        events += r.update(hs, t)
        t += 1 / FPS
    assert events == []


def test_axis():
    assert axis_for(0.5, 0.05) == "x"
    assert axis_for(0.05, 0.5) == "y"
    assert axis_for(0.4, 0.4) == "xy"


def test_target_rect_scales_about_the_centre_and_stays_on_screen():
    work = Rect(0, 0, 1920, 1040)
    start = Rect(400, 300, 800, 500)
    assert target_rect(start, 1.5, 1.0, work) == Rect(200, 300, 1200, 500)
    assert target_rect(start, 0.1, 0.1, work) == Rect(640, 450, 320, 200)        # usable minimum
    big = target_rect(start, 4.0, 4.0, work)
    assert big == Rect(0, 0, 1920, 1040)                                          # no bigger than the screen
    edge = target_rect(Rect(1500, 100, 400, 300), 1.5, 1.0, work)
    assert edge.x + edge.w <= 1920 and edge.w == 600                              # pushed back on screen


def test_window_sizer_applies_the_latest_size_to_the_window_in_front():
    import threading
    win = ActiveWindow("w1", Rect(100, 100, 400, 300), Rect(0, 0, 1920, 1080), "Notes")
    applied, started, done = [], [], threading.Event()

    def set_rect(handle, rect):
        applied.append((handle, rect))
        if rect.w == 800:
            done.set()
        return True

    s = WindowSizer(lambda: win, set_rect, started.append)
    s.begin()
    s.scale(1.5, 1.0)
    s.scale(2.0, 1.0)
    assert done.wait(2.0)
    assert started == [win]
    assert applied[-1] == ("w1", Rect(0, 100, 800, 300))            # 2x about the centre, kept on screen
    s.end()


def test_nothing_windowed_in_front_tells_the_app():
    import threading
    got, ev = [], threading.Event()
    s = WindowSizer(lambda: None, lambda h, r: True, lambda w: (got.append(w), ev.set()))
    s.begin()
    assert ev.wait(2.0) and got == [None]
