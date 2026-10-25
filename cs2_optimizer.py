"""CS2 Optimizer: analiza hardware, Windows y red (relays de Valve) y genera la mejor config para tu PC.

Uso:
  python cs2_optimizer.py --dpi 800 --sens 1.25                      # analiza y genera ./out
  python cs2_optimizer.py --dpi 800 --sens 1.25 --install            # copia los .cfg a CS2
  python cs2_optimizer.py --apply-video --fps-avg 420 --fps-low 210  # ajusta cs2_video.txt con tu benchmark
  python cs2_optimizer.py --test                                     # self-check

Solo lee el sistema y escribe archivos de config: no inyecta nada ni mueve el raton (VAC-safe).
"""
import argparse, json, os, re, shutil, statistics, subprocess, sys, tempfile, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # sin ventanas de consola cuando corre como .exe
SDR_URL = "https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730"
FALLBACK_HOSTS = ["1.1.1.1", "8.8.8.8"]
HISTORY = Path(os.environ.get("APPDATA", Path.home())) / "cs2-optimizer" / "history.json"
TIERS = ["baja", "media", "alta"]
POWER_FAST = ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "e9a42b02-d5df-448d-aa00-03f14749eb61")  # alto / maximo rendimiento
VENDORS = {"4318": "NVIDIA", "4098": "AMD", "32902": "Intel"}

# Valores de cs2_video.txt por gama. Solo se tocan claves que ya existen en tu archivo.
VIDEO = {
    "alta": {"msaa_samples": 4, "videocfg_shadow_quality": 2, "videocfg_texture_detail": 2,
             "r_texturefilteringquality": 5, "shaderquality": 0, "videocfg_particle_detail": 0,
             "videocfg_ao_detail": 0, "videocfg_hdr_detail": 3, "videocfg_fsr_detail": 0},
    "media": {"msaa_samples": 2, "videocfg_shadow_quality": 1, "videocfg_texture_detail": 1,
              "r_texturefilteringquality": 3, "shaderquality": 0, "videocfg_particle_detail": 0,
              "videocfg_ao_detail": 0, "videocfg_hdr_detail": 3, "videocfg_fsr_detail": 0},
    "baja": {"msaa_samples": 0, "videocfg_shadow_quality": 0, "videocfg_texture_detail": 0,
             "r_texturefilteringquality": 1, "shaderquality": 0, "videocfg_particle_detail": 0,
             "videocfg_ao_detail": 0, "videocfg_hdr_detail": 3, "videocfg_fsr_detail": 2},
}
VIDEO_ALWAYS = {"mat_vsync": 0, "r_low_latency": 2, "fullscreen": 1, "r_csgo_cmaa_enable": 0,
                "videocfg_dynamic_shadows": 1}  # Reflex+Boost, sin V-Sync, sombras de jugadores visibles


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, errors="ignore", creationflags=NO_WINDOW).stdout


def ps(cmd):
    data = json.loads(sh(["powershell", "-NoProfile", "-Command", cmd + " | ConvertTo-Json"]) or "[]")
    return data if isinstance(data, list) else [data]


def reg(root, key, name):
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, root), key) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return None


# ---------- hardware ----------

def hardware():
    gpus = ps("Get-CimInstance Win32_VideoController | Select-Object Name,CurrentRefreshRate,DriverVersion,"
              "@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}}")
    gpu = max(gpus, key=lambda g: bool(re.search(r"nvidia|radeon|rx ", g["Name"] or "", re.I)))  # dedicada > integrada
    ram = ps("Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory")[0]["TotalPhysicalMemory"]
    return {"gpu": gpu["Name"], "driver": gpu.get("DriverVersion"), "driver_date": gpu.get("DriverDate"),
            "hz": max(g["CurrentRefreshRate"] or 60 for g in gpus), "cores": os.cpu_count(),
            "ram_gb": round(ram / 2**30), "has_dgpu": len(gpus) > 1}


def gpu_tier(name):
    n = name.lower()
    if re.search(r"rtx\s*(30|40|50)\d0|rx\s*(6[7-9]|7\d|9\d)\d0", n):
        return "alta"
    if re.search(r"intel|gtx\s*(9|10)\d0|vega|radeon\(tm\) graphics", n):
        return "baja"
    return "media"


