"""The first-run tour: which cards each user gets, goals ticking off, skipping, and the config flag."""
import json

import shiboken6
from PySide6.QtWidgets import QApplication

from rotary import actions, tutorial
from rotary.gestures import EngineSnapshot
from rotary.ui.tutorial import TutorialWindow

app = QApplication.instance() or QApplication([])


def keys(ctx):
    return [s.key for s in tutorial.steps_for(ctx)]


def test_camera_users_learn_the_hand_shapes_and_the_mouse():
    k = keys(tutorial.Context())
    assert k[0] == "welcome" and k[-1] == "done"
    for want in ("palm", "open", "turn", "knob", "launch", "point", "close", "volume", "notch", "mouse"):
        assert want in k
    assert k.index("close") < k.index("notch")            # gestures first, then the camera-free way
    assert "gestures_later" not in k


def test_mouse_users_skip_the_gestures():
    k = keys(tutorial.Context(camera=False, notch=True))
    assert not {"palm", "open", "turn", "knob", "launch", "close", "volume"} & set(k)
    assert {"notch", "mouse", "gestures_later"} <= set(k)


def test_cards_follow_the_users_settings():
    no_grip = tutorial.steps_for(tutorial.Context(grip=False, still_seconds=1.0))
    opener = next(s for s in no_grip if s.key == "open")
    assert opener.pose == "palm" and "1 second" in opener.body and "fist" not in opener.body
    assert "knob" not in [s.key for s in no_grip]
    move = next(s for s in tutorial.steps_for(tutorial.Context(turn_style="move")) if s.key == "turn")
    assert "Slide" in move.body
    k = keys(tutorial.Context(volume=False, finger=False, assist_key=""))
    assert "volume" not in k and "point" not in k and "assist" not in k


def test_text_names_the_users_shortcuts():
    steps = tutorial.steps_for(tutorial.Context(hotkey="⌃⌥Space", assist_key="⌃⌥A", notch=False))
    text = " ".join(s.body + s.hint for s in steps)
    assert "⌃⌥Space" in text and "⌃⌥A" in text and "{" not in text


def test_other_features_can_add_cards():
    try:
        tutorial.register(tutorial.Step("resize", "Resize a window", "Pinch with both hands.", "pinch"),
                          after="volume")
        tutorial.register(tutorial.Step("resize2", "And corners", "Both at once.", "pinch"), after="volume")
        tutorial.register(tutorial.Step("cam_only", "x", "y", when=lambda c: c.camera), after="nowhere")
        k = keys(tutorial.Context())
        assert k[k.index("volume") + 1:k.index("volume") + 3] == ["resize", "resize2"]
        assert k[-2:] == ["cam_only", "done"]                    # unknown anchor: just before the end
        assert "cam_only" not in keys(tutorial.Context(camera=False))
    finally:
        for key in ("resize", "resize2", "cam_only"):
            tutorial.unregister(key)
    assert "resize" not in keys(tutorial.Context())


def test_goals_tick_once_and_only_on_their_own_card():
    t = tutorial.Tour(tutorial.steps_for(tutorial.Context()))
    assert t.done and not t.feed("open")                       # the welcome card has no goal
    t.go([s.key for s in t.steps].index("palm"))
    assert not t.done
    assert not t.feed("open")
    assert not t.feed_snapshot(EngineSnapshot(presented=False))
    assert t.feed_snapshot(EngineSnapshot(presented=True))
    assert t.done and not t.feed_snapshot(EngineSnapshot(presented=True))
    t.next()
    assert t.step.key == "open" and t.feed("open")


def test_window_walks_through_and_reports_how_it_ended():
    steps = tutorial.steps_for(tutorial.Context())
    ended = []
    w = TutorialWindow(steps, reduce_motion=True)
    w.finished.connect(ended.append)
    w.start()
    assert w.practice and w.count.text() == f"1 of {len(steps)}"
    assert not w.back_btn.isEnabled()
    w.next()
    w.feed_snapshot(EngineSnapshot(presented=True))
    assert "Nice" in w.hint.text() and w._advance.isActive()    # ticks, then moves on by itself
    for _ in range(len(steps)):
        w.next()
    assert ended == [True] and not w.isVisible() and not w.practice
    shiboken6.delete(w)             # now, while the QApplication is still there (as the app does with deleteLater)

    ended.clear()
    w = TutorialWindow(steps, reduce_motion=True)
    w.finished.connect(ended.append)
    w.start()
    w.skip.click()
    w.end(False)                                                # only reported once
    assert ended == [False]
    shiboken6.delete(w)


def test_new_users_get_the_tour_and_existing_users_dont(tmp_path):
    fresh = tmp_path / "fresh.json"
    assert actions.load_config(fresh)["general"]["tutorial_done"] is False
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"general": {"onboarded": True}}), encoding="utf-8")
    assert actions.load_config(old)["general"]["tutorial_done"] is True
    half = tmp_path / "half.json"                               # never finished the welcome page
    half.write_text(json.dumps({"general": {"onboarded": False}}), encoding="utf-8")
    assert actions.load_config(half)["general"]["tutorial_done"] is False
    done = tmp_path / "done.json"
    done.write_text(json.dumps({"general": {"onboarded": True, "tutorial_done": False}}), encoding="utf-8")
    assert actions.load_config(done)["general"]["tutorial_done"] is False
