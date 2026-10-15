# Recording and recovery

`scripts/Start-Recording.ps1` records High video and audio indefinitely. `-Hours 24`
sets a fixed wall-clock deadline, including outages. `-Quality low` selects the
substream and `-VideoOnly` omits audio. Job metadata is stored in `recordings/jobs/`.

To enforce a known camera resolution, pass `-MinimumResolution 1920x1080`
(Python CLI: `--minimum-resolution 1920x1080`), using your camera's actual dimensions.
Both width and height must meet the minimum; larger frames are accepted. The worker
checks incoming video before saving a new connection. With audio enabled it also
checks every video keyframe before muxing. Smaller video is rejected and the
connection retried, so unavailable target resolution creates a logged recording gap
rather than silently saving lower quality. Existing clips are kept.

Without an explicit minimum, a High job remembers its first successfully received
dimensions as a floor for subsequent connections, including worker restarts. That
first connection alone cannot prove the camera supplied its highest resolution;
use an explicit minimum when it is known. No camera-specific resolution is assumed.
Video-only sessions additionally detect later size changes in decoded preview frames;
some frames can have been saved before such a change is detected.

The dashboard reports **received resolution**, separately from the requested
High/Main or Low/Sub stream. A High request alone does not verify high-resolution
delivery. If incoming video is below the minimum, it shows **Restoring quality**.

Video files are stored under a camera-name directory, grouped by capture start
day in UTC by default. `ICSEE_RECORDING_TIMEZONE` chooses an IANA zone;
the PC's display timezone is not changed. The filename uses the clip-opening
clock in that zone. A clip crossing midnight remains in its starting day's folder.
Tomorrow's folder is prepared ahead of the next cut.

Five-minute clips align to wall-clock boundaries and wait for a camera keyframe,
so the first clip can be shorter and cuts can be a few seconds late. Video is
copied without re-encoding; camera audio is converted to AAC. The browser preview
is silent. Audio currently requires the verified G.711 A-law packet format.

A stopped decoder, missing video/audio for 30 seconds, or low disk space causes
the old connection to close and finalize its clip. The worker refreshes account
authorization and retries with delays up to 60 seconds. It renews a native session
before the SDK's 24-hour limit and reopens a connection on timezone offset changes.
Gaps are logged in `events.jsonl`; live-stream footage during outages is unavailable.

Windows Task Scheduler runs the worker independently of the browser and terminal,
restarts failed workers, and resumes at user login after a reboot. The worker
prevents automatic Windows sleep; deliberate shutdown, sleep, power loss and
internet outages still interrupt capture.

To stop permanently, click **Stop recording** at `http://127.0.0.1:8766/` or run
`scripts/Stop-Recording.ps1`. A durable stop marker prevents resumption, and the
recovery task is removed. The command can fall back to the local job files if the
web server is unavailable. A stuck worker is terminated after 90 seconds, which
can leave its last clip incomplete. Existing clips are preserved.

There is no automatic retention/deletion. Allow approximately 14 GB/day for the
observed main stream with audio, depending on scene activity. Recording pauses
below 2 GB free space and retries when space becomes available.
