import sys
from pathlib import Path
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import g604_editor as g

root = tk.Tk()
root.withdraw()

sample = [
    {"mods": 0x08, "key": "c", "delay": 50},
    {"mods": 0x08, "key": "v", "delay": 120},
]
dlg = g.MacroDialog(root, sample)
dlg.after(90000, dlg.destroy)
root.mainloop()
