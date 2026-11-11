---
audience: contributor
kind: reference
---

# Vision

The vision subsystem gives G2 awareness of what is around it: detections, pictures, a wall-distance reading and recognition of things seen before.

Behaviour
---------

- Camera: A Grove Vision AI V2 runs object detection on the module itself and sends the Pi a running list of labels and boxes over USB serial. For a picture, the Pi asks for one small frame (240 × 240).
- Awareness and avoidance: A local reflex watches the detections and, with a wall-distance estimate from pictures, turns G2 away from a near wall. It makes no Claude call and no network call.
- Pictures: On request, one picture goes to Claude with the detector's labels, and G2 describes the scene aloud. During exploration G2 stops to take pictures of things worth a look.
- Recognition by instance: A second system fingerprints a photo crop and compares it with a library of earlier crops. A close match is "the same thing again", and nothing close joins the library unnamed until someone names it. It runs only while G2 is still, caps its disk use and never uploads.
- Picture tilt: The roll of a picture is estimated from its strongest edge direction as a second signal that the legs are sagging.

Interfaces
----------

- Detections to the [behavior](behavior.md) layer, and scene text to the [voice](voice.md) layer. Vision calls an injected "ask Claude" function and never imports voice code.
- The camera feed is read by a supervised background reader that restarts if it dies.

Parameters
----------

- Light metering: The light is metered every 30 s everywhere, not before every picture.
- Exposure balancing is always on for a picture.
- Detection model: One model slot, frozen firmware that decodes only the Swift-YOLO head ([Vision model training](../guides/train-vision-model.md#device-constraints-and-the-working-recipe)).

Constraints
-----------

- Frame age: The module answers each request with the previous picture, so a picture is taken twice and the first dropped. Claw camera frames are about 1 s old, so a look waits 1.5 s.
- Camera direction: A positive claw pan turns the camera left.
- Wall estimate: It needs recalibrating for the claw camera and reads "8 in" almost every time, so three identical readings in a row are not believed.
- Downloads: Models are fetched only with explicit approval and are never committed ([Models](../guides/models.md)).

Failure handling
----------------

- Camera not answering: The reader restarts and the picture is skipped.
- No strong edges in a picture: The tilt estimate says nothing.

Verification
------------

- Tests run the detection layer, the wall estimator and the tilt estimator on synthetic pictures.
- Robot: A roam with picture stops saves pictures under `~/.local/share/g2/explore_pictures/`.
