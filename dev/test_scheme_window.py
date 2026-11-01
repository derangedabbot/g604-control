import tkinter as tk
from tkinter import ttk
from pathlib import Path

# Проверка окна схемы: ровно тот код, что в приложении
root = tk.Tk()
root.title("Схема кнопок G604")
path = Path("/Users/antonp/Cursor/g604-control/diagram.png")
img = tk.PhotoImage(file=str(path))
factor = max(1, round(img.width() / 980))
if factor > 1:
    img = img.subsample(factor, factor)
lbl = ttk.Label(root, image=img)
lbl.image = img
lbl.pack(padx=10, pady=10)
ttk.Button(root, text="Закрыть", command=root.destroy).pack(pady=(0, 12))
root.after(60000, root.destroy)
root.mainloop()
