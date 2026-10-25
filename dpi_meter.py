"""Medidor de DPI real: mueve el raton una distancia conocida con una regla y cuenta los counts en raw input.

Usa Raw Input de Windows (lo mismo que lee CS2), asi que no le afectan la aceleracion ni la velocidad del
puntero de Windows, ni que el cursor choque con el borde de la pantalla.
"""
import ctypes, math, statistics, sys, threading, tkinter as tk
from ctypes import wintypes as wt

STANDARD = [400, 800, 1000, 1200, 1600, 2000, 3200, 6400]
WM_INPUT, RID_INPUT, RIDEV_INPUTSINK, RIM_TYPEMOUSE, MOUSE_MOVE_ABSOLUTE = 0xFF, 0x10000003, 0x100, 0, 1
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wt.USHORT), ("ulButtons", wt.ULONG), ("ulRawButtons", wt.ULONG),
                ("lLastX", wt.LONG), ("lLastY", wt.LONG), ("ulExtraInformation", wt.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RawMouse:
    """Acumula el movimiento crudo del raton en un hilo con una ventana invisible (message-only)."""

    def __init__(self):
        self.dx = self.dy = 0
        self.ready = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()
        if not self.ready.wait(3):
            raise OSError("No pude registrar Raw Input")

    def reset(self):
        self.dx = self.dy = 0

    def _loop(self):
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32")
        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        u.CreateWindowExW.restype = wt.HWND
        u.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT), wt.UINT]
        u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        k.GetModuleHandleW.restype = wt.HMODULE
        raw, size = RAWINPUT(), wt.UINT(ctypes.sizeof(RAWINPUT))

        def proc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                size.value = ctypes.sizeof(RAWINPUT)
                if u.GetRawInputData(lparam, RID_INPUT, ctypes.byref(raw), ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER)) > 0 \
                        and raw.header.dwType == RIM_TYPEMOUSE and not raw.mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
                    self.dx += raw.mouse.lLastX
                    self.dy += raw.mouse.lLastY
            return u.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = WNDPROC(proc)  # mantener referencia viva o el callback se libera
        hinst = k.GetModuleHandleW(None)
        u.RegisterClassW(ctypes.byref(WNDCLASS(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="CS2OptRaw")))
        hwnd = u.CreateWindowExW(0, "CS2OptRaw", None, 0, 0, 0, 0, 0, wt.HWND(-3), None, hinst, None)  # HWND_MESSAGE
        dev = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd)  # usage page 1 / usage 2 = raton
        if not hwnd or not u.RegisterRawInputDevices(ctypes.byref(dev), 1, ctypes.sizeof(dev)):
            return
        self.ready.set()
        msg = wt.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))


def dpi_from(counts, cm):
    return counts / (cm / 2.54)


def nearest_standard(dpi):
    return min(STANDARD, key=lambda s: abs(s - dpi))


class DpiMeter(tk.Frame):
    def __init__(self, master, on_result=None):
        super().__init__(master, bg="#111", padx=16, pady=12)
        self.on_result, self.results, self.measuring = on_result, [], False
        self.mouse = RawMouse()
        self.cm = tk.StringVar(value="10")
        row = tk.Frame(self, bg="#111")
        row.pack(anchor="w")
        tk.Label(row, text="Distancia a mover (cm):", fg="#ddd", bg="#111").pack(side="left")
        tk.Entry(row, textvariable=self.cm, width=6).pack(side="left", padx=6)
        tk.Label(self, fg="#aaa", bg="#111", justify="left", text=(
            "1. Pon una regla junto a la alfombrilla (o usa una tarjeta: 8.56 cm de ancho).\n"
            "2. Pulsa ESPACIO, mueve el raton en linea recta exactamente esa distancia y pulsa ESPACIO otra vez.\n"
            "3. Repite 3 veces: se usa la mediana. Levantar el raton invalida la medida."
        )).pack(anchor="w", pady=8)
        self.live = tk.Label(self, text="", fg="#4af", bg="#111", font=("Segoe UI", 16, "bold"))
        self.live.pack(pady=6)
        self.out = tk.Label(self, text="", fg="#9f9", bg="#111", font=("Segoe UI", 11), justify="left")
        self.out.pack(anchor="w")
        master.bind("<space>", self.toggle)
        self.tick()

    def toggle(self, _=None):
        if not self.measuring:
            self.mouse.reset()
            self.measuring = True
            return
        self.measuring = False
        try:
            cm = float(self.cm.get().replace(",", "."))
        except ValueError:
            self.out.config(text="Distancia invalida", fg="#fa4")
            return
        counts = math.hypot(self.mouse.dx, self.mouse.dy)
        if counts < 50 or cm <= 0:
            self.out.config(text="Movimiento demasiado corto, repite.", fg="#fa4")
            return
        self.results.append(dpi_from(counts, cm))
        dpi = statistics.median(self.results)
        std = nearest_standard(dpi)
        text = (f"Medidas: {', '.join(f'{r:.0f}' for r in self.results)}\n"
                f"DPI real: {dpi:.0f}  (configurado probablemente a {std}, desvio {100 * (dpi - std) / std:+.1f}%)")
        if len(self.results) >= 3 and statistics.pstdev(self.results) / dpi > 0.05:
            text += "\nLas medidas varian mas de 5%: mueve mas recto y sin levantar el raton."
        self.out.config(text=text, fg="#9f9")
        if self.on_result and len(self.results) >= 3:
            self.on_result(round(dpi))

    def tick(self):
        if self.measuring:
            self.live.config(text=f"Midiendo... {math.hypot(self.mouse.dx, self.mouse.dy):.0f} counts  (ESPACIO para parar)")
        else:
            self.live.config(text=f"Medida {len(self.results) + 1}: pulsa ESPACIO para empezar")
        self.after(50, self.tick)


def test():
    assert round(dpi_from(3150, 10)) == 800 and round(dpi_from(1600, 2.54)) == 1600
    assert nearest_standard(812) == 800 and nearest_standard(1530) == 1600


def main():
    root = tk.Tk()
    root.title("CS2 Optimizer - Medidor de DPI")
    root.configure(bg="#111")
    DpiMeter(root).pack()
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
