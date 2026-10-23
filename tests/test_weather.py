import time

from rotary import volume
from rotary.weather import kind_for, parse


def _j1(code="296", temp_c="9", temp_f="48", sunrise="07:12 AM", sunset="06:20 PM"):
    return {"current_condition": [{"weatherCode": code, "temp_C": temp_c, "temp_F": temp_f,
                                   "weatherDesc": [{"value": "Light rain"}]}],
            "weather": [{"astronomy": [{"sunrise": sunrise, "sunset": sunset}]}]}


def test_condition_codes_become_icons():
    assert kind_for(113) == "clear" and kind_for(116) == "partly" and kind_for(122) == "cloudy"
    assert kind_for(248) == "fog" and kind_for(296) == "rain" and kind_for(338) == "snow"
    assert kind_for(389) == "storm" and kind_for(999) == "cloudy"


def test_parse_reads_the_current_weather_and_whether_its_night():
    noon = time.struct_time((2026, 10, 23, 12, 0, 0, 4, 296, 0))
    w = parse(_j1(), noon)
    assert (w.kind, w.temp_c, w.temp_f, w.night, w.text) == ("rain", 9.0, 48.0, False, "Light rain")
    assert w.temperature(True) == "48°"
    late = time.struct_time((2026, 10, 23, 21, 30, 0, 4, 296, 0))
    assert parse(_j1("113"), late).night
    assert parse(_j1("113", sunrise="??"), time.struct_time((2026, 10, 23, 5, 0, 0, 4, 296, 0))).night
    assert parse({}) is None and parse({"current_condition": [{"weatherCode": "x"}]}) is None


def test_volume_set_goes_to_a_level(monkeypatch):
    if volume.sys.platform == "win32":
        return                                  # Core Audio: covered by hand
    calls, levels = [], []
    monkeypatch.setattr(volume, "_posix_set", lambda lv: calls.append(lv) or True)
    monkeypatch.setattr(volume, "_posix_get", lambda: 0.3)
    v = volume.Volume(levels.append)
    v.set(0.71)
    for _ in range(100):
        if levels:
            break
        time.sleep(0.01)
    assert calls == [0.72] and levels == [0.72]      # rounded to the slider's 2 % steps
    got = []
    v.read(got.append)
    for _ in range(100):
        if got:
            break
        time.sleep(0.01)
    assert got == [0.3]


def test_old_default_rotary_size_becomes_the_new_one(tmp_path):
    import json
    from rotary.actions import load_config
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"version": 2, "appearance": {"dial_size": 600}}))
    assert load_config(path)["appearance"]["dial_size"] == 540
    path.write_text(json.dumps({"version": 2, "appearance": {"dial_size": 680}}))
    assert load_config(path)["appearance"]["dial_size"] == 680       # a size someone chose stays
    path.write_text(json.dumps({"version": 3, "appearance": {"dial_size": 600}}))
    assert load_config(path)["appearance"]["dial_size"] == 600
