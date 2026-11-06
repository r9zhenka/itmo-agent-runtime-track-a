"""Tk is included in Python distributions; Linux may require python3-tk."""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from runtime.common import Fault
from .api import Client, validate_workspace


def launch(server, token, workspace_root):
    root = tk.Tk()
    root.title("Project A — Checkpoint 1")
    root.geometry("900x650")
    root.minsize(700, 500)
    root.columnconfigure(0, weight=1)
    # Only the activity area grows/shrinks; reserve space for the message controls.
    root.rowconfigure(2, weight=1)
    default_folder = "demo" if workspace_root and (Path(workspace_root) / "demo").is_dir() else ""
    values = {"server": tk.StringVar(value=server), "token": tk.StringVar(value=token),
              "folder": tk.StringVar(value=default_folder), "mode": tk.StringVar(value="rw")}
    state = {"client": None, "session": None, "run": None, "cursor": 0, "watching": False, "connecting": False}
    messages = queue.Queue()
    top = ttk.Frame(root, padding=12)
    top.grid(row=0, column=0, sticky="ew")
    for row, label in enumerate(("server", "token", "folder")):
        ttk.Label(top, text=label.capitalize()).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(top, textvariable=values[label], width=80,
                  show="*" if label == "token" else "").grid(row=row, column=1, sticky="ew", padx=6)
    top.columnconfigure(1, weight=1)
    ttk.Label(top, text="Checkpoint 1: select a folder under WORKSPACE_ROOT on the server machine.").grid(row=3, column=0, columnspan=2, sticky="w")

    def choose():
        if not workspace_root:
            messages.put(("log", "Run the client from project-a so it can read WORKSPACE_ROOT from .env."))
            return
        selected = filedialog.askdirectory(initialdir=workspace_root or ".")
        if selected:
            try:
                folder = str(Path(selected).resolve().relative_to(Path(workspace_root).resolve()))
                validate_workspace(folder)
                values["folder"].set(folder)
            except ValueError:
                messages.put(("log", "Choose a folder inside WORKSPACE_ROOT."))
            except Fault as exc:
                messages.put(("log", str(exc)))

    ttk.Button(top, text="Choose folder", command=choose).grid(row=2, column=2)
    buttons = ttk.Frame(root, padding=(12, 0))
    buttons.grid(row=1, column=0, sticky="ew")
    ttk.Combobox(buttons, textvariable=values["mode"], values=["rw", "ro"], state="readonly", width=5).pack(side="left")
    activity = ttk.LabelFrame(root, text="Activity (read-only)", padding=6)
    activity.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
    output = ScrolledText(activity, height=6, wrap="word", state="disabled")
    output.pack(fill="both", expand=True)
    composer = ttk.LabelFrame(root, text="Message", padding=8)
    composer.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
    composer.columnconfigure(0, weight=1)
    prompt = tk.Text(composer, height=4, wrap="word")
    prompt.grid(row=0, column=0, sticky="ew")
    send_controls = ttk.Frame(composer)
    send_controls.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    ttk.Label(send_controls, text="Type your request here. Ctrl+Enter to send.").pack(side="left")

    def worker(fn):
        def work():
            try:
                fn()
            except Exception as exc:
                messages.put(("log", str(exc)))
            finally:
                messages.put(("idle", None))
        threading.Thread(target=work, daemon=True).start()

    def connect():
        if state["watching"] or state["connecting"]:
            return
        folder, mode = values["folder"].get(), values["mode"].get()
        try:
            validate_workspace(folder)
        except Fault as exc:
            messages.put(("log", str(exc)))
            return
        state["connecting"] = True
        client = Client(values["server"].get(), values["token"].get())
        old_client, old_session = state["client"], state["session"]

        def work():
            try:
                if old_session:
                    old_client.release(old_session)
                session = client.create(folder, mode)
                messages.put(("connected", (client, session)))
            finally:
                messages.put(("connect_done", None))
        worker(work)

    def watch(client, session, run, cursor):
        for event in client.watch(session, run, cursor):
            messages.put(("event", event))

    def send():
        text = prompt.get("1.0", "end").strip()
        if not state["session"]:
            messages.put(("log", "Choose a folder and click Connect before sending a message."))
            return
        if not text:
            messages.put(("log", "Type your request in the Message box below, then click Send."))
            prompt.focus_set()
            return
        if state["watching"] or state["connecting"]:
            messages.put(("log", "Wait for the current request to finish, or cancel it first."))
            return
        state["watching"] = True
        client, session, cursor = state["client"], state["session"], state["cursor"]
        messages.put(("log", "You: " + text))
        prompt.delete("1.0", "end")

        def work():
            try:
                run = client.send(session, text)
                messages.put(("run", run))
                watch(client, session, run, cursor)
            finally:
                messages.put(("watch_done", None))
        worker(work)

    def reconnect():
        if not state["run"] or state["watching"]:
            return
        state["watching"] = True

        def work():
            try:
                watch(state["client"], state["session"], state["run"], state["cursor"])
            finally:
                messages.put(("watch_done", None))
        worker(work)

    def cancel():
        if state["session"]:
            client, session = state["client"], state["session"]
            worker(lambda: messages.put(("log", json.dumps(client.cancel(session)))))

    for name, callback in (("Connect", connect), ("Reconnect events", reconnect), ("Cancel", cancel)):
        ttk.Button(buttons, text=name, command=callback).pack(side="left", padx=6)
    ttk.Button(send_controls, text="Send", command=send).pack(side="right")

    def submit_shortcut(_event):
        send()
        return "break"

    prompt.bind("<Control-Return>", submit_shortcut)

    def display(text):
        output.configure(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.configure(state="disabled")

    def poll():
        while not messages.empty():
            kind, data = messages.get_nowait()
            if kind == "connected":
                state.update(client=data[0], session=data[1], cursor=0, run=None)
                display("Connected: " + data[1])
                prompt.focus_set()
            elif kind == "connect_done":
                state["connecting"] = False
            elif kind == "watch_done":
                state["watching"] = False
            elif kind == "run":
                state["run"] = data
            elif kind == "event":
                state["cursor"] = data["seq"]
                display(json.dumps(data, ensure_ascii=False))
                if data["type"] == "result" and data["run_id"] == state["run"]:
                    state["run"] = None
            elif kind == "log":
                display(data)
        root.after(80, poll)

    def close():
        if state["session"]:
            client, session = state["client"], state["session"]
            # Non-daemon cleanup survives closing the window.
            def release():
                try:
                    client.release(session)
                except Exception:
                    pass
            threading.Thread(target=release).start()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(80, poll)
    root.mainloop()
