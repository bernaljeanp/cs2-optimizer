"""Interfaz grafica de CS2 Optimizer (es la que se empaqueta como CS2Optimizer.exe)."""
import queue, threading, tkinter as tk
from tkinter import scrolledtext
from types import SimpleNamespace

import cs2_optimizer as core
import dpi_meter
import recoil_trainer
import sens_test

BG, FG = "#111", "#ddd"


def main():
    recoil_trainer.dpi_aware()
    root = tk.Tk()
    root.title("CS2 Optimizer")
    root.configure(bg=BG)
    logs = queue.Queue()  # el analisis corre en otro hilo; Tk solo se toca desde el principal

    form = tk.Frame(root, bg=BG)
    form.pack(fill="x", padx=10, pady=8)
    fields = {}
    dpi, dpi_src = core.detect_dpi()
    sens, sens_src = core.detect_sens()
    for col, (key, label, default) in enumerate([("dpi", "DPI (opcional)", dpi or ""), ("sens", "Sensibilidad", sens or ""),
                                                 ("fps_avg", "FPS medio", ""), ("fps_low", "1% low", "")]):
        tk.Label(form, text=label, fg=FG, bg=BG).grid(row=0, column=col, sticky="w", padx=4)
        fields[key] = tk.Entry(form, width=10)
        fields[key].insert(0, default)
        fields[key].grid(row=1, column=col, padx=4)
    install, video = tk.BooleanVar(value=True), tk.BooleanVar()
    tk.Checkbutton(form, text="Instalar cfg en CS2", variable=install, fg=FG, bg=BG, selectcolor="#333",
                   activebackground=BG).grid(row=2, column=0, columnspan=2, sticky="w")
    tk.Checkbutton(form, text="Aplicar video (cierra CS2)", variable=video, fg=FG, bg=BG, selectcolor="#333",
                   activebackground=BG).grid(row=2, column=2, columnspan=2, sticky="w")

    out = scrolledtext.ScrolledText(root, width=100, height=34, bg="#161616", fg=FG, insertbackground=FG,
                                    font=("Consolas", 10))
    out.pack(padx=10, pady=(0, 10), fill="both", expand=True)

    def num(key, kind):
        v = fields[key].get().strip().replace(",", ".")
        return kind(v) if v else None

    def analyze():
        try:
            opts = SimpleNamespace(dpi=num("dpi", int), sens=num("sens", float), fps_avg=num("fps_avg", int),
                                   fps_low=num("fps_low", int), install=install.get(), apply_video=video.get())
        except ValueError as e:
            out.insert("end", f"Revisa los campos: {e}\n")
            return
        out.delete("1.0", "end")
        run_btn.config(state="disabled")

        def work():
            try:
                core.run(opts, logs.put)
            except Exception as e:  # mostrar cualquier fallo en la ventana en vez de morir en silencio
                logs.put(f"\nError: {e!r}")
            logs.put(None)
        threading.Thread(target=work, daemon=True).start()

    def poll():
        while not logs.empty():
            line = logs.get()
            if line is None:
                run_btn.config(state="normal")
            else:
                out.insert("end", line + "\n")
                out.see("end")
        root.after(100, poll)

    def trainer():
        win = tk.Toplevel(root)
        win.title("Entrenador de recoil")
        win.configure(bg=BG)
        try:
            sens = num("sens", float) or 1.25
        except ValueError:
            sens = 1.25
        recoil_trainer.Trainer(win, sens).pack()

    def meter():
        win = tk.Toplevel(root)
        win.title("Medidor de DPI")
        win.configure(bg=BG)

        def got(dpi):
            fields["dpi"].delete(0, "end")
            fields["dpi"].insert(0, str(dpi))
        try:
            dpi_meter.DpiMeter(win, got).pack()
        except OSError as e:
            win.destroy()
            out.insert("end", f"Medidor de DPI no disponible: {e}\n")

    def sens_check():
        try:
            sens = num("sens", float)
        except ValueError:
            sens = None
        if not sens:
            out.insert("end", "Pon tu sensibilidad de CS2 antes del test.\n")
            return

        def apply(rec):
            fields["sens"].delete(0, "end")
            fields["sens"].insert(0, str(rec))
            f = core.set_autoexec_sens(rec)
            out.insert("end", f"Sensibilidad {rec} " + (f"guardada en {f}\n" if f else "(instala la config para guardarla)\n"))
        sens_test.SensTest(root, sens, apply)

    bar = tk.Frame(form, bg=BG)
    bar.grid(row=1, column=4, rowspan=2, padx=12)
    run_btn = tk.Button(bar, text="Analizar y optimizar", command=analyze, bg="#2a6", fg="white", width=20)
    run_btn.pack(pady=2)
    tk.Button(bar, text="Entrenador de recoil", command=trainer, bg="#246", fg="white", width=20).pack(pady=2)
    tk.Button(bar, text="Test de sensibilidad", command=sens_check, bg="#a52", fg="white", width=20).pack(pady=2)
    tk.Button(bar, text="Medir DPI (opcional)", command=meter, bg="#333", fg="#aaa", width=20).pack(pady=2)
    out.insert("end", f"Sensibilidad detectada: {sens or 'desconocida'} ({sens_src or 'no encontre la config de CS2'})\n"
                      f"DPI: {dpi or 'desconocido'}" + (f" ({dpi_src})" if dpi else "") +
                      ". No hace falta: el Test de sensibilidad trabaja directo con tu raton.\n"
                      "1. 'Test de sensibilidad' lee tu estilo y te recomienda sensibilidad.\n"
                      "2. 'Analizar y optimizar' configura red, video y Windows.\n" + core.BENCH_HELP + "\n")
    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
