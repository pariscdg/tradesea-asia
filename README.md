# TradeSea Asia

Download **TradeSeaAsia.exe** from the [latest release](https://github.com/pariscdg/tradesea-asia/releases/latest). Windows and installed Google Chrome are required; Python is not needed.

1. Put the executable in a permanent, writable folder (for example, a TradeSeaAsia folder under your user folder), then open it.
2. Click **Sign in** and complete login in Chrome.
3. Choose your account categories and click **Save changes**. Save creates or updates the Windows scheduled task for your Windows account and this executable's location. Wait for the scheduling success message.

Keep the executable and its adjacent data files in that folder. If you move the app, open it and Save again to update the task. Your PC must be awake and you must be signed into Windows at the scheduled time; the panel itself can be closed. Missed runs are not replayed. If login expires, sign in through the app again. Scheduling failures are shown explicitly; click Save again after resolving the error.

- Drag accounts into **Asia** or **24-hour** to choose their automated lockout duration.
- Expand **Unallocated accounts** to allocate available accounts. Drop an account back onto this section to remove it from future scheduled runs.
- Each account also has a move dropdown for keyboard use.
- **Save changes** persists allocations and registers the scheduled task; dragging and saving never start a lockout.
- **Settings** controls the Asia duration (12 hours by default). The 24-hour category always uses 24 hours.
- Existing selections are displayed automatically. New accounts remain unallocated after the first category save.
- Active deadlines remain enforced. Changes to an account's duration are blocked while it is locked or its status cannot be verified.
- **Sign in** refreshes the persistent Chrome login; **Refresh** reloads accounts and statuses.

The Windows task `tradesea-asia` still runs Sunday–Thursday at 5:00 PM using the Windows system clock and local time zone (currently Central Time, corresponding to 6:00 PM Eastern). The trigger has no fixed UTC offset, so Windows daylight-saving changes are respected. Both categories use this schedule. A 24-hour assignment is a 24-hour lockout at that run, not a continuously renewed lockout.

`TradeSeaAsia.exe --preview` opens an offline sample panel. `--self-check` checks simulated lockouts without contacting TradeSea. `--run` is used by the scheduled task.

The native panel uses Qt Quick with a transparent window and antialiased rounded edges. It does not use WebView2. Source is in `src/`. Earlier HTML/WebView and Tk UI files are retained as historical references; the active UI is `src/panel.qml` with `src/qt_panel.py`. Live login, saved settings, and deadline records are stored alongside the executable and are excluded from Git.

Build using Python 3.13 with `requirements-build.txt`, then run `build.ps1`. Run regression tests with `python -m unittest discover -s src`.

The glass outline is the native window boundary. Drag the top strip to move the window; use its top-right controls to minimize, maximize/restore, or close. Closing with unsaved allocations asks before discarding them.

For a native rendering check, run `TradeSeaAsia.exe --ui-check`. It opens sample data briefly, verifies that pixels outside all four rounded corners have zero alpha, and records the result in `.asia-ui-check.json`. No live account changes are made.
