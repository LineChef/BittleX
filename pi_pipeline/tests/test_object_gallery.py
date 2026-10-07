from pi_pipeline.vision.object_gallery import (
    GalleryDecision,
    ObjectGallery,
    ObjectGalleryConfig,
)

# same_instance_threshold=0.80, near_duplicate_threshold=0.93 (defaults).
# Hand-picked so cosine similarity lands in a known band:
E_A = [1.0, 0.0]           # a "family"
E_A_SAMPLE = [1.0, 0.5]    # cos(E_A) ~= 0.894 -- same instance, worth another sample
E_A_DUP = [1.0, 0.05]      # cos(E_A) ~= 0.9988 -- same instance, too similar to bother
E_B = [0.0, 1.0]           # orthogonal to E_A -- a different object
E_C = [-1.0, 0.0]          # opposite E_A -- a third, different object


def test_new_entry_when_nothing_matches():
    g = ObjectGallery()
    d = g.consider(E_A, quality=0.9, now=1.0)
    assert d is GalleryDecision.NEW
    assert len(g.entries) == 1
    e = next(iter(g.entries.values()))
    assert e.sample_count == 1 and e.first_seen == 1.0 and e.last_seen == 1.0


def test_low_quality_refused_before_ever_comparing():
    g = ObjectGallery(ObjectGalleryConfig(min_quality=0.5))
    d = g.consider(E_A, quality=0.2, now=1.0)
    assert d is GalleryDecision.LOW_QUALITY
    assert len(g.entries) == 0


def test_same_instance_within_dup_band_adds_a_sample():
    g = ObjectGallery()
    g.consider(E_A, quality=0.9, now=1.0)
    d = g.consider(E_A_SAMPLE, quality=0.9, now=2.0)
    assert d is GalleryDecision.ADD_SAMPLE
    assert len(g.entries) == 1
    e = next(iter(g.entries.values()))
    assert e.sample_count == 2 and e.last_seen == 2.0


def test_near_duplicate_is_recognised_but_not_resampled():
    g = ObjectGallery()
    g.consider(E_A, quality=0.9, now=1.0)
    d = g.consider(E_A_DUP, quality=0.9, now=2.0)
    assert d is GalleryDecision.DUPLICATE
    e = next(iter(g.entries.values()))
    assert e.sample_count == 1                # no new sample added
    assert e.last_seen == 2.0                  # but recognised as "still here"


def test_different_object_gets_its_own_entry():
    g = ObjectGallery()
    g.consider(E_A, quality=0.9, now=1.0)
    d = g.consider(E_B, quality=0.9, now=2.0)
    assert d is GalleryDecision.NEW
    assert len(g.entries) == 2


def test_locked_entry_is_recognised_but_never_resampled():
    g = ObjectGallery()
    g.consider(E_A, quality=0.9, now=1.0)
    eid = next(iter(g.entries))
    g.mark_complete(eid)
    d = g.consider(E_A_SAMPLE, quality=0.9, now=2.0)
    assert d is GalleryDecision.LOCKED
    assert g.entries[eid].sample_count == 1
    assert g.entries[eid].last_seen == 2.0     # still updates -- it's still recognised

    g.mark_incomplete(eid)
    d2 = g.consider(E_A_SAMPLE, quality=0.9, now=3.0)
    assert d2 is GalleryDecision.ADD_SAMPLE     # unlocking resumes sampling


def test_auto_locks_once_max_samples_reached():
    g = ObjectGallery(ObjectGalleryConfig(max_samples_per_entry=2))
    g.consider(E_A, quality=0.9, now=1.0)                    # sample 1
    g.consider(E_A_SAMPLE, quality=0.9, now=2.0)             # sample 2 -> auto-lock
    eid = next(iter(g.entries))
    assert g.entries[eid].locked
    d = g.consider(E_A_SAMPLE, quality=0.9, now=3.0)
    assert d is GalleryDecision.LOCKED                        # no 3rd sample


def test_capacity_evicts_oldest_unnamed_unlocked_entry():
    g = ObjectGallery(ObjectGalleryConfig(max_entries=2))
    g.consider(E_A, quality=0.9, now=1.0)     # NEW, oldest
    g.consider(E_B, quality=0.9, now=2.0)     # NEW, fills capacity
    d = g.consider(E_C, quality=0.9, now=3.0)  # over capacity -> evict E_A, then add
    assert d is GalleryDecision.NEW
    assert len(g.entries) == 2
    centroids = [tuple(e.centroid) for e in g.entries.values()]
    assert tuple(E_A) not in centroids        # the oldest one is gone
    assert tuple(E_B) in centroids and tuple(E_C) in centroids


def test_named_and_locked_entries_are_never_evicted_and_do_not_count_against_the_candidate_cap():
    g = ObjectGallery(ObjectGalleryConfig(max_entries=1))
    g.consider(E_A, quality=0.9, now=1.0)
    eid = next(iter(g.entries))
    g.set_name(eid, "keys")                    # protected: labeled, and exempt from the cap (retention policy 2026-10-07)
    assert g.consider(E_B, quality=0.9, now=2.0) is GalleryDecision.NEW            # a named entry leaves room for a candidate
    assert g.consider(E_C, quality=0.9, now=3.0) is GalleryDecision.NEW            # the cap of 1 is on candidates: E_B (unnamed) is evicted for E_C
    assert len(g.entries) == 2 and g.entries[eid].name == "keys"                   # the named one is untouched


def test_the_total_ceiling_stops_new_entries_but_never_removes_one():
    g = ObjectGallery(ObjectGalleryConfig(max_entries=10, max_total_entries=2))
    g.consider(E_A, quality=0.9, now=1.0)
    g.consider(E_B, quality=0.9, now=2.0)
    assert g.consider(E_C, quality=0.9, now=3.0) is GalleryDecision.REJECTED_AT_CAPACITY
    assert len(g.entries) == 2


