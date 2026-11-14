---
audience: contributor
kind: reference
---

# Specification

This section specifies each of G2's subsystems: what it does, how it behaves, what it connects to, which settings control it, the constraints it keeps, how it handles failure, and how to verify it. Each page states the present behaviour only. What is deployed and what has run on the robot is in [Status](../STATUS.md), and the overall structure is in [Architecture](../architecture.md).

Subsystems
----------

- [Locomotion](locomotion.md): Walking, stand-ups, postures and how every move starts and stops
- [Safety and recovery](safety.md): Emergency stop, falls, sagging legs, wobble, battery gates and the moves that are refused
- [Serial link](link.md): The one shared connection between the Pi and the BiBoard
- [Voice](voice.md): Wake word, local commands, the Claude conversation, speech and sounds
- [Memory](memory.md): The exchange log, saved facts and how they reach a conversation
- [Vision](perception.md): The camera, detection, pictures, wall distance and recognition
- [Behavior](behavior.md): The tick that composes idle, conversation, exploration and approach
- [Goals](goals.md): Sessions of attempts that are scored and judged on the Pi
- [Power](power.md): Packs, battery warnings, sleep and shutdown
- [Mode exceptions](mode-exceptions.md): The register of behaviors that differ in one mode because that was explicitly requested (empty by default)
