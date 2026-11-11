# Walking and training

This section explains how G2's walking gait is trained in simulation, scored, exported and deployed to the robot. The gait is a small neural network that adds corrections to Petoi's scripted walk. Which policy is deployed and how it has done on G2 is on the [Current status](../STATUS.md) page.

Start here
----------

- [Walking policy](walking-policy.md): What the learned gait does, what it cannot do and how it is built.
- [Training pipeline](training-pipeline.md): The whole path from an idea to a file on G2: choose settings, train, score, export, promote and feed real data back.

Training and testing details
----------------------------

- [Passability audit](passability-audit.md): The rule that simulated difficulty never rises above what a capable policy can pass, and how each hazard's limit is measured.
- [Skill learning method](skill-learning-method.md): The recipe for teaching G2 a new motor skill.
- [Hardware logging](hardware-logging.md): What a real-robot walk log contains and what is useful as training evidence.
- [Real-data pipeline](real-data-pipeline.md): How walks on the robot are logged, checked and turned into simulation calibration.

Deployment on the Pi is covered in [Gait deployment](../guides/gait-deployment.md). The code index for the trainer is in the [training code README](../../rl_training/README.md).
