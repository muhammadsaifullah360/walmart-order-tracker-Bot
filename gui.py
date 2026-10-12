"""
gui.py -- modern window to run the Walmart status bot without the command line.

Start it with:   python gui.py   (or double-click run.bat)
Settings here override config.py for this run and are saved to settings.json.
"""

import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import scrolledtext, messagebox

import config
import bot

SETTINGS_FILE = os.path.join(bot.app_dir(), "settings.json")

# ---- palettes --------------------------------------------------------------
PALETTES = {
    "dark": {
        "window": "#0f141b", "card": "#161d27", "field": "#0b1016",
        "fg": "#e6edf3", "muted": "#8b98a5", "line": "#263040",
        "log_fg": "#c9d1d9",
        "btn2_bg": "#30363d", "btn2_hover": "#3c444d", "btn2_fg": "#e6edf3",
        "track": "#243040",
    },
    "light": {
        "window": "#eef1f5", "card": "#ffffff", "field": "#ffffff",
        "fg": "#1f2328", "muted": "#59636e", "line": "#d0d7de",
        "log_fg": "#1f2328",
        "btn2_bg": "#e5e7eb", "btn2_hover": "#d6dae0", "btn2_fg": "#1f2328",
        "track": "#d0d7de",
    },
}
GREEN, GREEN_H = "#238636", "#2ea043"
RED, RED_H     = "#da3633", "#f85149"
AMBER, AMBER_H = "#bb8009", "#d29922"
BLUE           = "#2f81f7"
DARKTXT        = "#0f141b"
# status dot colors for the counters
DOT = {"good": "#2ea043", "transit": "#2f81f7", "wait": "#d29922", "bad": "#f85149"}

FONT      = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_H1   = ("Segoe UI Semibold", 16)
MONO      = ("Consolas", 9)


