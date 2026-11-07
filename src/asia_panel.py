"""Small local panel. Opening or saving this window never applies a lockout."""
from datetime import datetime
import json
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

from asia_settings import account_key, identity, is_lucid, label, resolve_accounts
from tradesea_lockout import DURATIONS


def schedule_status():
    command = "$t = Get-ScheduledTask -TaskName 'tradesea-asia' -ErrorAction SilentlyContinue; if ($t) { " \
              "$i = $t | Get-ScheduledTaskInfo; @{enabled=($t.State -ne 'Disabled'); next=$i.NextRunTime.ToString('s')} | ConvertTo-Json -Compress }"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        value = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
        if value and value["enabled"]:
            return "Next run: " + datetime.fromisoformat(value["next"]).strftime("%a, %b %d at %I:%M %p").replace(" 0", " ")
        return "Scheduled task is disabled" if value else "Scheduled task is not installed"
    except Exception:
        return "Schedule status unavailable"


class AsiaPanel:
    def __init__(self, root, service, read_schedule=schedule_status, auto_load=True):
        self.root, self.service, self.read_schedule = root, service, read_schedule
        self.accounts, self.statuses, self.selected = [], {}, set()
        self.settings = service.repo.settings()
        self.mode = self.settings["mode"]
        self.busy, self.loaded, self.closed = False, False, False
        self.events = queue.Queue()
        self.duration_labels = {f"{s // 3600} hour" + ("s" if s != 3600 else ""): s for s in DURATIONS}
        self.duration = tk.StringVar(value=self.duration_label(self.settings["durationSeconds"]))
        root.title("TradeSea Asia")
        root.geometry("440x575")
        root.resizable(False, False)
        root.configure(bg="#f4f6f8")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6f8")
        style.configure("TLabel", background="#f4f6f8", foreground="#253342", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground="#687787", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground="#172b3b")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 7))
        style.configure("Primary.TButton", background="#215e86", foreground="white", font=("Segoe UI Semibold", 11), padding=(12, 11))
        style.map("Primary.TButton", background=[("disabled", "#d9e0e6"), ("active", "#174b6b")], foreground=[("disabled", "#87939f")])
        style.configure("TCombobox", padding=8, font=("Segoe UI", 11))
        style.map("TCombobox", fieldbackground=[("disabled", "#e2e6eb"), ("readonly", "white")], foreground=[("disabled", "#8a949d")])
        frame = ttk.Frame(root, padding=(24, 20))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="TRADESEA", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Asia lockout", style="Title.TLabel").pack(anchor="w", pady=(2, 12))
        connection = ttk.Frame(frame)
        connection.pack(fill="x")
        self.login_status = ttk.Label(connection, text="Connecting saved login…", style="Muted.TLabel")
        self.login_status.pack(side="left")
        self.refresh_button = ttk.Button(connection, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="right")
        self.login_button = ttk.Button(connection, text="Sign in", command=lambda: self.refresh(True))
        self.login_button.pack(side="right", padx=(0, 6))
        ttk.Separator(frame).pack(fill="x", pady=14)
        ttk.Label(frame, text="Accounts", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        self.account_button = ttk.Button(frame, text="Loading accounts…", command=self.show_accounts)
        self.account_button.pack(fill="x", pady=(5, 4))
        self.account_note = ttk.Label(frame, text="All Lucid accounts selected by default.", style="Muted.TLabel")
        self.account_note.pack(anchor="w")
        duration_row = ttk.Frame(frame)
        duration_row.pack(fill="x", pady=(15, 5))
        ttk.Label(duration_row, text="Lockout duration", font=("Segoe UI Semibold", 10)).pack(side="left")
        self.duration_box = ttk.Combobox(duration_row, textvariable=self.duration, values=list(self.duration_labels),
                                         width=11, state="disabled")
        self.duration_box.pack(side="right")
        self.lock_note = ttk.Label(frame, text="Checking lockout status…", style="Muted.TLabel", wraplength=390)
        self.lock_note.pack(anchor="w", fill="x", pady=(3, 9))
        ttk.Separator(frame).pack(fill="x", pady=(3, 10))
        ttk.Label(frame, text="SUNDAY–THURSDAY · 5:00 PM", font=("Segoe UI Semibold", 10)).pack(anchor="w")
        self.schedule_note = ttk.Label(frame, text="Checking scheduled task…", style="Muted.TLabel")
        self.schedule_note.pack(anchor="w", pady=(3, 2))
        self.last_run = ttk.Label(frame, text="The task uses your saved selection and duration.", style="Muted.TLabel", wraplength=390)
        self.last_run.pack(anchor="w")
        self.save_button = ttk.Button(frame, text="Save for scheduled run", style="Primary.TButton", command=self.save)
        self.save_button.pack(fill="x", pady=(16, 7))
        self.message = ttk.Label(frame, text="Saving applies to the next scheduled run.", style="Muted.TLabel", wraplength=390)
        self.message.pack(anchor="w", fill="x")
        self.render()
        root.after(100, self.poll)
        if auto_load:
            root.after(150, self.refresh)

    def duration_label(self, seconds):
        return next(name for name, duration in self.duration_labels.items() if seconds == duration)

    def close(self):
        self.closed = True
        self.root.destroy()

    def work(self, action, success):
        if self.busy:
            return
        self.busy = True
        self.render()
        def run():
            try:
                self.events.put((success, action(), None))
            except Exception as exc:
                self.events.put((success, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            success, value, error = self.events.get_nowait()
            self.busy = False
            if error:
                self.loaded = False
                self.login_status.configure(text="Connection needs attention")
                self.message.configure(text=error, foreground="#9b5522")
            else:
                success(value)
            self.render()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def refresh(self, interactive=False):
        self.message.configure(text="Sign in in the Chrome window." if interactive else "Refreshing saved login and account status…", foreground="#687787")
        def action():
            result = self.service.load(interactive)
            result["schedule"] = self.read_schedule()
            return result
        self.work(action, self.loaded_result)

    def loaded_result(self, result):
        self.accounts, self.statuses, self.settings = result["accounts"], result["statuses"], result["settings"]
        self.mode = self.settings["mode"]
        selected, missing = resolve_accounts(self.settings, self.accounts)
        self.selected = {account_key(account) for account in selected}
        self.duration.set(self.duration_label(self.settings["durationSeconds"]))
        self.loaded = True
        self.login_status.configure(text="Saved login connected", foreground="#267154")
        if "schedule" in result:
            self.schedule_note.configure(text=result["schedule"])
        last = result.get("lastRun")
        if last:
            count = sum(bool(item.get("ok")) for item in last.get("results", []))
            self.last_run.configure(text=f"Last run: {count} of {len(last.get('results', []))} accounts confirmed." if last.get("results") else "Last run needs attention. Refresh the saved login.")
        self.message.configure(text="A saved account is unavailable. Review the selection." if missing else "Settings loaded. Changes apply to the next scheduled run.", foreground="#687787")

    def render(self):
        enabled = self.loaded and not self.busy
        self.account_button.configure(state="normal" if enabled else "disabled")
        for button in (self.refresh_button, self.login_button):
            button.configure(state="disabled" if self.busy else "normal")
        self.save_button.configure(state="normal" if enabled and self.selected else "disabled")
        selected_status = [self.statuses.get(key, {"locked": True, "verified": False}) for key in self.selected]
        locked = [status for status in selected_status if status["locked"]]
        if locked:
            self.duration.set(self.duration_label(self.settings["durationSeconds"]))
        self.duration_box.configure(state="readonly" if enabled and self.selected and not locked else "disabled")
        if self.loaded:
            title = "All Lucid accounts" if self.mode == "all-lucid" else "Selected accounts"
            self.account_button.configure(text=f"{title} · {len(self.selected)} selected   ▾")
            self.account_note.configure(text="New Lucid accounts are included automatically." if self.mode == "all-lucid" else "Only these accounts will be used by the task.")
        if any(not status.get("verified") for status in selected_status):
            note = "Duration unavailable until selected account status can be verified."
        elif locked:
            ends = [status["end"] for status in locked if status.get("end")]
            note = f"{len(locked)} selected account(s) locked. Duration is fixed"
            note += " until " + datetime.fromtimestamp(max(ends)).strftime("%b %d, %I:%M %p").replace(" 0", " ") + "." if ends else "."
        else:
            note = "Choose the duration before a lockout starts." if self.selected else "Choose at least one account."
        self.lock_note.configure(text=note)

    def select_all_lucid(self):
        self.mode = "all-lucid"
        self.selected = {account_key(account) for account in self.accounts if is_lucid(account)}
        self.render()

    def toggle(self, key):
        self.mode = "selected"
        if key in self.selected:
            self.selected.remove(key)
        else:
            self.selected.add(key)
        self.render()

    def show_accounts(self):
        if self.busy or not self.loaded:
            return
        menu = tk.Menu(self.root, tearoff=False, font=("Segoe UI", 10))
        menu.add_command(label="Select all Lucid accounts", command=self.select_all_lucid)
        menu.add_separator()
        self.menu_vars = []
        for account in self.accounts:
            key = account_key(account)
            status = self.statuses.get(key, {})
            suffix = " · Status unavailable" if not status.get("verified") else " · Locked" if status.get("locked") else ""
            var = tk.BooleanVar(value=key in self.selected)
            self.menu_vars.append(var)
            menu.add_checkbutton(label=label(account) + suffix, variable=var, command=lambda k=key: self.toggle(k))
        try:
            menu.tk_popup(self.account_button.winfo_rootx(), self.account_button.winfo_rooty() + self.account_button.winfo_height())
        finally:
            menu.grab_release()

    def save(self):
        if self.busy or not self.loaded or not self.selected:
            return
        settings = {"version": 1, "mode": self.mode, "durationSeconds": self.duration_labels[self.duration.get()],
                    "accounts": [identity(a) for a in self.accounts if account_key(a) in self.selected]}
        self.message.configure(text="Verifying lockouts and saving settings…", foreground="#687787")
        def done(result):
            self.loaded_result(result)
            self.message.configure(text="Saved. The scheduled task will use these settings.", foreground="#267154")
        self.work(lambda: self.service.save(settings), done)


def show_panel(service):
    root = tk.Tk()
    try:
        AsiaPanel(root, service)
    except Exception as exc:
        from tkinter import messagebox
        messagebox.showerror("TradeSea Asia", str(exc), parent=root)
        root.destroy()
        return 1
    root.mainloop()
    return 0