def adjust_tier(tier, hz, fps_low):
    """El benchmark real manda sobre el nombre de la GPU."""
    if not fps_low:
        return tier
    i = TIERS.index(tier)
    if fps_low < hz:
        i = max(0, i - 1)
    elif fps_low > 1.5 * hz:
        i = min(2, i + 1)
    return TIERS[i]


def fps_cap(fps_avg, fps_low):
    """0 = sin limite. Si los 1% low caen por debajo de la mitad de la media, limitar estabiliza el frametime."""
    if fps_avg and fps_low and fps_avg > 2 * fps_low:
        return int(fps_avg * 0.8)  # ponytail: heuristica; sube/baja el 0.8 si notas tirones
    return 0


# ---------- red ----------

def ping(host, n=30):
    out = sh(["ping", "-n", str(n), "-w", "1000", host])
    # "time=12ms", "tiempo=12ms", "tiempo<1ms" -> Windows en ingles y espanol
    return parse_ping([int(t) for t in re.findall(r"[=<](\d+)\s*ms", out)], n)


def parse_ping(times, sent):
    if not times:
        return {"ping": None, "jitter": None, "loss": 100.0}
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0
    return {"ping": round(statistics.median(times)), "jitter": round(jitter, 1),
            "loss": round(100 * (sent - len(times)) / sent, 1)}


def scan_relays(n=4):
    """Ping a un relay de cada region de Valve (SDR). Devuelve la lista ordenada por ping."""
    try:
        with urllib.request.urlopen(SDR_URL, timeout=10) as r:
            pops = json.load(r)["pops"]
    except (OSError, ValueError, KeyError):
        return []
    targets = [(k, v.get("desc", k), v["relays"][0]["ipv4"]) for k, v in pops.items() if v.get("relays")]
    with ThreadPoolExecutor(16) as ex:
        res = ex.map(lambda t: {"pop": t[0], "desc": t[1], "ip": t[2], **ping(t[2], n)}, targets)
    return sorted((r for r in res if r["ping"] is not None), key=lambda r: r["ping"])


def net_buffer(net):
    """cl_net_buffer_ticks: 0 = minimo input lag, 1-2 = suaviza conexiones inestables."""
    if net["loss"] >= 3 or (net["jitter"] or 0) >= 15:
        return 2
    if net["loss"] >= 1 or (net["jitter"] or 0) >= 5:
        return 1
    return 0


def max_mm_ping(best):
    """Ping maximo de matchmaking: tu mejor region + margen, para no caer en servidores lejanos."""
    return max(50, min(350, round(best + 40, -1)))


# ---------- raton ----------

def sens_info(dpi, sens):
    edpi = dpi * sens
    cm360 = 360 / (edpi * 0.022) * 2.54
    if edpi > 1400:
        tip = "eDPI alto: el spray de rifles sera dificil de controlar. Prueba 700-1200."
    elif edpi < 500:
        tip = "eDPI muy bajo: necesitas mucho espacio de alfombrilla para tirar del spray."
    else:
        tip = "eDPI en el rango habitual de pros (500-1400). No lo cambies sin motivo."
    return round(edpi), round(cm360, 1), tip


# ---------- archivos de CS2 ----------

def steam_dir():
    p = reg("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath")
    return Path(p) if p else None


