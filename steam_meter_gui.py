"""
Steam Meter GUI — Desktop launcher for non-technical users
Run with: python steam_meter_gui.py
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import subprocess
import sys
import os
from pathlib import Path
import re

# ── Theme colors ───────────────────────────────────────────────────────────────
BG        = "#13111e"
PANEL     = "#1e1b2e"
ACCENT    = "#8b5cf6"
ACCENT2   = "#a78bfa"
SUCCESS   = "#6ee7b7"
WARNING   = "#fcd34d"
DANGER    = "#f87171"
TEXT      = "#ede9fe"
TEXT_DIM  = "#6b6893"
BORDER    = "#2d2845"
INPUT_BG  = "#0d0b17"

FONT_TITLE  = ("Avenir Next", 22, "bold")
FONT_LABEL  = ("Avenir Next", 11)
FONT_SMALL  = ("Avenir Next", 9)
FONT_MONO   = ("Menlo", 9)
FONT_BTN    = ("Avenir Next", 11, "bold")
FONT_HEADER = ("Avenir Next", 13, "bold")


class GlowButton(tk.Canvas):
    """
    Canvas button replicating the CSS radial-glow + grid pattern effect.
    Colors: rgba(46,213,115) green on dark background.
    Hover shrinks the grid (15px → 10px). Disabled dims everything.
    """
    _MAIN  = "#2ed573"            # rgb(46,213,115)
    _GRID  = "#151f24"            # rgba(46,213,116,0.073) blended over BG #13111e
    _BG    = (0x13, 0x11, 0x1e)  # BG decomposed
    _CTR   = (0x1d, 0x58, 0x3d)  # rgba(46,213,116,0.36) blended over BG
    _DIM   = (0x20, 0x1e, 0x30)  # disabled center glow (neutral)

    def __init__(self, parent, text, command, height=52, font=None, **kw):
        super().__init__(parent, height=height, width=1, bg=BG,
                         highlightthickness=0, cursor="hand2", **kw)
        self._text    = text
        self._command = command
        self._font    = font or ("Avenir Next", 13, "bold")
        self._grid_sz = 15
        self._enabled = True

        self.bind("<Configure>",       lambda _: self._redraw())
        self.bind("<Enter>",           lambda _: self._hover(True))
        self.bind("<Leave>",           lambda _: self._hover(False))
        self.bind("<Button-1>",        lambda _: self._click())
        self.bind("<ButtonRelease-1>", lambda _: self._redraw())

    def configure(self, **kw):
        changed = False
        if "state" in kw:
            self._enabled = (kw.pop("state") == "normal")
            changed = True
        if "text" in kw:
            self._text = kw.pop("text")
            changed = True
        if kw:
            super().configure(**kw)
        if changed:
            self._redraw()

    config = configure

    def _hover(self, entering):
        if self._enabled:
            self._grid_sz = 10 if entering else 15
            self._redraw()

    def _click(self):
        if self._enabled and self._command:
            self._command()

    def _redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            self.after(20, self._redraw)
            return
        cx, cy = w // 2, h // 2

        # ── Base fill ──
        self.create_rectangle(0, 0, w, h, fill=BG, outline="")

        # ── Radial glow: concentric ovals from outer/BG → inner/green ──
        br, bg_c, bb = self._BG
        cr, cg, cb   = self._CTR if self._enabled else self._DIM
        steps = 20
        for i in range(steps):
            t  = i / (steps - 1)          # 0 = outer (BG), 1 = inner (glow)
            rx = cx * (1.0 - t)
            ry = cy * (1.0 - t)
            r  = int(br + (cr - br) * t)
            g  = int(bg_c + (cg - bg_c) * t)
            b  = int(bb + (cb - bb) * t)
            self.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                             fill=f"#{r:02x}{g:02x}{b:02x}", outline="")

        # ── Grid pattern ──
        gs = self._grid_sz
        for x in range(0, w + gs, gs):
            self.create_line(x, 0, x, h, fill=self._GRID, width=1)
        for y in range(0, h + gs, gs):
            self.create_line(0, y, w, y, fill=self._GRID, width=1)

        # ── Top / bottom gradient border (bright centre → transparent edges) ──
        segs = 40
        mr, mg, mb = (0x2e, 0xd5, 0x73) if self._enabled else (0x4a, 0x47, 0x70)
        for i in range(segs):
            x0 = int(w * i / segs)
            x1 = int(w * (i + 1) / segs)
            d  = abs((i + 0.5) / segs - 0.5) * 2   # 0=centre, 1=edge
            a  = max(0.0, 1.0 - d ** 0.7)
            rc = int(mr * a + br * (1 - a))
            gc = int(mg * a + bg_c * (1 - a))
            bc = int(mb * a + bb * (1 - a))
            brd = f"#{rc:02x}{gc:02x}{bc:02x}"
            self.create_line(x0, 0,   x1, 0,   fill=brd, width=2)
            self.create_line(x0, h-1, x1, h-1, fill=brd, width=2)

        # ── Text ──
        color = self._MAIN if self._enabled else "#4a4770"
        self.create_text(cx, cy, text=self._text.upper(),
                         fill=color, font=self._font, anchor="center")


class SteamMeterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Steam Meter Extractor")
        self.geometry("720x780")
        self.minsize(660, 700)
        self.configure(bg=BG)
        self.resizable(True, True)

        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 720) // 2
        y = (self.winfo_screenheight() - 780) // 2
        self.geometry(f"720x780+{x}+{y}")

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=PANEL, pady=0)
        header.pack(fill="x")

        # Accent stripe
        stripe = tk.Frame(header, bg=ACCENT, height=3)
        stripe.pack(fill="x")

        inner = tk.Frame(header, bg=PANEL, padx=32, pady=20)
        inner.pack(fill="x")

        tk.Label(inner, text="Steam Meter Extractor",
                 font=FONT_TITLE, bg=PANEL, fg=TEXT).pack(anchor="w")
        tk.Label(inner, text="Automatically reads meter values from security camera images using AI",
                 font=FONT_SMALL, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", pady=(4, 0))

        # ── Body ──
        body = tk.Frame(self, bg=BG, padx=32, pady=24)
        body.pack(fill="both", expand=True)

        # Step 1 — Image Folder
        self._section(body, "1", "Image Folder", "Select the folder containing your .jpg meter photos")
        row1 = tk.Frame(body, bg=BG)
        row1.pack(fill="x", pady=(6, 16))

        self.folder_var = tk.StringVar()
        f1 = self._entry(row1, self.folder_var, placeholder="No folder selected...")
        f1.pack(side="left", fill="x", expand=True)
        self.folder_entry = f1.winfo_children()[0]
        self._btn(row1, "Browse", self._browse_folder,
                  bg=PANEL, fg=ACCENT2, padx=14).pack(side="left", padx=(8, 0))

        # Step 2 — API Key
        self._section(body, "2", "Gemini API Key",
                      "Paste your key from aistudio.google.com → Get API Key")
        row2 = tk.Frame(body, bg=BG)
        row2.pack(fill="x", pady=(6, 16))

        self.key_var = tk.StringVar()
        self.key_entry = self._entry(row2, self.key_var, show="•",
                                     placeholder="AIza...")
        self.key_entry.pack(side="left", fill="x", expand=True)

        self.show_key = tk.BooleanVar(value=False)
        tk.Checkbutton(row2, text="Show", variable=self.show_key,
                       command=self._toggle_key,
                       bg=BG, fg=TEXT_DIM, selectcolor=PANEL,
                       activebackground=BG, font=FONT_SMALL,
                       relief="flat", bd=0).pack(side="left", padx=(8, 0))

        # Step 3 — Output File
        self._section(body, "3", "Output Excel File",
                      "Where to save the results spreadsheet")
        row3 = tk.Frame(body, bg=BG)
        row3.pack(fill="x", pady=(6, 16))

        self.output_var = tk.StringVar(value="steam_results.xlsx")
        f3 = self._entry(row3, self.output_var)
        f3.pack(side="left", fill="x", expand=True)
        self.output_entry = f3.winfo_children()[0]
        self._btn(row3, "Browse", self._browse_output,
                  bg=PANEL, fg=ACCENT2, padx=14).pack(side="left", padx=(8, 0))

        # ── Divider ──
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=8)

        # ── Run / Stop Buttons ──
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", pady=(8, 0))

        self.run_btn = GlowButton(btn_row, "▶  Run Extraction", self._run,
                                  height=52, font=("Avenir Next", 13, "bold"))
        self.run_btn.pack(side="left", fill="x", expand=True)

        self.stop_btn = tk.Button(btn_row, text="■  Stop", command=self._stop,
                                  bg="#2d1a1a", fg=DANGER, font=FONT_BTN,
                                  relief="flat", bd=0, padx=20, pady=12,
                                  cursor="hand2", activebackground=DANGER,
                                  activeforeground="white", state="disabled",
                                  disabledforeground="#4a3030")
        self.stop_btn.bind("<Enter>", lambda _: self.stop_btn.config(bg=DANGER, fg="white")
                           if self.stop_btn["state"] == "normal" else None)
        self.stop_btn.bind("<Leave>", lambda _: self.stop_btn.config(bg="#2d1a1a", fg=DANGER))
        self.stop_btn.pack(side="left", padx=(8, 0))

        # ── Progress ──
        prog_frame = tk.Frame(body, bg=BG)
        prog_frame.pack(fill="x", pady=(12, 0))

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = tk.Label(prog_frame, textvariable=self.status_var,
                                   font=FONT_SMALL, bg=BG, fg=TEXT_DIM, anchor="w")
        self.status_lbl.pack(fill="x")

        self.progress = ttk.Progressbar(prog_frame, mode="indeterminate", length=300)
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", troughcolor=PANEL,
                        background=ACCENT, thickness=4)
        self.progress.pack(fill="x", pady=(4, 0))

        # ── Log Console ──
        log_header = tk.Frame(body, bg=BG)
        log_header.pack(fill="x", pady=(16, 4))
        tk.Label(log_header, text="Log", font=FONT_HEADER,
                 bg=BG, fg=TEXT).pack(side="left")
        self._btn(log_header, "Clear", self._clear_log,
                  bg=PANEL, fg=TEXT_DIM, padx=10, pady=2,
                  font=FONT_SMALL).pack(side="right")

        log_frame = tk.Frame(body, bg=BORDER, padx=1, pady=1)
        log_frame.pack(fill="both", expand=True)

        inner_log = tk.Frame(log_frame, bg=INPUT_BG)
        inner_log.pack(fill="both", expand=True)

        self.log = tk.Text(inner_log, bg=INPUT_BG, fg=TEXT, font=FONT_MONO,
                           relief="flat", bd=0, wrap="word",
                           padx=12, pady=10, state="disabled",
                           insertbackground=TEXT)
        scrollbar = tk.Scrollbar(inner_log, command=self.log.yview,
                                 bg=PANEL, troughcolor=INPUT_BG,
                                 activebackground=ACCENT)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        # Tag colors for log
        self.log.tag_config("ok",      foreground="#6ee7b7")  # pastel mint
        self.log.tag_config("warn",    foreground="#fcd34d")  # pastel yellow
        self.log.tag_config("err",     foreground="#f87171")  # pastel rose
        self.log.tag_config("info",    foreground="#c4b5fd")  # pastel lavender
        self.log.tag_config("dim",     foreground="#4a4770")  # muted purple
        self.log.tag_config("default", foreground="#ede9fe")  # warm white

        self._log("Steam Meter Extractor ready. Fill in the fields above and click Run.\n", "dim")

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _section(self, parent, number, title, subtitle):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(4, 0))
        badge = tk.Label(f, text=number, font=("Avenir Next", 9, "bold"),
                         bg=ACCENT, fg="white", width=2, padx=4, pady=1)
        badge.pack(side="left", padx=(0, 8))
        tk.Label(f, text=title, font=FONT_HEADER,
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(f, text=f"  —  {subtitle}", font=FONT_SMALL,
                 bg=BG, fg=TEXT_DIM).pack(side="left")

    def _entry(self, parent, var, show=None, placeholder=None):
        frame = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        e = tk.Entry(frame, textvariable=var, font=FONT_LABEL,
                     bg=INPUT_BG, fg=TEXT, relief="flat", bd=0,
                     insertbackground=TEXT, highlightthickness=0)
        if show:
            e.config(show=show)
        e.pack(fill="x", padx=8, pady=6)
        return frame

    def _btn(self, parent, text, cmd, bg=ACCENT, fg="white",
             padx=20, pady=8, font=FONT_LABEL):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, font=font,
                      relief="flat", bd=0, padx=padx, pady=pady,
                      cursor="hand2", activebackground=ACCENT2,
                      activeforeground="white")
        b.bind("<Enter>", lambda e: b.config(bg=ACCENT2 if bg == ACCENT else ACCENT))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    # ── Actions ────────────────────────────────────────────────────────────────

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select folder of meter images")
        if d:
            self.folder_var.set(d)
            suggested = str(Path(d).parent / "steam_results.xlsx")
            self.output_var.set(suggested)
            self.folder_entry.xview_moveto(1)
            self.output_entry.xview_moveto(1)

    def _browse_output(self):
        f = filedialog.asksaveasfilename(
            title="Save Excel output as",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        if f:
            self.output_var.set(f)
            self.output_entry.xview_moveto(1)

    def _toggle_key(self):
        self.key_entry.winfo_children()[0].config(
            show="" if self.show_key.get() else "•")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _log(self, msg, tag="default"):
        self.log.config(state="normal")
        self.log.insert("end", msg, tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def _set_status(self, text, color=TEXT_DIM):
        self.status_var.set(text)
        self.status_lbl.config(fg=color)

    # ── Stop ───────────────────────────────────────────────────────────────────

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.stop_btn.config(state="disabled")
        self.run_btn.config(state="normal", text="▶  Run Extraction")
        self.progress.stop()
        self._set_status("⏹  Stopped by user", WARNING)
        self._log("\n⏹  Extraction stopped by user.\n", "warn")

    # ── Run ────────────────────────────────────────────────────────────────────

    def _run(self):
        folder = self.folder_var.get().strip()
        api_key = self.key_var.get().strip()
        output  = self.output_var.get().strip()

        # Validation
        if not folder:
            messagebox.showerror("Missing Input", "Please select an image folder.")
            return
        if not Path(folder).is_dir():
            messagebox.showerror("Invalid Folder", f"Folder not found:\n{folder}")
            return
        if not api_key:
            messagebox.showerror("Missing API Key", "Please enter your Gemini API key.")
            return
        if not output:
            messagebox.showerror("Missing Output", "Please specify an output file path.")
            return

        # Find steam_meter.py next to this GUI script
        script = Path(__file__).parent / "ImageRecognitionTool.py"
        if not script.exists():
            messagebox.showerror(
                "Script Not Found",
                f"steam_meter.py not found in:\n{script.parent}\n\n"
                "Make sure steam_meter.py is in the same folder as this GUI."
            )
            return

        self._proc = None
        self.run_btn.config(state="disabled", text="Running...")
        self.stop_btn.config(state="normal")
        self.progress.start(12)
        self._set_status("Running extraction...", ACCENT2)
        self._log(f"\n{'─'*60}\n", "dim")
        self._log(f"📁 Folder : {folder}\n", "info")
        self._log(f"📊 Output : {output}\n", "info")
        self._log(f"{'─'*60}\n\n", "dim")

        threading.Thread(target=self._run_thread,
                         args=(script, folder, api_key, output),
                         daemon=True).start()

    def _run_thread(self, script, folder, api_key, output):
        cmd = [sys.executable, "-u", str(script),
               "--input",   folder,
               "--api-key", api_key,
               "--output",  output]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self._proc = proc

            ok_re      = re.compile(r"✓\s*\[OK")
            warn_re    = re.compile(r"\?\s*\[YELLOW")
            err_re     = re.compile(r"✗\s*\[RED")
            ts_re      = re.compile(r"\[\s*\d+/\d+\]")
            total_re   = re.compile(r"Processing (\d+) images")
            summary_re = re.compile(r"(^Summary|^===|Total\s*:|✅|🟡|🔴|^Saved|^  Output)")
            info_re    = re.compile(r"^(Connecting|Ready\.|Reading)")
            noise_re   = re.compile(r"^(WARNING|UserWarning|DeprecationWarning|urllib|requests\.|  File )")

            total_images = 0
            processed    = 0

            for line in proc.stdout:
                stripped = line.strip()
                if not stripped or noise_re.search(stripped):
                    continue

                # Grab total image count from "Ready. Processing N images..." line
                if not total_images:
                    m = total_re.search(stripped)
                    if m:
                        total_images = int(m.group(1))

                if ok_re.search(line):
                    processed += 1
                    self.after(0, self._log, line, "ok")
                    self.after(0, self._set_status,
                               f"Image {processed} of {total_images} — reading meter values...", ACCENT2)
                elif warn_re.search(line):
                    processed += 1
                    self.after(0, self._log, line, "warn")
                    self.after(0, self._set_status,
                               f"Image {processed} of {total_images} — reading meter values...", ACCENT2)
                elif err_re.search(line):
                    processed += 1
                    self.after(0, self._log, line, "err")
                    self.after(0, self._set_status,
                               f"Image {processed} of {total_images} — reading meter values...", ACCENT2)
                elif ts_re.search(line):
                    self.after(0, self._log, line, "dim")
                elif summary_re.search(stripped):
                    self.after(0, self._log, line, "info")
                elif info_re.search(stripped):
                    self.after(0, self._log, line, "info")

            proc.wait()
            success = proc.returncode == 0

            def finish():
                self.progress.stop()
                self.stop_btn.config(state="disabled")
                self.run_btn.config(state="normal", text="▶  Run Extraction")
                if success:
                    self._set_status(f"✅  Done — {processed} images processed", SUCCESS)
                    self._log(f"\n✅  Done! Results saved to:\n    {output}\n", "ok")
                    messagebox.showinfo("Complete",
                        f"Extraction finished!\n\nResults saved to:\n{output}")
                else:
                    self._set_status("❌  Extraction failed — see log for details", DANGER)
                    self._log("\n❌  Process exited with errors. Check the log above.\n", "err")

            self.after(0, finish)

        except Exception as ex:
            def err_finish():
                self.progress.stop()
                self.stop_btn.config(state="disabled")
                self.run_btn.config(state="normal", text="▶  Run Extraction")
                self._set_status("❌  Error", DANGER)
                self._log(f"\n❌  Unexpected error: {ex}\n", "err")
            self.after(0, err_finish)


if __name__ == "__main__":
    app = SteamMeterApp()
    app.mainloop()