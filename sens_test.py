"""Test de sensibilidad: lee tu estilo (flicks + tracking) y recomienda la sensibilidad de CS2.

Simula la camara de CS2: counts del raton (Raw Input) x sensibilidad x 0.022 = grados, con el FOV de CS2
(106.26 grados horizontales a 16:9). Por eso no depende del DPI ni de la aceleracion de Windows.
Metodo: si en los flicks te pasas del objetivo, la sensibilidad es alta; si te quedas corto, es baja.
"""
import math, random, statistics, sys, time, tkinter as tk

from dpi_meter import shared_mouse

M_YAW = 0.022
HFOV = 106.26
FLICKS = 20
TRACK_SECONDS = 12
TARGET_DEG = 1.2  # radio del objetivo, ~una cabeza a media distancia
OK_BAND = 0.07  # +-7% de overshoot se considera normal


def flick_ratio(path, target):
    """Maxima proyeccion de la mira sobre la direccion del objetivo / distancia. >1 = te pasas, <1 = corto."""
    d = math.hypot(*target)
    ux, uy = target[0] / d, target[1] / d
    return max(x * ux + y * uy for x, y in path) / d


def analyze(sens, flicks, track):
    """flicks: [(objetivo_xy, camino_xy, ms, acierto)]; track: [(error_en_direccion_del_movimiento, error_total)]."""
    ratios = [flick_ratio(p, t) for t, p, _, _ in flicks if p and math.hypot(*t) > 8]
    r = statistics.median(ratios) if ratios else 1.0
    rec = sens if abs(r - 1) <= OK_BAND else min(max(sens / r, sens * 0.8), sens * 1.2)  # maximo 20% por test
    ms = statistics.median(f[2] for f in flicks) if flicks else 0
    hits = sum(f[3] for f in flicks) / len(flicks) if flicks else 0
    lag = statistics.mean(t[0] for t in track) if track else 0
    terr = statistics.mean(t[1] for t in track) if track else 0
    tips = []
    if r > 1 + OK_BAND:
        tips.append(f"Te pasas del objetivo un {100 * (r - 1):.0f}% en los flicks: sensibilidad alta.")
    elif r < 1 - OK_BAND:
        tips.append(f"Te quedas corto un {100 * (1 - r):.0f}% y corriges despues: sensibilidad baja.")
    else:
        tips.append("Tus flicks caen justo en el objetivo: tu sensibilidad te va bien.")
    if lag < -0.5:
        tips.append("En tracking vas detras del objetivo: anticipa el movimiento.")
    elif lag > 0.5:
        tips.append("En tracking te adelantas: suaviza el brazo.")
    style = ("agresivo" if ms < 450 else "equilibrado" if ms < 700 else "preciso/lento") + \
            (" y certero" if hits >= 0.7 else "" if hits >= 0.4 else " con muchos fallos")
    return {"ratio": round(r, 2), "rec": round(rec, 2), "ms": round(ms), "hits": round(100 * hits),
            "lag": round(lag, 2), "track_err": round(terr, 2), "style": style, "tips": tips}


