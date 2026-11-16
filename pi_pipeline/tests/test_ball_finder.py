"""The colour ball finder (vision/ball_finder.py) on synthetic pictures."""
from pi_pipeline.vision import ball_finder as bf


# ---- 2026-11-16: a pale ball at the horizon (he turned away from a ball right in front of him)

def _jpeg(draw):
    import io

    from PIL import Image, ImageDraw
    im = Image.new("RGB", (240, 240), (110, 108, 106))
    draw(ImageDraw.Draw(im))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


PALE = (92, 136, 92)                  # brightest green under 140 and a dominance of about 44: the normal rule's brightness floor rejects it


def test_a_pale_ball_at_the_horizon_is_found_by_the_second_dim_rule_and_marked_for_confirmation():
    jpeg = _jpeg(lambda d: d.ellipse((112, 69, 130, 87), fill=PALE))              # about 18 px across, centre row 78: a ball 24 to 30 in away
    r = bf.find_ball(jpeg)
    assert r is not None and r.via == "dim" and 70 <= r.y <= 85 and abs(r.x - 121) < 4


def test_a_pale_ball_5_to_9_inches_away_is_found_in_the_lower_half_but_a_big_green_patch_high_in_the_frame_is_not():
    near = bf.find_ball(_jpeg(lambda d: d.ellipse((90, 130, 135, 175), fill=PALE)))              # about 45 px across (about 1600 px), centre row 152
    assert near is not None and near.via == "dim" and near.y > 140
    high = bf.find_ball(_jpeg(lambda d: d.ellipse((90, 15, 135, 60), fill=PALE)))                # the same patch high in the frame: a wall or a plant
    assert high is None


def test_the_second_dim_rule_keeps_its_floor_and_a_small_speck_is_still_nothing():
    assert bf.find_ball(_jpeg(lambda d: d.ellipse((118, 74, 121, 77), fill=PALE))) is None      # 4 px: under the area floor
    assert bf.find_ball(_jpeg(lambda d: d.ellipse((112, 15, 130, 33), fill=PALE))) is None      # right size, but above row 65: not on the floor


# ---- 2026-11-16: the ball found by its own colour

def test_the_ball_is_found_by_its_own_colour_when_the_fixed_rules_miss_it():
    pale = (92, 138, 92)
    jpeg = _jpeg(lambda d: d.ellipse((113, 70, 129, 86), fill=pale))                     # 16 px, centre row 78
    close_up = (157, 211, 142)                                                           # a reference sampled up close, in much brighter light
    r = bf.find_ball_color(jpeg, close_up)
    assert r is not None and r.via == "color" and 70 <= r.y <= 85 and abs(r.x - 121) < 4
    assert bf.find_ball_color(jpeg, (200, 60, 60)) is None                               # a red reference never matches a green ball
    assert bf.find_ball_color(jpeg, None) is None


def test_a_gray_floor_and_a_blob_high_in_the_frame_are_not_the_ball_by_colour():
    assert bf.find_ball_color(_jpeg(lambda d: None), (92, 138, 92)) is None             # nothing but floor
    high = _jpeg(lambda d: d.ellipse((113, 15, 129, 31), fill=(92, 138, 92)))
    assert bf.find_ball_color(high, (92, 138, 92)) is None                               # above row 65: a wall or a plant


def test_a_reading_carries_the_blobs_mean_colour():
    r = bf.find_ball(_jpeg(lambda d: d.ellipse((100, 120, 140, 160), fill=(30, 200, 40))))
    assert r is not None and r.color is not None and r.color[1] > r.color[0] and r.color[1] > r.color[2]


def test_the_ball_target_falls_back_to_the_colour_only_when_it_has_one():
    from pi_pipeline.behavior.gallery_target import BallTarget
    jpeg = _jpeg(lambda d: d.ellipse((113, 70, 129, 86), fill=(92, 138, 92)))
    assert BallTarget().detections(jpeg) == [] or BallTarget().detections(jpeg)[0][0] == "ball"
    assert BallTarget(color=(157, 211, 142)).detections(jpeg)                           # found by its colour
