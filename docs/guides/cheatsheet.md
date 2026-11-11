---
audience: builder
kind: reference
---

# Cheat sheet

Commands to run, one example per row: copy it and change the value. Every option is in [`shell-helpers.md`](shell-helpers.md) (`g2help` prints it in the terminal). Before G2 moves: [`operating-g2.md`](operating-g2.md). Setup, training, bring-up and repo commands: [`cheatsheet-advanced.md`](cheatsheet-advanced.md).

Jump to: [Most used](#most-used) · [Stop](#stop-and-safety) · [Walk tests](#walk-tests) · [Explore](#explore) · [Ball goal](#ball-goal-and-punts) · [Claw and camera](#claw-and-camera) · [Data](#data-and-review) · [Pi power](#pi-power-and-network) · [Voice and mic](#voice-and-mic) · [Say to G2](#things-to-say-to-g2) · [A to Z](#a-to-z)

## Most used

- `g2rest`: rest G2 now
- `g2standup`: one eased stand-up from rest, then rest again (`g2standup 5` for five)
- `g2stop voice`: stop the voice service safely
- `g2reset`: restart the voice loop
- `g2floor hardwood`: set the floor before any walk
- `g2ball`: start the ball goal
- `g2ballstop`: stop the ball goal
- `g2explore start`: start exploring
- `g2pics`: open the review page
- `g2sync run --force all`: copy everything from the Pi
- `g2mic off 30`: wake word off for 30 minutes
- `g2deploy --once`: deploy the last commit to the Pi now (no flag: waits for the Pi to come online)
- `g2ssh`: open a shell on the Pi

## Stop and safety

- `"G2, emergency stop"`: freeze everything ("resume" releases)
- `g2rest`: rest G2 when nothing is in control
- `g2stop voice`: stop the voice service (rests him first)
- `g2stop explore`: stop an exploration (rests him first)
- `g2explore halt`: freeze an exploration
- `g2explore release`: release the freeze
- `g2app --bench`: work on the bench: no autonomous movement

Never put G2 on his back. Tests start on his feet, hands near. Never deploy while testing.

## Walk tests

- `g2floor tile`: set the floor (every log records it)
- `g2walk 3 hardwood`: three logged 12.5 s walks
- `g2baseline status`: check a baseline run
- `g2baseline fetch`: copy the baseline logs to the Mac
- `g2turns start`: logged turn runs (real turn rate)
- `g2walklog ~/g2_runs/x.csv`: summarize a walk log
- `g2imu rest 20`: record the raw IMU for 20 s

## Explore

- `g2explore start 300`: explore for 300 s
- `g2explore stop`: end the session
- `g2explore status`: what is running
- `g2explore logs`: the recent log
- `g2explore heard`: what the listener heard
- `g2explore report html`: open the last roam's report

## Ball goal and punts

Voice: "G2, ball goal". The goal tools are also in the review page's Goals tab ([`goals.md`](goals.md)).

- `g2ball`: start a session (G2 in rest, hands near)
- `g2ballstop`: end it; G2 rests
- `g2goal report`: open the goal report
- `g2goal status`: what each goal has learned
- `g2goal history ball_punt`: the last sessions
- `g2goal show ball_punt`: every setting and who changes it
- `g2goal suggestions`: changes G2 suggests
- `g2goal confirm ball_punt punt_max_in`: accept a suggestion
- `g2goal cancel ball_punt punt_max_in`: decline it
- `g2goal pin ball_punt punt_max_in 4`: hold a value
- `g2goal limit ball_punt punt_max_in 3 5`: keep it between 3 and 5
- `g2goal undo ball_punt punt_max_in`: ban the value he settled on
- `g2goal forget ball_punt punt_max_in`: drop what he learned for it
- `g2goal overrides ball_punt`: list the pins and limits
- `g2goal verdict ball_punt 22 wrong`: attempt 22 was scored wrong
- `g2goal set ball_punt --attempts 8`: change a goal's size
- `g2goal reset ball_punt --yes`: forget everything it learned
- `g2goal priority walls ball_punt`: set the goal order
- `g2goal practise`: what "G2, practise" would choose
- `g2goal apply`: send queued Goals-tab edits to the Pi
- `g2punt`: one punt attempt
- `g2puntstop`: stop it
- `g2puntset show`: the punt settings in use
- `g2puntset punt_max_in 3.5`: change one punt setting
- `g2puntset nudge_gait policy`: small steps with the learned walk (default: scripted)

## Claw and camera

- `g2claw calibrate` which way a positive pan turns the camera
- `g2claw pictures`: straight, left, right pictures
- `g2claw test`: one look around
- `g2claw hold`: do the legs hold 20 s
- `g2look wall_straight 12`: one claw-camera picture, labelled, 12 in
- `g2look done`: start the voice service again
- `g2turn3 left`: test the 3-point turn
- `g2send kbalance`: send a raw BiBoard command
- `g2see`: live camera view at localhost:8080
- `g2vision`: print live detections
- `g2walls`: the wall pictures
- `g2wallstats 7`: wall statistics, last 7 days
- `g2wallpic wall_straight 12`: take one wall picture
- `g2wallreplay`: what G2 would do with each wall picture

## Data and review

- `g2sync status` when each copy last worked
- `g2sync run --force all`: copy everything from the Pi now
- `g2sync now goals`: copy one thing (goals, pictures, memorydb, logs...)
- `g2pics`: the review page: pictures, facts, goals
- `g2pics stop`: end the review page
- `g2picscurate`: filter pictures (light, blur, duplicates)
- `g2pimem`: G2's memory on the Pi, in the review page
- `g2pimem search dishwasher`: search his memory as text
- `g2mem 24`: Pi memory use, last 24 h
- `g2membackup`: snapshot the memory database
- `g2data`: sync walk logs and run the quality gates
- `g2cal status`: the calibration snapshots
- `g2calauto`: run the calibration step now
- `g2bg start`: the Mac's 30-minute background jobs
- `g2cmds --board`: what the BiBoard did on its own
- `g2api 24`: API calls and cost, last 24 h
- `g2crash 3`: why the voice service crashed

## Pi power and network

- `g2power plugged`: Pi is on its charger: Wi-Fi power-save stays off
- `g2power unplugged`: Pi is on its battery again
- `g2power status`: power-save, CPU governor, charger
- `g2wifi list`: the Wi-Fi networks the Pi joins
- `g2wifi add HomeNet`: add a network
- `g2deploy --once`: deploy now (no waiting)
- `g2deploy --cancel`: stop a waiting deploy

## Voice and mic

- `g2mic off 30`: wake word off for 30 minutes
- `g2mic on`: wake word back on
- `g2micon`: same as `g2mic on`
- `g2mic status` on or off, time left
- `g2chat`: talk to Claude by typing
- `g2voice`: the voice loop on this Mac
- `g2audio devices`: audio diagnostics

By voice: "G2, mic off for 20 minutes". The review page shows a **Mic on** button while it is off.

## Things to say to G2

Wake with "gee two". The full list: [`voice-commands.md`](voice-commands.md).

- "emergency stop" / "resume": freeze and hold / release
- "gee two, let's talk" / "that's all": talk without the wake word until "that's all"
- "go ahead and look around" / "end exploration mode": start / end exploration
- "come here": walk to the speaker
- "hi step" / "walk normally": switch gait
- "the floor is tile": set the floor label
- "what do you see": describe a picture
- "ball goal" / "punt": start the ball goal / one punt
- "mic off for 20 minutes": wake word off
- "go to sleep" / "shut down": sleep / lie down and shut the Pi down (flip the PiSugar switch by hand)

## A to Z

Every command on this page and in [`cheatsheet-advanced.md`](cheatsheet-advanced.md) (generated; `python tools/gen_cheatsheet_index.py` rewrites it).

<!-- index:start -->
- `g2`: [Setup](cheatsheet-advanced.md#setup)
- `g2api`: [Data and review](#data-and-review)
- `g2app`: [Stop and safety](#stop-and-safety), [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2attach`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2audio`: [Voice and mic](#voice-and-mic)
- `g2auto`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2back`: [Setup](cheatsheet-advanced.md#setup)
- `g2ball`: [Most used](#most-used), [Ball goal and punts](#ball-goal-and-punts)
- `g2ballstop`: [Most used](#most-used), [Ball goal and punts](#ball-goal-and-punts)
- `g2baseline`: [Walk tests](#walk-tests)
- `g2bg`: [Data and review](#data-and-review)
- `g2bringup`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2cal`: [Data and review](#data-and-review)
- `g2calauto`: [Data and review](#data-and-review)
- `g2cam`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2chat`: [Voice and mic](#voice-and-mic)
- `g2check`: [Docs and repo](cheatsheet-advanced.md#docs-and-repo)
- `g2claw`: [Claw and camera](#claw-and-camera)
- `g2clean`: [Docs and repo](cheatsheet-advanced.md#docs-and-repo)
- `g2cmds`: [Data and review](#data-and-review)
- `g2crash`: [Data and review](#data-and-review)
- `g2curate`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2data`: [Data and review](#data-and-review)
- `g2deploy`: [Most used](#most-used), [Pi power and network](#pi-power-and-network)
- `g2diag`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2docs`: [Setup](cheatsheet-advanced.md#setup)
- `g2docsgen`: [Docs and repo](cheatsheet-advanced.md#docs-and-repo)
- `g2doctor`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2eta`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2explore`: [Most used](#most-used), [Stop and safety](#stop-and-safety), [Explore](#explore)
- `g2feat`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2floor`: [Most used](#most-used), [Walk tests](#walk-tests)
- `g2goal`: [Ball goal and punts](#ball-goal-and-punts)
- `g2help`: [Setup](cheatsheet-advanced.md#setup)
- `g2imu`: [Walk tests](#walk-tests)
- `g2libstatus`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2look`: [Claw and camera](#claw-and-camera)
- `g2mem`: [Data and review](#data-and-review)
- `g2membackup`: [Data and review](#data-and-review)
- `g2mic`: [Most used](#most-used), [Voice and mic](#voice-and-mic)
- `g2micon`: [Voice and mic](#voice-and-mic)
- `g2pcam`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2pcam-pull`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2pics`: [Most used](#most-used), [Data and review](#data-and-review)
- `g2picscurate`: [Data and review](#data-and-review)
- `g2pimem`: [Data and review](#data-and-review)
- `g2policy`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2power`: [Pi power and network](#pi-power-and-network)
- `g2preflight`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2promote`: [Camera model](cheatsheet-advanced.md#camera-model)
- `g2punt`: [Ball goal and punts](#ball-goal-and-punts)
- `g2puntset`: [Ball goal and punts](#ball-goal-and-punts)
- `g2puntstop`: [Ball goal and punts](#ball-goal-and-punts)
- `g2reset`: [Most used](#most-used)
- `g2rest`: [Most used](#most-used), [Stop and safety](#stop-and-safety)
- `g2rl`: [Setup](cheatsheet-advanced.md#setup)
- `g2rltest`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2see`: [Claw and camera](#claw-and-camera)
- `g2send`: [Claw and camera](#claw-and-camera)
- `g2serial`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2ssh`: [Most used](#most-used), [Setup](cheatsheet-advanced.md#setup)
- `g2standup`: [Most used](#most-used)
- `g2stop`: [Most used](#most-used), [Stop and safety](#stop-and-safety)
- `g2sync`: [Most used](#most-used), [Data and review](#data-and-review)
- `g2tb`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2test`: [Training and policies](cheatsheet-advanced.md#training-and-policies), [Docs and repo](cheatsheet-advanced.md#docs-and-repo)
- `g2train`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2traits`: [Bring-up and hardware](cheatsheet-advanced.md#bring-up-and-hardware)
- `g2turn3`: [Claw and camera](#claw-and-camera)
- `g2turns`: [Walk tests](#walk-tests)
- `g2vision`: [Claw and camera](#claw-and-camera)
- `g2voice`: [Voice and mic](#voice-and-mic)
- `g2walk`: [Walk tests](#walk-tests)
- `g2walklog`: [Walk tests](#walk-tests)
- `g2wallpic`: [Claw and camera](#claw-and-camera)
- `g2wallreplay`: [Claw and camera](#claw-and-camera)
- `g2walls`: [Claw and camera](#claw-and-camera)
- `g2wallstats`: [Claw and camera](#claw-and-camera)
- `g2watch`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2watchrun`: [Training and policies](cheatsheet-advanced.md#training-and-policies)
- `g2wifi`: [Pi power and network](#pi-power-and-network)
<!-- index:end -->
