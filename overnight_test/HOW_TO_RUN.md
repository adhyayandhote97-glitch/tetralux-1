# Overnight endurance test - how to run (TEMPORARY)

Everything for this test lives in `overnight_test/`. Delete the folder afterwards
(see the revert checklist at the end) and the project is exactly as before.

Always use `/usr/bin/python3`. Plain `python3` is Python 3.14 on this Mac and
has no pyserial or numpy.

## 0. Firmware: nothing to upload

The firmware already on the board sends a `uint32` sequence number (`seq`) and
`millis()` (`ts`) in every packet, which is all the logger needs. So there is
**no test firmware** and nothing to re-flash tomorrow. Checked against the real
board on 2026-11-17: seq is contiguous and `ts` steps by 380 ms.

## 1. Hardware

- Power the Nano **from the Mac over USB**, not from the 18650 battery.
- Plug the Mac into its charger and keep the **lid open**. Closing the lid can
  sleep the Mac even with caffeinate.
- Put the cube where nobody will bump it or the cable.

## 2. Close everything else that uses the USB port

Only one program can read the board. When two try, one of them gets errors and
loses data. Close:

- the dashboard (Ctrl+C in its terminal),
- Arduino IDE (quit it completely),
- the PlatformIO serial monitor in VS Code.

The logger checks this itself and **refuses to start** if anything else has the
port open. It prints the program's name. During the run it re-checks every
minute and logs a `port_shared` event if something grabs the port.

## 3. Start it (two terminals)

Terminal A - keep the Mac awake for the whole night:

```bash
caffeinate -dimsu
```

Terminal B - the logger:

```bash
cd "/Users/adhyayan/Desktop/Victorious Kidss Educares/MYP 5 Caring 3 /Personal Project - Tetralux-1/Code Editing/Tetralux-1/Code_Tetralux-1"
```

```bash
/usr/bin/python3 overnight_test/endurance_log.py --hours 8
```

It finds the board automatically (`/dev/cu.usbmodem*`). Add
`--port /dev/cu.usbmodem1201` to force a specific port. It stops by itself
after 8 h; Ctrl+C stops it earlier and still closes the files cleanly. Every row
is flushed to disk as it arrives, so a crash or power cut loses nothing already
logged.

What you see:

- **Every second:** `seq 2214: sun x=+0.046 y=-0.993 z=+0.112 az= -87.3 el= +6.4`
- **Every 60 s:** `===== STATUS 0h05m | received 790 | bad lines 790 | missing 0 | loss 0.00% | ... temp C 27.25 ... =====`
- `EVENT ...` lines whenever something happens: disconnect, reconnect, no data, board restart.

"bad lines" counts **every** non-packet line. The board currently prints
`[BH1750] Device is not configured!` once per loop, so expect bad lines to be
about the same as received. The analysis separates these status messages from
real broken packets. (That message means one BH1750 never started. The +z
BH1750 reads exactly 0.0 lux all the time, so it is probably that one. It does
not affect the sun estimate, which uses the photodiodes.)

## 4. Check the first 5 minutes

At 5 min the status line should show about **790 received** (2.6 packets/s),
**missing 0**, **loss 0.00%** and six temperatures near room temperature.

For a full mid-run report (safe while the logger is running, since it only
reads the file), use a third terminal:

```bash
cd "/Users/adhyayan/Desktop/Victorious Kidss Educares/MYP 5 Caring 3 /Personal Project - Tetralux-1/Code Editing/Tetralux-1/Code_Tetralux-1"
```

```bash
/usr/bin/python3 overnight_test/analyse_endurance.py "$(ls -t overnight_test/test_logs/endurance_*[0-9].csv | head -1)" --no-charts | head -40
```

To see the last raw rows:

```bash
tail -3 "$(ls -t overnight_test/test_logs/endurance_*[0-9].csv | head -1)"
```

If missing climbs, or you see `disconnect` / `no_data` events, check the cable
before going to bed.

## 5. Pose tags (accuracy and repeatability)

While the logger runs, type a tag in Terminal B and press Enter:

```
P3 az=45 el=0
```

**Put the cube in position first, then press Enter, then hold still for 5 s.**
Typing works even while lines scroll past. The logger prints the result as soon
as the 5 s are up:

```
-> P3 done: 13 frames, error 1.8 deg, std 3.0 deg  (targets <=10 / <=5)
```

Anything that is not a pose (for example `lamp moved`) is saved as a note with
its time.

**What az and el mean.** They give the lamp direction as seen from the cube,
using the cube's own axes (the same as the dashboard):

- `az` is measured around the cube's flat, from +x (0) towards +y (90).
- `el` is measured upwards, towards +z (90).

| Lamp points straight at | Tag |
|---|---|
| +x face (Face 4) | `az=0 el=0` |
| +y face (Face 1) | `az=90 el=0` |
| -x face (Face 6) | `az=180 el=0` |
| -y face (Face 2) | `az=-90 el=0` |
| +z face (Face 3) | `az=0 el=90` |
| -z face (Face 5) | `az=0 el=-90` |
| edge between +x and +y | `az=45 el=0` |
| corner between +x, +y and +z | `az=45 el=35.3` |

Corners (`el=±35.3`) and edges (`el=0`, az a multiple of 45) are exact without
a protractor. Turn the cube so that corner or edge points straight at the lamp.

A 15-pose set for the accuracy criterion:

- the 6 faces;
- 4 edges: az = 45, 135, -135 and -45, all at el = 0;
- 4 top corners: the same four az values at el = 35.3;
- 1 bottom corner: `az=45 el=-35.3`.

For repeatability, repeat poses with the same ID (P1 again, P1 again ...). The
analysis lists every repeat.

Tips:

- Use a dark room and a single lamp at least 1 m away.
- Keep your hand and body out of the light while the 5 s run.
- Do the poses in the first hour, then leave the cube still for the rest of the
  night.

## 6. In the morning

Ctrl+C in Terminal B if it is still running, and in Terminal A. Then:

```bash
/usr/bin/python3 overnight_test/analyse_endurance.py "$(ls -t overnight_test/test_logs/endurance_*[0-9].csv | head -1)"
```

It writes into `overnight_test/test_logs/`:

- `<stem>_summary.md` - criteria table, gaps, intervals, temperatures, downtime, poses
- `<stem>_gaps.csv`, `<stem>_buckets.csv`, `<stem>_poses.csv` - tables for the report
- `<stem>_loss.png`, `<stem>_intervals.png`, `<stem>_temperature.png` - charts.
  These need matplotlib, which is not installed yet; without it the charts are
  skipped and everything else still works.

Tests for the maths:

```bash
/usr/bin/python3 -m pytest overnight_test/test_endurance_maths.py -q
```

## Revert checklist (tomorrow)

1. **Keep the data:** copy `overnight_test/test_logs/` somewhere outside the
   repo, e.g. the Personal Project folder.
2. Delete the test folder:

   ```bash
   rm -rf overnight_test
   ```

3. Go back to your branch and delete the test branch:

   ```bash
   git checkout main
   ```

   ```bash
   git branch -D overnight-test
   ```

4. `git status` should print nothing to commit.
5. **Firmware:** nothing to re-flash. No test firmware was made, and the board
   still runs your normal firmware. If you flashed anything else in the
   meantime, re-upload `firmware/` with PlatformIO.
6. Optional: before the test, your uncommitted firmware changes were saved as
   commit `c5abacb` ("Snapshot before overnight endurance test") on `main`. To
   turn them back into uncommitted changes, run this on main:

   ```bash
   git reset --soft HEAD~1
   ```
