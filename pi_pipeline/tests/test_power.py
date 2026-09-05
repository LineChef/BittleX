from pi_pipeline.power import power as P


def test_status_shape():
    s = P.status()
    assert set(s) >= {"on_pi", "cpu_governor", "wifi_power_save", "boot_config_lines_needed"}
    assert "dtparam=audio=off" in s["boot_config_lines_needed"]


def test_governor_refuses_powersave():
    try:
        P.set_cpu_governor("powersave", dry_run=True)
        assert False, "should have raised"
    except ValueError as e:
        assert "powersave" in str(e)


def test_governor_dry_run():
    acts = P.set_cpu_governor("ondemand", dry_run=True)
    assert acts and all("ondemand" in x or "DRY-RUN" in x for x in acts)


def test_wifi_dry_run():
    ok, msg = P.set_wifi_power_save(True, dry_run=True)
    assert ok and "power_save on" in msg


def test_profiles_dry_run():
    h = P.apply_headless_profile(dry_run=True)
    assert set(h) == {"leds", "wifi_power_save", "governor"}
    i = P.apply_interactive_profile(dry_run=True)
    assert i["wifi_power_save"][1].endswith("power_save off")