def find_cfg_dir():
    steam = steam_dir()
    if not steam:
        return None
    vdf = steam / "steamapps/libraryfolders.vdf"
    libs = [steam] + ([Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
                      if vdf.exists() else [])
    for lib in libs:
        d = lib / "steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg"
        if d.is_dir():
            return d
    return None


def find_video():
    """cs2_video.txt de la cuenta de Steam usada mas recientemente."""
    steam = steam_dir()
    files = list(steam.glob("userdata/*/730/local/cfg/cs2_video.txt")) if steam else []
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def apply_video(path, settings):
    """Cambia solo claves existentes, conserva formato y deja un .bak con fecha. Devuelve {clave: (antes, despues)}."""
    text = path.read_bytes().decode()
    changed = {}
    for k, v in settings.items():
        pat = re.compile(rf'("setting\.{re.escape(k)}"\s+")([^"]*)(")')
        m = pat.search(text)
        if m and m.group(2) != str(v):
            changed[k] = (m.group(2), str(v))
            text = pat.sub(lambda m: m.group(1) + str(v) + m.group(3), text, count=1)
    if changed:
        shutil.copy2(path, path.with_name(f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak"))
        path.write_bytes(text.encode())
    return changed


def video_value(text, key):
    m = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
    return m.group(1) if m else None


def cs2_running():
    return "cs2.exe" in sh(["tasklist", "/FI", "IMAGENAME eq cs2.exe"]).lower()


# ---------- Windows ----------

def windows_checks(hw, video_text):
    tips = []
    adapters = ps("Get-NetAdapter | Where-Object Status -eq Up | Select-Object Name,PhysicalMediaType,InterfaceDescription")
    real = [a for a in adapters if not re.search(r"vmware|virtual|tailscale|hyper-v|vpn|tap|wireguard|loopback",
                                                 f"{a.get('Name')} {a.get('InterfaceDescription')}", re.I)]
    if any("802.11" in (a.get("PhysicalMediaType") or "") for a in real) and \
            not any("802.3" in (a.get("PhysicalMediaType") or "") for a in real):
        tips.append("Estas por Wi-Fi: un cable Ethernet baja el jitter y la perdida mas que cualquier comando.")
    scheme = sh(["powercfg", "/getactivescheme"]).lower()
    if scheme and not any(g in scheme for g in POWER_FAST):
        tips.append("Plan de energia no es 'Alto rendimiento'. Ejecuta:  powercfg /setactive SCHEME_MIN")
    if reg("HKEY_CURRENT_USER", r"Control Panel\Mouse", "MouseSpeed") not in (None, "0"):
        tips.append("'Mejorar precision del puntero' esta activo: desactivalo (Config. del mouse). "
                    "CS2 usa raw input, pero falsea el entrenador de recoil y el escritorio.")
    if reg("HKEY_CURRENT_USER", r"Software\Microsoft\GameBar", "AutoGameModeEnabled") == "0":
        tips.append("Modo juego de Windows desactivado: activalo (Config > Juegos > Modo de juego).")
    if reg("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode") != "2":
        tips.append("Activa 'Programacion de GPU acelerada por hardware' (Config > Pantalla > Graficos).")
    if hw.get("driver_date"):
        age = (date.today() - date.fromisoformat(hw["driver_date"])).days
        if age > 180:
            tips.append(f"Driver de GPU con {age} dias ({hw['driver']}): actualizalo desde la web del fabricante.")
    if video_text:
        vendor = VENDORS.get(video_value(video_text, "VendorID") or "")
        if hw["has_dgpu"] and vendor == "Intel":
            tips.append("CS2 esta usando la GPU INTEGRADA. Panel NVIDIA/AMD o Config > Pantalla > Graficos: "
                        "asigna cs2.exe a 'Alto rendimiento'.")
        if video_value(video_text, "setting.mat_vsync") == "1":
            tips.append("V-Sync activado en CS2: agrega input lag. --apply-video lo desactiva.")
        if video_value(video_text, "setting.r_low_latency") in ("0", None):
            tips.append("NVIDIA Reflex desactivado en CS2. --apply-video lo pone en Activado + Boost.")
    return tips


# ---------- historial ----------

def save_history(entry):
    """Guarda la medicion y devuelve las anteriores."""
    try:
        hist = json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        hist = []
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps((hist + [entry])[-200:], indent=1))
    return hist


def trend(prev, entry):
    same = [h for h in prev if h.get("pop") == entry["pop"] and h.get("ping") is not None]
    if not same or entry["ping"] is None:
        return None
    p = statistics.mean(h["ping"] for h in same)
    j = statistics.mean(h["jitter"] or 0 for h in same)
    return (f"vs tus {len(same)} mediciones anteriores: ping {entry['ping'] - p:+.0f} ms, "
            f"jitter {entry['jitter'] - j:+.1f} ms")


# ---------- salida ----------

def autoexec(hw, net, buf, dpi, sens, cap, mm_ping):
    mm = f"mm_dedicated_search_maxping {mm_ping}   // tu mejor region + margen\n" if mm_ping else ""
    return f"""// Generado por CS2 Optimizer | GPU {hw['gpu']} | {hw['hz']} Hz | ping {net['ping']} ms
// Red
rate 786432                       // maximo de CS2
cl_net_buffer_ticks {buf}          // 0 si tu linea es estable; 1-2 si hay jitter/perdida
{mm}// FPS / latencia
fps_max {cap}                         // 0 = sin limite (con Reflex el driver evita la cola de GPU)
fps_max_ui 120
engine_low_latency_sleep_after_client_tick true
// Raton (sin aceleracion)
sensitivity {sens}                  // DPI {dpi}
m_yaw 0.022
m_pitch 0.022
zoom_sensitivity_ratio 1.0
// Telemetria en HUD (fps, ping, perdida real con el servidor)
cl_hud_telemetry_frametime_show 1
cl_hud_telemetry_ping_show 1
cl_hud_telemetry_net_misdelivery_show 1
echo "autoexec cargado"
"""


PRACTICE = """// exec practice  -> solo en partida local (Jugar > Practica > servidor offline)
sv_cheats 1
mp_warmup_end
mp_freezetime 0
mp_roundtime_defuse 60
mp_buy_anywhere 1
mp_buytime 99999
mp_maxmoney 60000
mp_startmoney 60000
sv_infinite_ammo 2               // municion infinita pero con recarga (spray real de 30 balas)
sv_showimpacts 1                 // rojo = servidor, azul = cliente
sv_showimpacts_time 8
bot_kick
mp_restartgame 1
give weapon_ak47
echo "Practica: 30 balas a una pared a 10 m, compara con el patron. Repite con m4a1_silencer / famas."
"""

BENCH_HELP = ("Benchmark: suscribete en el Workshop a 'CS2 FPS BENCHMARK', juegalo, anota FPS medio y 1% low "
              "y vuelve a correr con --fps-avg y --fps-low.")


def run(o, log=print):
    log("Leyendo hardware y Windows...")
    hw = hardware()
    video_path = find_video()
    video_text = video_path.read_bytes().decode(errors="ignore") if video_path else ""
    base_tier = gpu_tier(hw["gpu"])
    tier = adjust_tier(base_tier, hw["hz"], o.fps_low)

    log("Midiendo ping a todas las regiones de Valve...")
    relays = scan_relays()
    if relays:
        best = relays[0]
        net = ping(best["ip"], 30)  # 30 muestras a la mejor region para jitter/perdida fiables
        pop = best["pop"]
    else:
        log("No pude leer la lista de relays de Valve; mido contra 1.1.1.1 / 8.8.8.8.")
        net = max((ping(h) for h in FALLBACK_HOSTS), key=lambda r: (r["loss"], r["jitter"] or 0))
        pop = "isp"
    buf = net_buffer(net)
    mm_ping = max_mm_ping(net["ping"]) if net["ping"] is not None else None
    cap = fps_cap(o.fps_avg, o.fps_low)
    edpi, cm360, tip = sens_info(o.dpi, o.sens)

    out = Path("out")
    out.mkdir(exist_ok=True)
    (out / "autoexec.cfg").write_text(autoexec(hw, net, buf, o.dpi, o.sens, cap, mm_ping))
    (out / "practice.cfg").write_text(PRACTICE)

    log(f"\n== Hardware ==  {hw['gpu']} | {hw['cores']} hilos | {hw['ram_gb']} GB RAM | {hw['hz']} Hz")
    log(f"   Gama: {tier}" + (f" (por GPU: {base_tier}, ajustada por tu benchmark)" if tier != base_tier else ""))
    if relays:
        log("\n== Regiones de Valve (mejores 5) ==")
        for r in relays[:5]:
            log(f"   {r['ping']:>4} ms  {r['desc']}")
    log(f"\n== Red ==  ping {net['ping']} ms | jitter {net['jitter']} ms | perdida {net['loss']}%")
    log(f"   -> cl_net_buffer_ticks {buf}" + (f" | ping max matchmaking {mm_ping}" if mm_ping else ""))
    entry = {"date": datetime.now().isoformat(timespec="minutes"), "pop": pop, **net, "fps_low": o.fps_low}
    t = trend(save_history(entry), entry)
    if t:
        log("   " + t)
    log(f"\n== Recoil ==  eDPI {edpi} | {cm360} cm/360. {tip}")
    log("   Entrena con practice.cfg en el juego y con el entrenador fuera del juego (recoil_trainer.py).")
    log(f"\n== FPS ==  fps_max {cap}" + ("" if o.fps_low else f"\n   {BENCH_HELP}"))

    tips = windows_checks(hw, video_text)
    if hw["ram_gb"] < 16:
        tips.append("Menos de 16 GB de RAM: cierra el navegador antes de jugar, CS2 usa ~6-8 GB.")
    log("\n== Windows y CS2 ==")
    for x in tips or ["Todo en orden."]:
        log("   - " + x)

    settings = {**VIDEO[tier], **VIDEO_ALWAYS}
    if o.apply_video:
        if not video_path:
            log("\nNo encontre cs2_video.txt (abre CS2 una vez).")
        elif cs2_running():
            log("\nCierra CS2 antes de --apply-video: el juego sobrescribe el archivo al salir.")
        else:
            changed = apply_video(video_path, settings)
            log(f"\n== Video aplicado (gama {tier}) ==  backup .bak junto a {video_path.name}")
            for k, (a, b) in changed.items() or [("", ("", ""))]:
                log(f"   {k}: {a} -> {b}" if k else "   Ya estaba optimo.")
    else:
        log(f"\nVideo recomendado (gama {tier}): usa --apply-video para escribirlo en cs2_video.txt.")

    log("\nOpciones de lanzamiento en Steam:  +exec autoexec")
    dest = find_cfg_dir() if o.install else None
    if o.install and not dest:
        log("No encontre la carpeta de CS2; copia out/*.cfg a mano a ...\\game\\csgo\\cfg")
    if dest:
        for f in ("autoexec.cfg", "practice.cfg"):
            (dest / f).write_text((out / f).read_text())
        log(f"Instalado en {dest}")
    else:
        log(f"Archivos en {out.resolve()}")


def test():
    assert parse_ping([], 10)["loss"] == 100.0
    n = parse_ping([10, 12, 10, 11], 5)
    assert n["ping"] in (10, 11) and n["loss"] == 20.0
    assert net_buffer({"loss": 0, "jitter": 1}) == 0
    assert net_buffer({"loss": 1.5, "jitter": 1}) == 1
    assert net_buffer({"loss": 0, "jitter": 20}) == 2
    assert max_mm_ping(9) == 50 and max_mm_ping(159) == 200 and max_mm_ping(900) == 350
    assert gpu_tier("NVIDIA GeForce RTX 5070 Laptop GPU") == "alta"
    assert gpu_tier("Intel(R) UHD Graphics") == "baja"
    assert gpu_tier("NVIDIA GeForce GTX 1660") == "media"
    assert adjust_tier("alta", 240, 200) == "media" and adjust_tier("media", 144, 300) == "alta"
    assert adjust_tier("alta", 240, None) == "alta" and adjust_tier("baja", 60, 50) == "baja"
    assert fps_cap(500, 300) == 0 and fps_cap(500, 200) == 400 and fps_cap(None, None) == 0
    assert sens_info(800, 1.25)[0] == 1000
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cs2_video.txt"
        f.write_bytes(b'"video.cfg"\n{\n\t"setting.mat_vsync"\t\t"1"\n\t"setting.msaa_samples"\t\t"4"\n}\n')
        assert apply_video(f, {"mat_vsync": 0, "msaa_samples": 4, "no_existe": 1}) == {"mat_vsync": ("1", "0")}
        assert b'"setting.mat_vsync"\t\t"0"' in f.read_bytes() and len(list(Path(d).glob("*.bak"))) == 1
        assert apply_video(f, {"mat_vsync": 0}) == {}
    import dpi_meter, recoil_trainer
    recoil_trainer.test()
    dpi_meter.test()
    print("ok")


def main():
    ap = argparse.ArgumentParser(description="CS2 Optimizer")
    ap.add_argument("--dpi", type=int, default=800)
    ap.add_argument("--sens", type=float, default=1.25)
    ap.add_argument("--fps-avg", type=int, help="FPS medio del benchmark")
    ap.add_argument("--fps-low", type=int, help="1%% low del benchmark")
    ap.add_argument("--install", action="store_true", help="copia autoexec/practice a la carpeta cfg de CS2")
    ap.add_argument("--apply-video", action="store_true", help="escribe la config de video en cs2_video.txt (con backup)")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        return test()
    run(a)


if __name__ == "__main__":
    sys.exit(main())
