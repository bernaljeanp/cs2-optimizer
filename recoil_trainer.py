"""Entrenador de recoil fuera del juego: manten pulsado el raton y tira el spray. Puntua tu desvio en grados.

No interactua con CS2: es una ventana propia que lee tu raton (100% legal).
Para que sea fiel: velocidad del puntero de Windows 6/11 y 'Mejorar precision del puntero' desactivado
(asi 1 count del raton = 1 pixel, igual que el raw input de CS2).
"""
import math, sys, tkinter as tk

M_YAW = 0.022
# Patron de impactos acumulado por bala, en grados (x derecha, y arriba) y ms entre balas.
# ponytail: aproximado a ojo, no extraido del juego. Calibralo con practice.cfg (sv_showimpacts) y
# edita estos numeros; para otra arma agrega una entrada.
PATTERNS = {
    "AK-47": (100, list(zip(
        [0, 0, 0.02, 0.04, 0, -0.08, -0.05, 0.05, 0.2, 0, -0.4, -0.9, -1.3, -1.5, -1.4,
         -1.0, -0.4, 0.3, 0.9, 1.4, 1.7, 1.8, 1.6, 1.2, 0.7, 0.3, 0, -0.2, -0.3, -0.3],
        [0, 0.3, 0.75, 1.3, 1.95, 2.6, 3.2, 3.7, 4.1, 4.4, 4.6, 4.75, 4.85, 4.95, 5.0,
         5.05, 5.1, 5.15, 5.2, 5.25, 5.3, 5.32, 5.35, 5.4, 5.42, 5.45, 5.5, 5.52, 5.55, 5.6]))),
}
W, H = 800, 760
START = (400, 60)


def ideal_path(pattern, sens, start=START):
    """Donde debe estar el raton (px) en cada bala para compensar: opuesto al impacto."""
    k = 1 / (sens * M_YAW)  # counts (= px) por grado
    return [(start[0] - x * k, start[1] + y * k) for x, y in pattern]


def score(shots, ideal, sens):
    """Error medio y peor bala en grados, nota 0-100 y consejos."""
    errs = [math.dist(s, i) * sens * M_YAW for s, i in zip(shots, ideal)]
    mean = sum(errs) / len(errs)
    first = list(zip(shots[:10], ideal[:10]))
    rest = list(zip(shots[10:], ideal[10:]))
    tips = []
    dy = sum(s[1] - i[1] for s, i in first) / len(first) if first else 0
    if dy < -8:
        tips.append("Baja mas rapido en las primeras 10 balas.")
    elif dy > 8:
        tips.append("Estas bajando de mas al principio.")
    if rest and sum(abs(s[0] - i[0]) for s, i in rest) / len(rest) > 12:
        tips.append("Pierdes el control lateral desde la bala 11: sigue el zig-zag (derecha, luego izquierda).")
    return {"mean": round(mean, 2), "worst": errs.index(max(errs)) + 1,
            "score": round(max(0, 100 * (1 - mean / 2))), "tips": tips or ["Buen spray."], "errs": errs}


class Trainer(tk.Frame):
    def __init__(self, master, sens=1.25):
        super().__init__(master, bg="#111")
        self.sens = tk.DoubleVar(value=sens)
        self.weapon = tk.StringVar(value=next(iter(PATTERNS)))
        self.shots, self.job, self.best, self.pos = [], None, None, START
        bar = tk.Frame(self, bg="#111")
        bar.pack(fill="x", padx=8, pady=6)
        tk.Label(bar, text="Sensibilidad CS2", fg="#ddd", bg="#111").pack(side="left")
        tk.Spinbox(bar, from_=0.1, to=10, increment=0.05, textvariable=self.sens, width=6,
                   command=self.draw).pack(side="left", padx=6)
        tk.OptionMenu(bar, self.weapon, *PATTERNS, command=lambda _: self.draw()).pack(side="left")
        self.info = tk.Label(bar, text="", fg="#9f9", bg="#111", font=("Segoe UI", 10, "bold"))
        self.info.pack(side="right")
        self.c = tk.Canvas(self, width=W, height=H, bg="#161616", highlightthickness=0)
        self.c.pack()
        self.c.bind("<ButtonPress-1>", self.start)
        self.c.bind("<B1-Motion>", lambda e: setattr(self, "pos", (e.x, e.y)))
        self.c.bind("<ButtonRelease-1>", lambda e: self.finish())
        self.draw()

    def ideal(self):
        return ideal_path(PATTERNS[self.weapon.get()][1], self.sens.get())

    def draw(self):
        self.c.delete("all")
        pts = self.ideal()
        self.c.create_line(*[v for p in pts for v in p], fill="#333", smooth=True)
        for n, (x, y) in enumerate(pts, 1):
            self.c.create_oval(x - 3, y - 3, x + 3, y + 3, outline="#555")
            if n % 5 == 0:
                self.c.create_text(x + 14, y, text=str(n), fill="#666", font=("Segoe UI", 8))
        sx, sy = START
        self.c.create_oval(sx - 12, sy - 12, sx + 12, sy + 12, outline="#4af", width=2)
        self.c.create_text(W / 2, H - 20, fill="#888", text="Pulsa en el circulo azul, manten el click y sigue la "
                           "linea gris como si tiraras el spray. Suelta para ver tu nota.")

    def start(self, e):
        if math.dist((e.x, e.y), START) > 15:
            self.info.config(text="Empieza dentro del circulo azul", fg="#fa4")
            return
        self.draw()
        self.shots, self.pos = [], (e.x, e.y)
        self.fire()

    def fire(self):
        self.shots.append(self.pos)
        x, y = self.pos
        self.c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#4af", outline="")
        if len(self.shots) < len(self.ideal()):
            self.job = self.after(PATTERNS[self.weapon.get()][0], self.fire)
        else:
            self.finish()

    def finish(self):
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        if len(self.shots) < 2:
            return
        r = score(self.shots, self.ideal(), self.sens.get())
        for (x, y), err in zip(self.shots, r["errs"]):
            col = "#4d4" if err < 0.3 else "#dd4" if err < 0.8 else "#d44"
            self.c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=col, outline="")
        self.best = max(self.best or 0, r["score"])
        self.info.config(fg="#9f9", text=f"Nota {r['score']}/100 (mejor {self.best}) | error medio {r['mean']} deg | "
                                         f"peor bala #{r['worst']} | {len(self.shots)} balas")
        self.c.create_text(W / 2, H - 45, fill="#ddd", text="  ".join(r["tips"]))
        self.shots = []


def dpi_aware():
    """Coordenadas en pixeles fisicos para que 1 count = 1 px aunque Windows escale al 125%/150%."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def test():
    pat = PATTERNS["AK-47"][1]
    ideal = ideal_path(pat, 1.25)
    assert len(pat) == 30 and ideal[0] == START and ideal[-1][1] > START[1]  # compensar = tirar hacia abajo
    assert score(ideal, ideal, 1.25)["score"] == 100
    r = score([START] * 30, ideal, 1.25)  # no compensar nada
    assert r["score"] < 20 and "Baja mas rapido" in r["tips"][0]


def main(sens=1.25):
    dpi_aware()
    root = tk.Tk()
    root.title("CS2 Optimizer - Entrenador de recoil")
    root.configure(bg="#111")
    Trainer(root, sens).pack()
    root.mainloop()


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.25)
