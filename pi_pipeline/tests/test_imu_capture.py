from pi_pipeline.gait.imu_capture import capture, summarise


def line(ax, ay, az, yaw, pitch, roll):
    return f"ICM:{ax:6.2f}{ay:6.2f}{az:6.2f}{-yaw:7.1f}{pitch:7.1f}{roll:7.1f}"


def test_the_capture_reads_accel_and_angles_and_the_summary_gives_rate_bias_and_noise():
    t = [0.0]
    frames = [line(0.10 + 0.01 * (i % 2), -0.05, 9.80, 1.0, -2.0, 3.0) for i in range(60)]
    it = iter(frames)

    def poll():
        out = [next(it, None)] if True else []
        return [x for x in out if x]

    def clock():
        return t[0]

    def sleep(s):
        t[0] += 0.2                                           # one frame every 0.2 s: 5 Hz
    rows = capture(poll, 10.0, clock=clock, sleep=sleep)
    s = summarise(rows)
    assert 40 <= s["frames"] <= 51 and abs(s["rate_hz"] - 5.0) < 0.3
    assert abs(s["az"]["mean"] - 9.8) < 0.01 and s["az"]["std"] < 0.01 and abs(s["ax"]["mean"] - 0.105) < 0.02
    assert abs(s["roll_deg"]["mean"] - 3.0) < 0.1 and abs(s["pitch_deg"]["mean"] + 2.0) < 0.1
    assert summarise([]) == {"frames": 0}
