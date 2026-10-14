# Recording and recovery

`scripts/Start-Recording.ps1` records High video and audio indefinitely. `-Hours 24`
sets a fixed wall-clock deadline, including outages. `-Quality low` selects the
substream and `-VideoOnly` omits audio. Job metadata is stored in `recordings/jobs/`.

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