class SensTest:
    def __init__(self, master, sens, on_apply=None):
        self.sens, self.on_apply = sens, on_apply
        self.win = tk.Toplevel(master)
        self.win.attributes("-fullscreen", True)  # el cursor real no puede salir: los clics caen siempre aqui
        self.W, self.H = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.f = (self.W / 2) / math.tan(math.radians(HFOV / 2))
        self.c = tk.Canvas(self.win, width=self.W, height=self.H, bg="#0d0d0d", highlightthickness=0, cursor="none")
        self.c.pack()
        cx, cy = self.W / 2, self.H / 2
        for x0, y0, x1, y1 in ((cx - 9, cy, cx - 3, cy), (cx + 3, cy, cx + 9, cy),
                               (cx, cy - 9, cx, cy - 3), (cx, cy + 3, cx, cy + 9)):
            self.c.create_line(x0, y0, x1, y1, fill="#3f3", width=2)
        self.target = self.c.create_oval(0, 0, 0, 0, fill="#e33", outline="")
        self.hud = self.c.create_text(cx, 50, fill="#ddd", font=("Segoe UI", 16))
        self.res = self.c.create_text(cx, cy + 160, fill="#ddd", font=("Segoe UI", 14), justify="center")
        self.mouse = shared_mouse()
        self.last = (self.mouse.dx, self.mouse.dy)
        self.yaw = self.pitch = 0.0
        self.flicks, self.track, self.result = [], [], None
        self.phase = "intro"
        self.c.itemconfig(self.hud, text=f"Test de sensibilidad ({sens}). {FLICKS} flicks: apunta y haz clic en cada "
                                          f"objetivo rapido. Luego {TRACK_SECONDS} s siguiendo un objetivo. "
                                          "Clic para empezar, ESC para salir.")
        self.win.bind("<Escape>", lambda e: self.win.destroy())
        self.win.bind("a", self.apply)
        self.c.bind("<Button-1>", self.click)
        self.loop()

    def project(self, ty, tp):
        dy, dp = math.radians(ty - self.yaw), math.radians(tp - self.pitch)
        if abs(dy) >= math.pi / 2 or abs(dp) >= math.pi / 2:
            return None  # detras de la camara
        return self.W / 2 + self.f * math.tan(dy), self.H / 2 + self.f * math.tan(dp)

    def spawn(self):
        d, a = random.uniform(8, 35), random.uniform(0, 2 * math.pi)
        self.origin = (self.yaw, self.pitch)
        self.goal = (self.yaw + d * math.cos(a), self.pitch + 0.4 * d * math.sin(a))  # CS es sobre todo horizontal
        self.path, self.t0 = [], time.perf_counter()

    def click(self, _):
        if self.phase == "intro":
            self.phase = "flick"
            self.spawn()
        elif self.phase == "flick":
            gy, gp = self.goal
            hit = math.hypot(gy - self.yaw, gp - self.pitch) <= TARGET_DEG
            oy, op = self.origin
            self.flicks.append(((gy - oy, gp - op), self.path, 1000 * (time.perf_counter() - self.t0), hit))
            if len(self.flicks) < FLICKS:
                self.spawn()
            else:
                self.phase = "pretrack"
                self.c.itemconfig(self.hud, text="Ahora sigue el objetivo con la mira sin hacer clic. Clic para empezar.")
        elif self.phase == "pretrack":
            self.phase, self.origin, self.t0, self.prev = "track", (self.yaw, self.pitch), time.perf_counter(), None

    def track_goal(self, t):
        oy, op = self.origin
        return oy + 18 * math.sin(0.9 * t) + 6 * math.sin(2.3 * t + 1), op + 3 * math.sin(1.3 * t)

    def loop(self):
        if not self.win.winfo_exists():
            return
        dx, dy = self.mouse.dx, self.mouse.dy
        k = self.sens * M_YAW
        self.yaw += (dx - self.last[0]) * k
        self.pitch += (dy - self.last[1]) * k
        self.last = (dx, dy)
        goal = None
        if self.phase == "flick":
            self.path.append((self.yaw - self.origin[0], self.pitch - self.origin[1]))
            goal = self.goal
            self.c.itemconfig(self.hud, text=f"Flick {len(self.flicks) + 1}/{FLICKS}")
        elif self.phase == "track":
            t = time.perf_counter() - self.t0
            goal = self.track_goal(t)
            if self.prev and t > self.prev[0]:
                pt, pg = self.prev
                vx, vy = (goal[0] - pg[0]) / (t - pt), (goal[1] - pg[1]) / (t - pt)
                v = math.hypot(vx, vy)
                ex, ey = self.yaw - goal[0], self.pitch - goal[1]
                if v > 3:
                    self.track.append(((ex * vx + ey * vy) / v, math.hypot(ex, ey)))
            self.prev = (t, goal)
            self.c.itemconfig(self.hud, text=f"Tracking: {max(0, TRACK_SECONDS - t):.0f} s")
            if t >= TRACK_SECONDS:
                self.finish()
                goal = None
        pos = self.project(*goal) if goal else None
        r = self.f * math.tan(math.radians(TARGET_DEG))
        self.c.coords(self.target, *((pos[0] - r, pos[1] - r, pos[0] + r, pos[1] + r) if pos else (0, 0, 0, 0)))
        self.win.after(8, self.loop)

    def finish(self):
        self.phase = "done"
        self.result = r = analyze(self.sens, self.flicks, self.track)
        self.c.config(cursor="arrow")
        self.c.itemconfig(self.hud, text=f"Estilo: {r['style']}  |  aciertos {r['hits']}%  |  flick medio {r['ms']} ms")
        change = "mantenla" if r["rec"] == self.sens else f"recomendada {r['rec']}"
        self.c.itemconfig(self.res, text="\n".join(r["tips"]) + f"\n\nSensibilidad actual {self.sens} -> {change}\n"
                          "Repite el test 2-3 veces antes de cambiar.\n"
                          "A = aplicar al autoexec   |   ESC = salir")

    def apply(self, _=None):
        if not self.result or self.result["rec"] == self.sens:
            return
        if self.on_apply:
            self.on_apply(self.result["rec"])
            self.c.itemconfig(self.hud, text=f"Sensibilidad {self.result['rec']} aplicada")
        else:
            import cs2_optimizer
            f = cs2_optimizer.set_autoexec_sens(self.result["rec"])
            msg = f"Aplicada en {f.name}" if f else "No encontre autoexec.cfg: instala la config primero."
            self.c.itemconfig(self.hud, text=msg)


def test():
    target = (20, 0)
    over = [(x, 0) for x in range(0, 25)] + [(20, 0)]  # pico 24 -> ratio 1.2
    short = [(x, 0) for x in range(0, 18)]  # pico 17 -> ratio 0.85
    assert flick_ratio(over, target) == 1.2
    assert analyze(1.0, [(target, over, 400, True)] * 5, [])["rec"] == 0.83
    assert analyze(1.0, [(target, short, 800, False)] * 5, [])["rec"] == 1.18
    exact = [(x, 0) for x in range(0, 21)]
    r = analyze(1.0, [(target, exact, 500, True)] * 5, [(-1.0, 1.5)] * 10)
    assert r["rec"] == 1.0 and "detras" in r["tips"][1] and r["style"] == "equilibrado y certero"


def main():
    import cs2_optimizer
    sens = (float(sys.argv[1]) if len(sys.argv) > 1 else cs2_optimizer.detect_sens()[0]) or 1.0
    root = tk.Tk()
    root.withdraw()
    t = SensTest(root, sens)
    t.win.bind("<Destroy>", lambda e: root.destroy() if e.widget is t.win else None)
    root.mainloop()


if __name__ == "__main__":
    main()
