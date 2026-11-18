"""The wall replay's score: how many labelled walls a detector acts on by distance, and how many pictures labelled `nothing` it wrongly acts on."""
from pi_pipeline.vision import wall_replay as wr


def test_the_score_counts_walls_acted_on_by_distance_and_false_alarms():
    shots = [{"label": "wall_straight", "true_in": 8, "action": "turn left (wall ahead)"}, {"label": "wall_straight", "true_in": 12, "action": "none"},
             {"label": "wall_straight", "true_in": 20, "action": "turn right (wall ahead)"}, {"label": "wall_far", "true_in": 40, "action": "none"}, {"label": "door", "true_in": 10, "action": "none"}]
    roam = [{"shot": "a.jpg", "label": "nothing", "action": "none"}, {"shot": "b.jpg", "label": "nothing", "action": "turn left (wall ahead)"}, {"shot": "c.jpg", "label": "wall", "action": "none"}]
    s = wr.score(shots, roam)
    assert s["wall acted on"] == {"within 12 in": "1 of 2", "13 to 24 in": "1 of 1", "farther than 24 in": "0 of 1"}
    assert s["false alarms (labelled nothing, acted on)"] == "1 of 2" and s["false alarm shots"] == ["b.jpg"]
