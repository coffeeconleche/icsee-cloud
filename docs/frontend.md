# Local camera dashboard

The dashboard at `http://127.0.0.1:8766/` shows the selected camera, live video,
stream quality, saved footage totals, recording progress, and connection health.
It supports phones and desktops, light/dark themes, fullscreen, and snapshots.
There are no remote scripts, fonts, analytics, or CDN dependencies.

## Controls

- **Low / High** selects a stream in live-view sessions. A recording keeps its
  chosen quality, so these controls are disabled while a recording job is present.
- **Camera icon** saves the current preview frame as a PNG through the browser.
- **Expand icon** switches the live image into fullscreen where supported.
- **Silent preview** explains the difference between browser and saved audio.
- **Copy folder path** copies the current day's folder. The files stay on the PC;
  this button does not upload or open the directory.
- **Stop recording / Stop live view** opens a confirmation. Cancel keeps the
  session running. Confirm uses the existing durable stop behavior.
- **Session details** shows video format, preview frame rate, timezone, and
  reconnect count. The theme button remembers a browser-local preference.

The clip timer shows the next approximate wall-clock cut, not an exact file-write
deadline: cuts wait for a camera keyframe. Saved size and clip totals include all
recording days. A disconnected browser does not prove that recording has stopped;
the UI reports the connection as unavailable and keeps retrying status requests.

## Implementation

`frontend.py` serves an explicit allowlist of bundled files from
`src/icsee_cloud/web/`. `index.html`, `app.css`, and `app.js` implement the dashboard
with semantic HTML, local CSS, and browser APIs. Lucide icons are bundled in an SVG
sprite with their license. No JavaScript framework or package installation is
needed to run the Python package.

The UI uses the existing `/status`, `/stream.mjpeg`, `/quality`, and `/stop` APIs.
Camera labels and recording locations come from the local runtime and are rendered
as text; no account, camera, or location is hard-coded in the interface. Controls
remain keyboard accessible, dialogs use the native focus behavior, and reduced
motion is supported. The small-screen navigation is inert when closed.

Static resources are read on request, so edits to the web assets need a browser
refresh. Changes to Python routes need a worker restart. Package data and the
source manifest include the assets; source and wheel installations use the same UI.

## Design and validation tools

The following tools were researched through their official documentation:

- [shadcn MCP](https://ui.shadcn.com/docs/mcp) lets assistants browse, search, and
  install registry components. It is useful for a future React-based interface;
  it is not a dependency of this dashboard.
- [Tailwind with Vite](https://tailwindcss.com/docs/installation/using-vite) is an
  option for a compiled styling workflow. The current CSS works without a build.
- [Lucide](https://lucide.dev/guide/lucide) supplies the bundled interface icons.
- [Playwright](https://playwright.dev/docs/screenshots) supports rendered browser
  checks and screenshots. The dashboard was checked in desktop/mobile layouts,
  both themes, real live video, and simulated connection/control states.

Python HTTP tests cover resource serving, blocked unknown paths, and compatibility
with the existing status and control API. Screenshots, browser downloads, local
tooling, and camera-specific test evidence stay in the ignored research directory.