class GuiReporter(bot.Reporter):
    def __init__(self, app):
        self.app = app
        self.log_queue = app.log_queue
        self.stop_event = app.stop_event
        self.human_event = app.human_event
        self.pause_event = app.pause_event

    def log(self, msg, level="info"):
        self.log_queue.put(f"[{level.upper()}] {msg}" if level != "info" else msg)

    def progress(self, done, total, counts):
        self.app.after(0, lambda: self.app.update_progress(done, total, counts))

    def should_pause(self):
        return self.pause_event.is_set()

    def notify_done(self, summary):
        self.log_queue.put(summary)
        self.app.after(0, lambda: self.app.on_done(summary))

    def wait_for_human(self, msg):
        self.log_queue.put("")
        self.log_queue.put("  " + msg)
        self.log_queue.put("  Solve it in the browser, then click 'Continue'.")
        self.human_event.clear()
        self.app.after(0, lambda: self.app.set_waiting(True))
        alarm = bot.SoundAlarm()
        alarm.start()
        try:
            while not self.human_event.is_set():
                if self.stop_event.is_set():
                    break
                self.human_event.wait(timeout=0.3)
        finally:
            alarm.stop()
        self.app.after(0, lambda: self.app.set_waiting(False))
        self.log_queue.put("  Continuing...")

    def should_stop(self):
        return self.stop_event.is_set()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Walmart Order Tracker")
        self.geometry("820x720")
        self.minsize(720, 600)

        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "devorynlabs.walmart.tracker")
        except Exception:
            pass

        self.theme = "dark"
        self.C = PALETTES[self.theme]
        self._themed = []          # [(widget, {option: palette_key})]
        self._icon_img = None

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.human_event = threading.Event()
        self.pause_event = threading.Event()
        self.worker = None
        self._flash_on = False
        self.vars = {}

        self.configure(bg=self.C["window"])
        self._load_icon()
        self._build_banner()
        self._build_header()
        self._build_form()
        self._build_actions()
        self._build_progress()
        self._build_log()
        self._load_settings()
        self.after(150, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- theming ---------------------------------------------------------
    def _reg(self, widget, **rolemap):
        """Register a widget's options to palette keys, and apply now."""
        self._themed.append((widget, rolemap))
        widget.configure(**{opt: self.C[key] for opt, key in rolemap.items()})
        return widget

    def _retheme(self):
        self.C = PALETTES[self.theme]
        self.configure(bg=self.C["window"])
        for widget, rolemap in self._themed:
            try:
                widget.configure(**{opt: self.C[key] for opt, key in rolemap.items()})
            except Exception:
                pass
        self.theme_btn.configure(text=("☀  Light" if self.theme == "dark" else "☽  Dark"))

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self._retheme()

    def _load_icon(self):
        ico = os.path.join(bot.app_dir(), "icon.ico")
        png = os.path.join(bot.app_dir(), "icon.png")
        try:
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        try:
            if os.path.exists(png):
                self._icon_img = tk.PhotoImage(file=png)
                self.iconphoto(True, self._icon_img)
        except Exception:
            self._icon_img = None

    # ---- widget factories ------------------------------------------------
    def _flat_button(self, parent, text, bg, hover, cmd, fg="white"):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=hover, activeforeground=fg,
                      relief="flat", bd=0, font=FONT_BOLD, cursor="hand2",
                      padx=15, pady=8, highlightthickness=0)
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _btn2(self, parent, text, cmd):
        """Secondary (themed) button."""
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bd=0,
                      font=FONT_BOLD, cursor="hand2", padx=14, pady=7,
                      highlightthickness=0)
        self._reg(b, bg="btn2_bg", fg="btn2_fg", activebackground="btn2_hover",
                  activeforeground="btn2_fg")
        b.bind("<Enter>", lambda e: b.configure(bg=self.C["btn2_hover"]))
        b.bind("<Leave>", lambda e: b.configure(bg=self.C["btn2_bg"]))
        return b

    def _entry(self, parent, key, default, width=40):
        v = tk.StringVar(value=str(default))
        e = tk.Entry(parent, textvariable=v, width=width, font=FONT, relief="flat",
                     highlightthickness=1)
        self._reg(e, bg="field", fg="fg", insertbackground="fg",
                  highlightbackground="line", highlightcolor="line")
        self.vars[key] = v
        return e

    # ---- banner ----------------------------------------------------------
    def _build_banner(self):
        self.banner = tk.Label(
            self, text="  ⚠   SOLVE THE CAPTCHA IN THE BROWSER, THEN CLICK CONTINUE   ⚠  ",
            font=("Segoe UI", 12, "bold"), fg="white", bg=RED, height=2)

    def _show_banner(self, show):
        if show:
            self.banner.pack(fill="x", side="top", before=self.header)
            self.lift()
            try:
                self.attributes("-topmost", True)
            except Exception:
                pass
            self._flash()
        else:
            try:
                self.attributes("-topmost", False)
            except Exception:
                pass
            self.banner.pack_forget()

    def _flash(self):
        if not self.banner.winfo_ismapped():
            return
        self._flash_on = not self._flash_on
        self.banner.configure(bg=RED_H if self._flash_on else RED)
        self.after(550, self._flash)

    # ---- header ----------------------------------------------------------
    def _build_header(self):
        self.header = self._reg(tk.Frame(self), bg="window")
        self.header.pack(fill="x", padx=18, pady=(16, 6))
        self._reg(tk.Label(self.header, text="\U0001F916  Walmart Order Tracker",
                           font=FONT_H1), bg="window", fg="fg").pack(side="left")
        self.theme_btn = self._btn2(self.header, "☀  Light", self.toggle_theme)
        self.theme_btn.pack(side="right")
        self.status_dot = self._reg(tk.Label(self.header, text="● Idle", font=FONT_SM),
                                    bg="window", fg="muted")
        self.status_dot.pack(side="right", padx=12)

    # ---- form ------------------------------------------------------------
    def _build_form(self):
        card = tk.Frame(self, highlightthickness=1)
        self._reg(card, bg="card", highlightbackground="line")
        card.pack(fill="x", padx=18, pady=8)
        self.form_frame = card
        inner = self._reg(tk.Frame(card), bg="card")
        inner.pack(fill="x", padx=16, pady=14)

        def lab(parent, text):
            return self._reg(tk.Label(parent, text=text, font=FONT), bg="card", fg="fg")
        def lab_m(parent, text):
            return self._reg(tk.Label(parent, text=text, font=FONT_SM), bg="card", fg="muted")

        lab(inner, "Google Sheet URL or ID").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self._entry(inner, "sheet", config.SPREADSHEET_ID, width=66)\
            .grid(row=1, column=0, columnspan=4, sticky="we", pady=(0, 10))

        lab(inner, "Tab name").grid(row=2, column=0, sticky="w", pady=(0, 2))
        self._entry(inner, "tab", config.TAB_NAME, width=24)\
            .grid(row=3, column=0, sticky="w", pady=(0, 10))

        cols = self._reg(tk.Frame(inner), bg="card")
        cols.grid(row=3, column=1, columnspan=3, sticky="w", padx=(18, 0))
        def mini(lbl, key, dflt, w=4):
            f = self._reg(tk.Frame(cols), bg="card")
            f.pack(side="left", padx=(0, 12))
            lab_m(f, lbl).pack(anchor="w")
            self._entry(f, key, dflt, width=w).pack()
        mini("Header rows", "header", config.HEADER_ROWS, 5)
        mini("Email", "email_col", config.EMAIL_COL)
        mini("Orders", "orders_col", config.ORDERS_COL)
        mini("Status", "status_col", config.STATUS_COL)
        mini("Limit", "limit", 5, 6)
        mini("Skip<h", "skip_hours", getattr(config, "SKIP_IF_CHECKED_WITHIN_HOURS", 0), 5)

        self.dry_run = tk.BooleanVar(value=True)
        cb = tk.Checkbutton(inner, text="  Dry run  (test only — do NOT write to the sheet)",
                            variable=self.dry_run, font=FONT, highlightthickness=0, bd=0)
        self._reg(cb, bg="card", fg="fg", selectcolor="field",
                  activebackground="card", activeforeground="fg")
        cb.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))

        sub = self._reg(tk.Frame(inner), bg="card")
        sub.grid(row=5, column=0, columnspan=4, sticky="w", pady=(12, 0))
        self._btn2(sub, "Save settings", self._save_settings_clicked).pack(side="left")
        self._btn2(sub, "Inspect page", self.inspect).pack(side="left", padx=8)
        self._btn2(sub, "Open sheet", self.open_sheet).pack(side="left")
        self._btn2(sub, "Show problems", self.show_problems).pack(side="left", padx=8)

        inner.grid_columnconfigure(0, weight=1)

    # ---- actions ---------------------------------------------------------
    def _build_actions(self):
        bar = self._reg(tk.Frame(self), bg="window")
        bar.pack(fill="x", padx=18, pady=(4, 6))
        self.start_btn = self._flat_button(bar, "▶  Start", GREEN, GREEN_H,
                                           self.start, fg=DARKTXT)
        self.start_btn.pack(side="left")
        self.pause_btn = self._flat_button(bar, "⏸  Pause", AMBER, AMBER_H,
                                           self.toggle_pause, fg=DARKTXT)
        self.pause_btn.pack(side="left", padx=8)
        self.pause_btn.configure(state="disabled")
        self.stop_btn = self._flat_button(bar, "■  Stop", RED, RED_H,
                                          self.stop, fg=DARKTXT)
        self.stop_btn.pack(side="left")
        self.stop_btn.configure(state="disabled")
        self.continue_btn = self._flat_button(bar, "✔  Continue (captcha solved)",
                                               AMBER, AMBER_H, self.continue_pressed,
                                               fg=DARKTXT)
        self.continue_btn.pack(side="left", padx=8)
        self.continue_btn.configure(state="disabled")
        self._btn2(bar, "ℹ  About", self._show_about).pack(side="right")

    # ---- progress + counters --------------------------------------------
    def _build_progress(self):
        strip = self._reg(tk.Frame(self), bg="window")
        strip.pack(fill="x", padx=18, pady=(2, 2))
        self.pbar = tk.Canvas(strip, height=16, highlightthickness=0, bd=0)
        self._reg(self.pbar, bg="track")
        self.pbar.pack(fill="x", side="top")
        self.pbar.bind("<Configure>", lambda e: self._draw_progress())
        self._progress = (0, 0)

        counts = self._reg(tk.Frame(self), bg="window")
        counts.pack(fill="x", padx=18, pady=(4, 6))
        self.count_labels = {}
        names = [("good", "Delivered"), ("transit", "In transit"),
                 ("wait", "Processing"), ("bad", "Attention")]
        for key, label in names:
            f = self._reg(tk.Frame(counts), bg="window")
            f.pack(side="left", padx=(0, 18))
            tk.Label(f, text="●", fg=DOT[key], font=FONT,
                     bg=self.C["window"]).pack(side="left")
            self._themed.append((f.winfo_children()[0], {"bg": "window"}))
            lbl = self._reg(tk.Label(f, text=f"{label}: 0", font=FONT_SM),
                            bg="window", fg="fg")
            lbl.pack(side="left", padx=(5, 0))
            self.count_labels[key] = (lbl, label)
        self.pct_label = self._reg(tk.Label(counts, text="", font=FONT_SM),
                                   bg="window", fg="muted")
        self.pct_label.pack(side="right")

    def _draw_progress(self):
        self.pbar.delete("all")
        w = self.pbar.winfo_width()
        done, total = self._progress
        frac = (done / total) if total else 0
        self.pbar.create_rectangle(0, 0, max(1, int(w * frac)), 16,
                                   fill=BLUE, width=0)

    def update_progress(self, done, total, counts):
        self._progress = (done, total)
        self._draw_progress()
        self.pct_label.configure(text=f"{done}/{total} rows  ({int(100*done/total) if total else 0}%)")
        for key, (lbl, label) in self.count_labels.items():
            lbl.configure(text=f"{label}: {counts.get(key, 0)}")

    # ---- log -------------------------------------------------------------
    def _build_log(self):
        wrap = self._reg(tk.Frame(self), bg="window")
        wrap.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self._reg(tk.Label(wrap, text="Activity log", font=FONT_SM),
                  bg="window", fg="muted").pack(anchor="w", pady=(0, 4))
        self.log_box = scrolledtext.ScrolledText(
            wrap, wrap="word", state="disabled", font=MONO, relief="flat",
            highlightthickness=1, padx=10, pady=8)
        self._reg(self.log_box, bg="field", fg="log_fg", insertbackground="fg",
                  highlightbackground="line")
        self.log_box.pack(fill="both", expand=True)

    def _write(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _drain_log(self):
        try:
            while True:
                self._write(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(150, self._drain_log)

    def _set_status(self, text, color):
        self.status_dot.configure(text=f"● {text}", fg=color)

    def set_waiting(self, waiting):
        self.continue_btn.configure(state="normal" if waiting else "disabled")
        self._show_banner(waiting)
        if waiting:
            self._set_status("Waiting for captcha", AMBER_H)
        elif self.worker and self.worker.is_alive():
            self._set_status("Running", GREEN_H)

    # ---- settings --------------------------------------------------------
    def _collect_settings(self):
        data = {k: v.get() for k, v in self.vars.items()}
        data["dry_run"] = self.dry_run.get()
        data["theme"] = self.theme
        return data

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        for k, v in self.vars.items():
            if k in data:
                v.set(str(data[k]))
        if "dry_run" in data:
            self.dry_run.set(bool(data["dry_run"]))
        if data.get("theme") in PALETTES and data["theme"] != self.theme:
            self.theme = data["theme"]
            self._retheme()

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._collect_settings(), f, indent=2)
            return True
        except Exception as e:
            self.log_queue.put(f"[ERROR] could not save settings: {e}")
            return False

    def _save_settings_clicked(self):
        if self._save_settings():
            self._write(f"Settings saved to {SETTINGS_FILE}")

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ---- run -------------------------------------------------------------
    def _overrides(self):
        try:
            header = int(self.vars["header"].get() or 0)
            limit = int(self.vars["limit"].get() or 0)
            skip_h = float(self.vars["skip_hours"].get() or 0)
        except ValueError:
            messagebox.showerror("Bad input", "Header rows, Limit and Skip<h must be numbers.")
            return None
        return {
            "SPREADSHEET_ID": self.vars["sheet"].get(),
            "TAB_NAME": self.vars["tab"].get(),
            "FIRST_DATA_ROW": header + 1,
            "EMAIL_COL": self.vars["email_col"].get(),
            "ORDERS_COL": self.vars["orders_col"].get(),
            "STATUS_COL": self.vars["status_col"].get(),
            "LIMIT": limit,
            "SKIP_HOURS": skip_h,
            "DRY_RUN": self.dry_run.get(),
        }

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        overrides = self._overrides()
        if overrides is None:
            return
        self._save_settings()
        self.stop_event.clear()
        self.human_event.clear()
        self.pause_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.pause_btn.configure(state="normal", text="⏸  Pause")
        self.update_progress(0, 0, {})
        self._set_status("Running", GREEN_H)
        self._write("----- starting run -----")

        reporter = GuiReporter(self)

        def job():
            try:
                bot.run_bot(overrides, reporter)
            except Exception as e:
                self.log_queue.put(f"[ERROR] {e}")
            finally:
                self.after(0, self._run_finished)

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _run_finished(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled", text="⏸  Pause")
        self.continue_btn.configure(state="disabled")
        self._set_status("Idle", self.C["muted"])

    def stop(self):
        self.stop_event.set()
        self.human_event.set()
        self.pause_event.clear()
        self._set_status("Stopping...", AMBER_H)
        self._write("----- stop requested; finishing current step -----")

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.configure(text="⏸  Pause")
            self._set_status("Running", GREEN_H)
        else:
            self.pause_event.set()
            self.pause_btn.configure(text="▶  Resume")
            self._set_status("Paused", AMBER_H)

    def continue_pressed(self):
        self.human_event.set()
        self.continue_btn.configure(state="disabled")

    def on_done(self, summary):
        self._set_status("Done", GREEN_H)
        messagebox.showinfo("Run complete", summary)

    def inspect(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Stop the current run before inspecting.")
            return
        self._write("Opening Walmart page for inspection...")
        reporter = GuiReporter(self)

        def job():
            try:
                bot.inspect_page_gui(reporter)
            except Exception as e:
                self.log_queue.put(f"[ERROR] inspect: {e}")

        threading.Thread(target=job, daemon=True).start()

    def open_sheet(self):
        sid = bot.extract_spreadsheet_id(self.vars["sheet"].get())
        if sid:
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sid}/edit")

    def show_problems(self):
        """Read the sheet and list rows whose status needs attention."""
        self._write("Scanning sheet for problem rows...")

        def job():
            try:
                ov = self._overrides() or {}
                settings = {
                    "SPREADSHEET_ID": bot.extract_spreadsheet_id(ov.get("SPREADSHEET_ID", "")),
                    "TAB_NAME": ov.get("TAB_NAME", config.TAB_NAME),
                    "SERVICE_ACCOUNT_FILE": config.SERVICE_ACCOUNT_FILE,
                }
                ws = bot.open_worksheet(settings)
                vals = ws.get_all_values()
                s_idx = bot.col_to_index(ov.get("STATUS_COL", config.STATUS_COL))
                first = ov.get("FIRST_DATA_ROW", config.FIRST_DATA_ROW)
                found = 0
                for r in range(first, len(vals) + 1):
                    row = vals[r - 1]
                    st = row[s_idx].strip() if s_idx < len(row) else ""
                    if st and bot.is_problem(st):
                        self.log_queue.put(f"   row {r}: {st.splitlines()[0]}")
                        found += 1
                self.log_queue.put(f"Found {found} row(s) needing attention."
                                   if found else "No problem rows — all good!")
            except Exception as e:
                self.log_queue.put(f"[ERROR] show problems: {e}")

        threading.Thread(target=job, daemon=True).start()

    # ---- about -----------------------------------------------------------
    def _show_about(self):
        win = tk.Toplevel(self)
        win.title("About")
        win.configure(bg=self.C["card"])
        win.resizable(False, False)
        win.transient(self)
        try:
            if self._icon_img:
                win.iconphoto(False, self._icon_img)
        except Exception:
            pass
        pad = tk.Frame(win, bg=self.C["card"])
        pad.pack(padx=28, pady=24)
        tk.Label(pad, text="\U0001F916  Walmart Order Tracker", bg=self.C["card"],
                 fg=self.C["fg"], font=FONT_H1).pack(anchor="w")
        tk.Label(pad, text="Automated order-status checker", bg=self.C["card"],
                 fg=self.C["muted"], font=FONT_SM).pack(anchor="w", pady=(2, 16))
        tk.Label(pad, text="Built by  Devoryn Labs", bg=self.C["card"],
                 fg=self.C["fg"], font=FONT_BOLD).pack(anchor="w")
        link = tk.Label(pad, text="Muhammad Saif Ullah  —  LinkedIn",
                        bg=self.C["card"], fg=BLUE, font=FONT, cursor="hand2")
        link.pack(anchor="w", pady=(6, 0))
        url = "https://www.linkedin.com/in/muhammad-saif-ullah-0409821b5/"
        link.bind("<Button-1>", lambda e: webbrowser.open(url))
        link.bind("<Enter>", lambda e: link.configure(font=(FONT[0], FONT[1], "underline")))
        link.bind("<Leave>", lambda e: link.configure(font=FONT))
        self._flat_button(pad, "Close", self.C["btn2_bg"], self.C["btn2_hover"],
                          win.destroy, fg=self.C["fg"]).pack(anchor="e", pady=(20, 0))
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + 80
        win.geometry(f"+{max(x,0)}+{max(y,0)}")


if __name__ == "__main__":
    bot.setup_logging()
    App().mainloop()
