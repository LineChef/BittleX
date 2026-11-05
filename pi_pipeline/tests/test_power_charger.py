"""On the charger, Wi-Fi power-save stays off (power/charger.py); on the battery sleep mode still saves power."""
from pi_pipeline.power import charger, power


def test_plugged_is_remembered_and_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_ON_CHARGER", str(tmp_path / "on_charger"))
    assert not charger.is_plugged()
    assert charger.set_plugged(True) and charger.is_plugged() and charger.plugged_since()
    assert not charger.set_plugged(True)                                                     # already recorded: nothing changed
    assert charger.set_plugged(False) and not charger.is_plugged()
    assert not charger.set_plugged(False)


def test_wifi_power_save_is_never_turned_on_while_on_the_charger(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_ON_CHARGER", str(tmp_path / "on_charger"))
    ok, said = power.set_wifi_power_save(True, dry_run=True)
    assert ok and said.endswith("power_save on")                                             # on the battery: as asked
    charger.set_plugged(True)
    ok, said = power.set_wifi_power_save(True, dry_run=True)
    assert ok and "power_save off" in said and "on the charger" in said                      # sleep mode asks for "on": it stays off
    assert power.set_wifi_power_save(False, dry_run=True)[1].endswith("power_save off")
    assert power.apply_headless_profile(dry_run=True)["wifi_power_save"][1].count("power_save off") == 1
    charger.set_plugged(False)
    assert power.set_wifi_power_save(True, dry_run=True)[1].endswith("power_save on")        # back on the battery


def test_the_power_commands_record_and_clear_it(tmp_path, monkeypatch, capsys):
    from pi_pipeline.power import __main__ as cli
    monkeypatch.setenv("G2_ON_CHARGER", str(tmp_path / "on_charger"))
    cli.main(["plugged"])
    assert charger.is_plugged() and "on the charger" in capsys.readouterr().out
    assert power.status()["on_charger"] is True
    cli.main(["unplugged"])
    assert not charger.is_plugged() and "off the charger" in capsys.readouterr().out
