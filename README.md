# CS2 Optimizer

Analiza tu PC, Windows y tu conexión a los servidores de Valve, y genera la configuración de Counter-Strike 2 que mejor le va a **tu** hardware y **tu** red. Incluye un entrenador de recoil fuera del juego.

> **VAC-safe:** solo lee el sistema y escribe archivos de configuración (`.cfg`, `cs2_video.txt`). No inyecta nada en el juego, no lee su memoria y no mueve el ratón. No es un anti-recoil ni un macro.

## Qué hace

| Área | Qué mide | Qué ajusta |
|---|---|---|
| **Red** | Ping, jitter y pérdida a **todas las regiones de Valve** (lista oficial SDR de Steam) | `cl_net_buffer_ticks`, `rate`, ping máximo de matchmaking según tu mejor región |
| **Hardware** | GPU, RAM, núcleos, Hz del monitor | Preset de video por gama (baja / media / alta) |
| **Benchmark** | FPS medio y 1% low que introduces | Corrige la gama según tus FPS reales y limita `fps_max` si el frametime es inestable |
| **Video** | Tu `cs2_video.txt` actual | Lo reescribe con backup `.bak`: Reflex + Boost, MSAA, sombras… (V-Sync no se toca: ON con G-Sync/FreeSync, OFF sin él) |
| **Windows** | Wi-Fi vs cable, plan de energía, aceleración del ratón, modo juego, HAGS, antigüedad del driver, **CS2 usando la GPU integrada** en portátiles | Te dice qué cambiar (no toca Windows) |
| **DPI real** | Counts del ratón vía Raw Input al moverlo una distancia medida | Te dice tu DPI real (los sensores se desvían un 2–10% del valor anunciado) y lo usa para el eDPI |
| **Recoil** | eDPI y cm/360 | `practice.cfg` para entrenar spray en el juego + entrenador fuera del juego con nota |
| **Historial** | Guarda cada medición | Compara tu ping/jitter con mediciones anteriores |

## Uso

**Opción 1: `.exe`.** Descarga `CS2Optimizer.exe` de [Releases](../../releases) y ejecútalo. Windows SmartScreen puede avisar porque el ejecutable no está firmado: *Más información → Ejecutar de todas formas*.

**Opción 2: Python 3.10+** (solo librería estándar, sin dependencias):

```bash
python gui.py                                      # interfaz gráfica
python cs2_optimizer.py --dpi 800 --sens 1.25      # línea de comandos, genera ./out
python cs2_optimizer.py --dpi 800 --sens 1.25 --install --apply-video --fps-avg 420 --fps-low 210
python recoil_trainer.py 1.25                      # entrenador, con tu sensibilidad
```

| Opción | Efecto |
|---|---|
| `--install` | Copia `autoexec.cfg` y `practice.cfg` a la carpeta `cfg` de CS2 |
| `--apply-video` | Escribe el preset en `cs2_video.txt` (cierra CS2 antes; deja backup) |
| `--fps-avg` / `--fps-low` | Resultado del mapa de Workshop *CS2 FPS BENCHMARK* |

Después, en Steam → CS2 → Propiedades → Opciones de lanzamiento: `+exec autoexec`.
Para practicar spray: crea una partida offline y escribe `exec practice` en la consola.

## Medidor de DPI

`python dpi_meter.py`, o el botón *Medir DPI real* en la interfaz. Pon una regla, pulsa ESPACIO, mueve el ratón en línea recta la distancia indicada y pulsa ESPACIO otra vez. Con 3 medidas usa la mediana y rellena el DPI en la interfaz. Lee Raw Input, igual que CS2, así que no le afectan la aceleración ni la velocidad del puntero de Windows.

**Cambiar el DPI dentro del ratón:** cada fabricante usa un protocolo USB propio y la mayoría no está documentado. Por eso el programa no escribe en el firmware: cambia el DPI con el botón del ratón o con su software y confírmalo con el medidor.

## Entrenador de recoil

Muestra el camino que debe seguir tu ratón para compensar el spray del AK-47 **con tu sensibilidad**. Pulsa en el círculo, mantén el click y tira del spray; al soltar ves tu error medio en grados, la peor bala y consejos.

Para que sea fiel: velocidad del puntero de Windows 6/11 y *Mejorar precisión del puntero* desactivado.
El patrón es **aproximado**. Calíbralo con `practice.cfg` (`sv_showimpacts`) editando `PATTERNS` en `recoil_trainer.py`. PRs con patrones medidos y más armas son bienvenidos.

## Limitaciones conocidas

- Solo Windows.
- El ping se mide por ICMP a los relays de Valve: es una buena aproximación, pero el valor real en partida es el de la telemetría del HUD (que el `autoexec` activa).
- La gama de GPU se deduce del nombre hasta que introduces tu benchmark.
- Valve puede cambiar comandos o el formato de `cs2_video.txt` con actualizaciones. Solo se modifican claves que ya existen en tu archivo.

## Desarrollo

```bash
python cs2_optimizer.py --test
```

Al publicar un tag `v*`, GitHub Actions compila el `.exe` y lo sube a Releases.

Licencia MIT. No afiliado a Valve.
