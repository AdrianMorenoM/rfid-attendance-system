<div align="center">

# Sistema de Control de Asistencia RFID
## Documentación Técnica Integral

**Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH)**
**Ingeniería en Tecnologías de la Información y Comunicación**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?logo=raspberrypi&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Gunicorn-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL%20mode-003B57?logo=sqlite&logoColor=white)
![Estado](https://img.shields.io/badge/Estado-Producción-success)

</div>

---

> ### Datos
> | Campo | Valor |
> |---|---|
> | **Nombre del estudiante** | Adrián Moreno Méndez |
> | **Matrícula** | 22011747 |
> | **Asesor** | José Martín Oropeza Méndez |
> | **Fecha del reporte** | 18 de Junio del 2026 (Actualizado a Agosto del 2026) |

---

## Acerca de este documento

Este notebook documenta de forma técnica y visual el **Sistema de Control de Asistencia por RFID** desarrollado como parte del Servicio Social en el ITSOEH. Cubre arquitectura, hardware, software, base de datos, seguridad y dependencias del sistema, con diagramas generados en Python para que el reporte sea reproducible, versionable en Git y visualmente claro tanto en Jupyter como en GitHub.

<a id="toc"></a>
## Tabla de contenido

1. [Introducción y objetivos](#1)
2. [Arquitectura general del sistema](#2)
3. [Hardware](#3)
4. [Firmware y lógica del lector RFID](#4)
5. [Software — estructura y servicios](#5)
6. [Base de datos](#6)
7. [API REST](#7)
8. [Flujo de datos de extremo a extremo](#8)
9. [Analítica y panel de control (dashboard)](#9)
10. [Procesamiento de datos](#10)
11. [Registros y bitácoras (logs)](#11)
12. [Seguridad](#12)
13. [Mapa de dependencias](#13)
14. [Conclusiones y recomendaciones](#14)
15. [Glosario](#15)
16. [Referencias y anexos](#16)

<a id="1"></a>
## 1. Introducción y objetivos 
[[Volver a la tabla de contenido]](#toc)

### 1.1 Contexto
El control de asistencia manual en instituciones educativas es propenso a errores, suplantación y pérdida de tiempo administrativo. Como parte del Servicio Social, se desarrolló e implementó un **sistema de control de asistencia automatizado basado en tecnología RFID (13.56 MHz, HF)**, que permite registrar la entrada de estudiantes mediante una tarjeta física, almacenar la información en una base de datos local, y visualizarla en tiempo real a través de un panel administrativo y una pantalla en modo kiosco.

### 1.2 Objetivo general
Diseñar y documentar un sistema de control de asistencia por RFID funcional, seguro y mantenible para el ITSOEH, que sirva como base para futuras mejoras y como evidencia técnica del Servicio Social realizado.

### 1.3 Objetivos específicos
- Implementar la lectura de tarjetas RFID mediante un módulo RC522 conectado a una Raspberry Pi 4.
- Diseñar una base de datos relacional que modele estudiantes, tarjetas y registros de asistencia.
- Desarrollar una API REST para la administración de estudiantes y tarjetas (alta, baja, exportación).
- Desarrollar un panel de visualización en tiempo real (dashboard) con métricas del día.
- Implementar mecanismos de resiliencia (reconexión automática de red) y trazabilidad (auditoría).
- Evaluar la seguridad del sistema e identificar áreas de mejora.
- Documentar íntegramente la arquitectura para transferencia de conocimiento.

### 1.4 Alcance
El sistema opera de forma **local y autónoma** dentro de la red institucional; no depende de servicios en la nube ni de APIs de terceros. Está diseñado para un solo punto de lectura (un lector RC522).

<a id="2"></a>
## 2. Arquitectura general del sistema
[[Volver a la tabla de contenido]](#toc)

La siguiente celda define el estilo visual compartido (paleta de colores, funciones de dibujo) que se reutiliza en todos los diagramas de este notebook, para mantener consistencia visual.


```python
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams['font.family'] = 'DejaVu Sans'

COLOR = {
    'primary':   '#2C3E50',
    'secondary': '#2980B9',
    'accent':    '#16A085',
    'warning':   '#E67E22',
    'danger':    '#C0392B',
    'success':   '#27AE60',
    'neutral':   '#7F8C8D',
    'bg':        '#ECF0F1',
    'white':     '#FFFFFF',
}

def draw_box(ax, xy, w, h, text, fc=COLOR['secondary'], ec='white', fs=9.5, tc='white', lw=1.6):
    x, y = xy
    box = FancyBboxPatch((x, y), w, h,
                          boxstyle="round,pad=0.02,rounding_size=0.06",
                          linewidth=lw, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(box)
    ax.text(x + w/2, y + h/2, text, ha='center', va='center',
             fontsize=fs, color=tc, weight='bold', zorder=3, linespacing=1.4)
    return (x + w/2, y + h/2)

def draw_arrow(ax, start, end, text=None, color=COLOR['neutral'], style='-|>', lw=1.8, fs=8, curve=0.0):
    conn = f"arc3,rad={curve}"
    a = FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=14,
                         color=color, linewidth=lw, zorder=1, connectionstyle=conn)
    ax.add_patch(a)
    if text:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(mx, my + 0.12, text, fontsize=fs, color=color, ha='center',
                 style='italic', zorder=4,
                 bbox=dict(boxstyle='round,pad=0.15', fc='white', ec='none', alpha=0.85))

def new_canvas(w=13, h=8, title=None):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis('off')
    if title:
        ax.text(w/2, h - 0.35, title, ha='center', va='top',
                 fontsize=15, weight='bold', color=COLOR['primary'])
    return fig, ax

print("Report-style ready")
```

    Report-style ready



```python
fig, ax = new_canvas(13, 8.5, "Arquitectura general — Sistema RFID (ITSOEH)")

p_card = draw_box(ax, (0.4, 6.6), 2.4, 1.0, "Tarjeta RFID\n(usuario)", fc=COLOR['neutral'])
p_reader = draw_box(ax, (0.4, 4.6), 2.8, 1.3,
                     "RC522 + Raspberry Pi 4\nrfid-reader.service\n(root)", fc=COLOR['primary'])
p_db = draw_box(ax, (5.3, 4.6), 2.6, 1.3,
                 "rfid.db\n(SQLite · WAL mode)\nSPOF del sistema", fc=COLOR['accent'])
p_crud = draw_box(ax, (9.6, 6.0), 3.0, 1.3,
                   "rfid-crud.service\nAPI + Admin\n0.0.0.0:5001", fc=COLOR['secondary'])
p_dash = draw_box(ax, (9.6, 4.2), 3.0, 1.3,
                   "rfid-dashboard.service\nMétricas en vivo\n127.0.0.1:5000", fc=COLOR['secondary'])
p_kiosk = draw_box(ax, (9.6, 2.4), 3.0, 1.1,
                    "kiosk.service\nChromium --kiosk\n(pantalla física)", fc='#5D6D7E')
p_watch = draw_box(ax, (0.4, 2.2), 2.8, 1.2,
                    "network-watchdog\n.service\n(reconexión Wi-Fi auto)", fc=COLOR['warning'])
p_shared = draw_box(ax, (5.3, 2.4), 2.6, 1.1,
                     "]/run/rfid-shared/\n(modo alta de tarjeta)", fc=COLOR['neutral'])
p_bak = draw_box(ax, (5.3, 0.6), 2.6, 1.0, "shared/backups/\nrespaldos periódicos", fc=COLOR['neutral'])

draw_arrow(ax, (p_card[0], 6.55), (p_reader[0], 5.95), "acerca tarjeta")
draw_arrow(ax, (3.2, 5.25), (5.3, 5.25), "INSERT asistencia")
draw_arrow(ax, (7.9, 5.55), (9.6, 6.55), "lee/escribe")
draw_arrow(ax, (7.9, 5.15), (9.6, 4.85), "solo lectura")
draw_arrow(ax, (11.1, 4.2), (11.1, 3.5), "renderiza en")
draw_arrow(ax, (2.8, 3.2), (5.3, 3.0), "vigila conectividad", color=COLOR['warning'])
draw_arrow(ax, (6.6, 4.6), (6.6, 3.5), "modo admin", color=COLOR['neutral'])
draw_arrow(ax, (6.6, 4.6), (6.6, 1.6), "respaldo periódico", color=COLOR['neutral'], curve=0.25)

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_5_0.png)
    


> **Lectura del diagrama:** el sistema gira alrededor de una única base de datos SQLite (`rfid.db`), a la que escribe el lector y de la que leen tanto el panel administrativo (`crud`) como el dashboard. La pantalla física (kiosco) solo consume el dashboard vía HTTP local; el watchdog de red opera de forma independiente, vigilando únicamente la conectividad Wi-Fi. **`rfid.db` es el punto único de falla (SPOF)** — se profundiza en la [sección 13](#13).

<a id="3"></a>
## 3. Hardware
[[Volver a la tabla de contenido]](#toc)

| Componente | Detalle |
|---|---|
| Unidad de cómputo | Raspberry Pi 4 Model B |
| Lector RFID | Módulo **RC522** — HF, 13.56 MHz, estándar MIFARE |
| Interfaz de conexión | SPI (`spidev`) + pines GPIO |
| Medio de identificación | Tarjetas/llaveros MIFARE (UID de 4 bytes) |
| Salida visual | Sin pantalla física en esta implementación; consulta vía dashboard web en la red local (arquitectura preparada para un kiosco físico a futuro, ver §2) |
| Conectividad | Wi-Fi, con reconexión automática vía `network-watchdog.service` |

**Nota sobre el método de lectura:** la lectura del UID se realiza mediante los comandos *Request* + *Anticollision* del protocolo MIFARE, **sin autenticación criptográfica de sector**. Esto es adecuado para control de asistencia (bajo riesgo, no protege activos críticos), pero implica que el sistema identifica tarjetas por UID físico, no por contenido cifrado — se retoma en la sección de seguridad.

### 3.1 Diagrama de conexiones físicas (RC522 &harr; Raspberry Pi 4)

El lector RC522 se comunica con la Raspberry Pi 4 Model B mediante el bus **SPI0** nativo del GPIO de 40 pines. A continuación se muestra el esquema de conexión, seguido de la tabla de referencia con el color de cable sugerido (convención habitual en la mayoría de los kits RC522, útil para no confundir cableado durante el montaje o una reparación futura).


**Tabla de cableado — RC522 &rarr; Raspberry Pi 4 (GPIO físico)**

| Pin RC522 | Función | Pin físico Raspberry Pi | GPIO (BCM) |
|---|---|---|---|
| 3.3V | Alimentación lógica | Pin 1 | 3V3 (no GPIO) |
| RST | Reset del módulo | Pin 22 | GPIO25 |
| GND | Tierra común | Pin 6 | GND (no GPIO) |
| IRQ | Interrupción (no usada) | — (sin conectar) | — |
| MISO | SPI — Master In Slave Out | Pin 21 | GPIO9 (SPI0 MISO) |
| MOSI | SPI — Master Out Slave In | Pin 19 | GPIO10 (SPI0 MOSI) |
| SCK | SPI — Reloj (Clock) | Pin 23 | GPIO11 (SPI0 SCLK) |
| SDA (SS/CS) | SPI — Chip Select | Pin 24 | GPIO8 (SPI0 CE0) |

> **Nota importante:** el RC522 opera a **3.3 V lógicos**. Nunca debe alimentarse desde el pin de 5 V de la Raspberry Pi — hacerlo puede dañar permanentemente tanto el módulo como el GPIO de la Pi. El pin `IRQ` se deja sin conectar porque el firmware (`rfid_reader.py`) hace *polling* por software cada 150 ms en lugar de usar interrupciones por hardware.

### 3.2 Lista de materiales

| Componente | Modelo / referencia | Cantidad | Notas |
|---|---|---|---|
| Unidad de cómputo | Raspberry Pi 4 Model B (2 GB u 8 GB RAM) | 1 | Corre los tres servicios systemd (`rfid-reader`, `rfid-crud`, `rfid-dashboard`) |
| Lector RFID | Módulo **RC522** (MFRC522), HF 13.56 MHz | 1 | Antena integrada en la PCB del módulo; no requiere antena externa |
| Tarjetas/llaveros | MIFARE Classic 1K/4K o compatibles (UID de 4 bytes) | Según usuarios | Se identifican por UID físico, sin lectura de sector cifrado |
| Almacenamiento | microSD Clase 10 / A1, 16 GB o superior | 1 | Aloja el OS, `rfid.db` (SQLite en modo WAL) y los logs |
| Fuente de alimentación | Fuente oficial Raspberry Pi USB-C, **5 V / 3 A** | 1 | Alimenta tanto la Pi como el RC522 (vía el riel 3.3V de la propia Pi) |
| Cableado | 7× cables jumper hembra-hembra (Dupont), 10–15 cm | 1 set | Ver tabla de colores de la sección 3.1 |
| Gabinete/caja | Case ventilado para Raspberry Pi 4 (con acceso a GPIO) | 1 | Debe permitir el paso del cableado hacia el RC522 sin forzar los conectores |
| Pantalla | *No incluida en esta implementación* | — | El diagrama de arquitectura (sección 2) contempla un modo kiosco futuro; actualmente el acceso es vía dashboard web en la red local |

*Los modelos exactos (fabricante del kit RC522, marca de la microSD, etc.) dependen del proveedor local; se listan aquí las especificaciones mínimas necesarias para reproducir el sistema.*


### 3.3 Requisitos eléctricos

| Parámetro | Valor | Detalle |
|---|---|---|
| Alimentación Raspberry Pi 4 | 5 V &plusmn; 5%, hasta 3 A (15 W) | Vía USB-C; usar fuente **oficial o certificada** — fuentes genéricas de menor amperaje provocan el ícono de rayo (bajo voltaje) y *brownouts* que pueden corromper la SD o reiniciar el lector a mitad de una escritura en `rfid.db` |
| Alimentación RC522 | 3.3 V (tomados del propio riel 3V3 de la Pi, pin 1 o 17) | **No conectar a 5 V** bajo ninguna circunstancia |
| Consumo del RC522 | ~13–26 mA en reposo/lectura, hasta ~30 mA en picos de escritura | Bien dentro del presupuesto de corriente del riel 3.3V de la Pi 4 (~50 mA disponibles en el pin GPIO, mucho más si se toma directo del regulador) |
| Consumo total estimado | ~600–700 mA en operación normal (Pi 4 + RC522 + Wi-Fi activo) | Puede superar 1 A en arranque o con picos de CPU (dashboard + lector + Wi-Fi simultáneos) |

**Recomendaciones de alimentación estable:**
- Usar exclusivamente la fuente oficial USB-C de 5 V/3 A (o equivalente certificada) — nunca un cargador de celular genérico.
- Evitar cables USB-C largos o de baja sección; la caída de tensión en el cable es una causa común de *undervoltage* en Raspberry Pi.
- Si el sistema se instala en un punto sin acceso eléctrico estable, considerar un UPS pequeño o power bank con salida PD de 5V/3A, para evitar corrupción de la base de datos SQLite ante cortes de energía.
- Verificar periódicamente `vcgencmd get_throttled` — un valor distinto de `0x0` indica que hubo (o hay) condiciones de bajo voltaje.



```python
fig, ax = new_canvas(11, 7.3, "Disposici\u00f3n f\u00edsica sugerida dentro de la caja")

# Caja (vista superior)
box_x, box_y, box_w, box_h = 1.0, 0.8, 9.0, 4.9
ax.add_patch(plt.Rectangle((box_x, box_y), box_w, box_h, fill=False,
                            edgecolor=COLOR['primary'], linewidth=2.2, zorder=2))
ax.text(box_x + box_w/2, box_y + box_h + 0.55, "Gabinete (vista superior)",
        ha='center', fontsize=10.5, weight='bold', color=COLOR['primary'])

# Raspberry Pi
draw_box(ax, (box_x + 0.6, box_y + 1.8), 3.2, 2.2, "Raspberry Pi 4\n(GPIO hacia arriba)",
         fc=COLOR['secondary'], fs=9.5)

# Fuente / entrada USB-C
draw_box(ax, (box_x + 0.6, box_y + 0.3), 3.2, 1.0, "Entrada USB-C\n(alimentaci\u00f3n)",
         fc=COLOR['neutral'], fs=8.5)

# RC522 cerca del borde/tapa frontal, lejos de metal
draw_box(ax, (box_x + 5.6, box_y + 2.5), 2.8, 1.5, "RC522\n(antena hacia la tapa frontal)",
         fc=COLOR['accent'], fs=9)

# Zona de acercamiento de tarjeta (fuera de la caja, frente al RC522)
draw_box(ax, (box_x + 5.6, box_y + 4.2), 2.8, 0.5, "Zona de lectura\n(tarjeta se acerca aqu\u00ed)",
         fc=COLOR['warning'], fs=8)

draw_arrow(ax, (box_x + 7.0, box_y + 4.0), (box_x + 7.0, box_y + 4.2), color=COLOR['warning'])

# Cableado RC522 <-> Pi
draw_arrow(ax, (box_x + 3.8, box_y + 2.9), (box_x + 5.6, box_y + 3.1),
           text="7 cables Dupont", color=COLOR['neutral'], curve=0.15)

ax.text(box_x + box_w/2, box_y - 0.35,
        "Nota: mantener el RC522 alejado de superficies met\u00e1licas (reduce el alcance de lectura).",
        ha='center', fontsize=8.3, style='italic', color=COLOR['neutral'])

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_12_0.png)
    


### 3.4 Procedimiento de montaje

1. **Preparar la Raspberry Pi.** Instalar la microSD con el sistema operativo ya flasheado y probado (Raspberry Pi OS) antes de montarla en la caja, para evitar desmontajes posteriores.
2. **Fijar la Raspberry Pi en el gabinete**, dejando el header GPIO accesible y sin obstrucciones para el cableado. Orientar la Pi de forma que los puertos USB/Ethernet queden alineados con las aberturas del case.
3. **Cablear el RC522 según la tabla de la sección 3.1**, cuidando que cada conector Dupont quede firmemente insertado (una conexión floja en `SCK` o `MOSI` es la causa más común de lecturas intermitentes).
4. **Ubicar el RC522 lejos de superficies metálicas** (tornillería, chasis metálico, fuente de alimentación) — el metal cercano a la antena PCB reduce notablemente el alcance de lectura (de varios centímetros a prácticamente cero).
5. **Orientar la cara de la antena del RC522 hacia la tapa frontal o punto de acercamiento** donde el usuario presentará la tarjeta, dejando idealmente 0.5–1 cm de espacio libre entre la antena y la superficie externa de la caja (evitar plástico demasiado grueso, que también atenúa la señal).
6. **Dar tensión mecánica a los cables** (pequeñas bridas o un poco de cinta) para que no se desconecten por vibración o al mover el gabinete.
7. **Conectar la alimentación al final**, una vez verificado todo el cableado — primero con la Pi apagada, revisar continuidad y polaridad, y solo entonces energizar.
8. **Verificar el servicio `rfid-reader.service`** (`systemctl status rfid-reader`) y hacer una lectura de prueba con una tarjeta conocida antes de cerrar definitivamente la caja.

> Si el sistema evoluciona hacia el modo kiosco con pantalla física (contemplado en el diagrama de arquitectura de la sección 2), esta misma disposición interna se mantiene: solo se añade la pantalla conectada al dashboard vía HTTP local, sin cambios en el cableado del RC522.


<a id="4"></a>
## 4. Firmware y lógica del lector RFID
[[Volver a la tabla de contenido]](#toc)

El script `rfid_reader.py` corre como servicio systemd (`rfid-reader.service`, usuario `root` por requerir acceso a GPIO) en un ciclo continuo de *polling* cada 150 ms, con un *debounce* de 2 segundos para evitar lecturas duplicadas de la misma tarjeta.


```python
fig, ax = new_canvas(12, 9, "Lógica de decisión — rfid_reader.py")

y0 = 8.0
p1 = draw_box(ax, (4.2, y0), 3.6, 0.8, "Tarjeta detectada\n(UID leído)", fc=COLOR['primary'])

y1 = 6.7
p2 = draw_box(ax, (4.2, y1), 3.6, 0.8, "¿Modo administrador\nactivo?", fc=COLOR['warning'])
draw_arrow(ax, (p1[0], y0), (p2[0], y1 + 0.8))

p_admin = draw_box(ax, (9.3, y1), 2.8, 0.8, "Escribe UID en\n/run/rfid-shared/\n(no se registra)", fc=COLOR['neutral'])
draw_arrow(ax, (p2[0] + 1.8, y1 + 0.4), (9.3, y1 + 0.4), "sí", color=COLOR['warning'])

y2 = 5.4
p3 = draw_box(ax, (4.2, y2), 3.6, 0.8, "¿UID existe en\ntabla tarjetas?", fc=COLOR['secondary'])
draw_arrow(ax, (p2[0], y1), (p3[0], y2 + 0.8), "no")

p_desconocido = draw_box(ax, (0.2, y2), 3.2, 0.8, "Registra evento\n'rebote' — UID no\nregistrado", fc=COLOR['danger'])
draw_arrow(ax, (p3[0] - 1.8, y2 + 0.4), (3.4, y2 + 0.4), "no", color=COLOR['danger'])

y3 = 4.1
p4 = draw_box(ax, (4.2, y3), 3.6, 0.8, "¿Tarjeta activa Y\nestudiante activo?", fc=COLOR['secondary'])
draw_arrow(ax, (p3[0], y2), (p4[0], y3 + 0.8), "sí")

p_inactiva = draw_box(ax, (9.3, y3), 2.8, 0.8, "Registra evento\n'rebote' — tarjeta o\nestudiante inactivo", fc=COLOR['danger'])
draw_arrow(ax, (p4[0] + 1.8, y3 + 0.4), (9.3, y3 + 0.4), "no", color=COLOR['danger'])

y4 = 2.8
p5 = draw_box(ax, (4.2, y4), 3.6, 0.8, "¿Ya se registró\n'aceptado' hoy?", fc=COLOR['secondary'])
draw_arrow(ax, (p4[0], y3), (p5[0], y4 + 0.8), "sí")

y5 = 1.5
p6 = draw_box(ax, (4.2, y5), 3.6, 0.9, "Registra evento\n'aceptado'\nAcceso permitido", fc=COLOR['success'])
draw_arrow(ax, (p5[0], y4), (p6[0], y5 + 0.9), "no")

p_yaesc = draw_box(ax, (9.3, y5), 2.8, 0.9, "Registra evento\n'ya_escaneado'\n(n-ésima vez hoy)", fc=COLOR['warning'])
draw_arrow(ax, (p5[0] + 1.8, y4 + 0.4), (9.3, y5 + 0.6), "sí", color=COLOR['warning'])

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_15_0.png)
    


**Parámetros clave del lector:**

| Parámetro | Valor | Propósito |
|---|---|---|
| `POLL_S` | 0.15 s | Frecuencia de sondeo del lector |
| `DEBOUNCE_S` | 2 s | Evita registrar la misma tarjeta varias veces en una sola pasada |
| `SPI_SPEED` | 1,000,000 Hz | Velocidad de comunicación SPI con el RC522 |
| Modo simulación | Automático | Si no detecta hardware (`mfrc522`/`RPi.GPIO`), corre en espera sin fallar — útil en desarrollo |

**Comunicación con el módulo administrativo:** cuando existe el archivo de señal
`/run/rfid-shared/rfid_admin_mode`, el lector cambia de modo: en vez de registrar asistencia, escribe el UID leído (con bloqueo exclusivo `flock`) en `/run/rfid-shared/rfid_admin_uid`, para que el panel CRUD lo capture al dar de alta una tarjeta nueva.

### 4.1 Explicación bloque por bloque del código (`rfid_reader.py`)

**Inicialización y detección de hardware**

```python
try:
    from mfrc522 import MFRC522
    import RPi.GPIO as GPIO
    RFID_OK = True
except ImportError:
    RFID_OK = False
```

Si las librerías `mfrc522`/`RPi.GPIO` no están disponibles en el entorno (por ejemplo, ejecutando el script fuera de la Raspberry Pi), `RFID_OK` queda en `False`. Esto determina qué rama del `main()` se ejecuta — ver §4.4.

**Detección de tarjeta y lectura de UID (`leer_uid`)**

```python
def leer_uid(reader) -> str | None:
    status, _ = reader.MFRC522_Request(reader.PICC_REQIDL)
    if status != reader.MI_OK:
        return None
    status, uid_bytes = reader.MFRC522_Anticoll()
    if status != reader.MI_OK or not uid_bytes:
        return None
    uid_int = 0
    for b in uid_bytes[:4]:
        uid_int = (uid_int << 8) | b
    return str(uid_int)
```

| Línea | Qué hace |
|---|---|
| `MFRC522_Request(PICC_REQIDL)` | Pregunta al chip si hay alguna tarjeta en estado *idle* dentro del rango. Retorna `None` de inmediato si no hay tarjeta — se ejecuta decenas de veces por segundo (cada `POLL_S`). |
| `MFRC522_Anticoll()` | Ejecuta el procedimiento de **anticolisión** de ISO14443A (ver §4.2), que identifica una tarjeta única aunque haya varias en el rango. Retorna los bytes crudos del UID. |
| `uid_int = (uid_int << 8) \| b` | Combina los primeros 4 bytes del UID en un solo entero mediante desplazamiento de bits, y lo convierte a `string` — así queda almacenado y comparado en `rfid.db`. |

**Debounce**

```python
if uid_s == ultimo_uid and (ahora - ultimo_t) < DEBOUNCE_S:
    time.sleep(POLL_S)
    continue
```

Si la misma tarjeta se lee de nuevo dentro de `DEBOUNCE_S` (2 s) desde su última lectura, se ignora — evita que una sola pasada de tarjeta genere múltiples registros mientras el usuario la retira del lector.

**Modo administrador**

```python
if _modo_admin_activo():
    _notificar_admin_scan(uid_s)
    log.info(f"[ADMIN-SCAN   ]  UID: {uid_s}  → capturado (sin registro)")
    time.sleep(POLL_S)
    continue
```

`_modo_admin_activo()` revisa si existe el archivo de señal `/run/rfid-shared/rfid_admin_mode`, creado por el panel CRUD cuando un administrador va a dar de alta una tarjeta nueva. Mientras ese archivo existe, el lector **no** registra asistencia: solo captura el UID y lo escribe (con bloqueo exclusivo `fcntl.flock`) en
`/run/rfid-shared/rfid_admin_uid`, para que el CRUD lo lea y lo asocie al estudiante en alta. Así se comunican dos procesos independientes (`root` y `admin`) sin tocar la base de datos directamente.

**Inserción en base de datos (`procesar`)**

Fuera de modo admin, cada UID pasa por `procesar()`, que resuelve uno de cuatro escenarios (ver el diagrama de decisión más arriba en esta sección) y siempre inserta un registro en `registros_asistencia`:

1. UID no encontrado en `tarjetas` → `rebote`, `"UID no registrado"`.
2. Tarjeta inactiva o estudiante inactivo → `rebote`, motivo correspondiente.
3. Ya existe un `aceptado` ese mismo día para ese UID → `ya_escaneado`, con contador de reincidencia.
4. Primer escaneo válido del día → `aceptado`.

Todas las inserciones usan parámetros preparados (`?`), sin concatenación de strings — evita inyección SQL.

**Reinicio automático del chip**

```python
if time.time() - ultima_lectura_ok > REINIT_TIMEOUT:
    reinicios += 1
    reader.MFRC522_Init()
```

Si pasan más de `REINIT_TIMEOUT` (8 s) sin que el propio hardware responda (no se refiere a la ausencia de tarjetas, sino a fallos de comunicación con el chip), se reinicializa el RC522 — compensa fallos intermitentes de SPI, comunes en módulos económicos.

---

### 4.2 Protocolo MIFARE — por qué no se usa autenticación de sector

Las tarjetas MIFARE Classic organizan su memoria en **sectores protegidos** por llaves criptográficas (Key A / Key B). Leer o escribir *datos* dentro de esos sectores requiere autenticación (`MFRC522_Auth`).

Este sistema **no lee ni escribe datos dentro de la tarjeta** — únicamente necesita el **UID de fábrica**, que se obtiene con el procedimiento de *Request* + *Anticollision* durante la fase de **selección** de la tarjeta, la cual ocurre **antes** de cualquier autenticación de sector en el protocolo ISO14443A. El flujo se detiene justo ahí porque no hay necesidad de autenticar si nunca se va a acceder a un bloque de datos.

**Implicación de seguridad:** en tarjetas MIFARE Classic estándar el UID es de solo lectura, pero existen tarjetas regrabables ("*magic cards*") diseñadas para clonar UIDs arbitrarios. Es decir, el sistema no verifica una identidad criptográficamente firmada, sino un número de serie — la seguridad del control de acceso descansa en que la lista de UIDs válidos en `rfid.db` esté bien controlada administrativamente, **no** en una propiedad criptográfica de la tarjeta. Es un nivel de seguridad razonable para control de asistencia (bajo riesgo), pero insuficiente si en el futuro el sistema protegiera activos críticos — en ese caso, la vía sería migrar a MIFARE DESFire (autenticación AES) u otro esquema con autenticación mutua.

---

### 4.3 Ejemplos de logs del lector

Formato base: `HH:MM:SS  NIVEL    mensaje`.

**Arranque con hardware detectado:**
```
10:15:02  INFO     Hardware RC522 detectado
10:15:02  INFO     === Lector RFID iniciado ===
10:15:02  INFO     DB: /home/admin/rfid-system/shared/rfid.db
10:15:02  INFO     Archivo señal admin: /run/rfid-shared/rfid_admin_mode
10:15:02  INFO     Listo — acerca una tarjeta...
```

**Tarjeta válida, primer escaneo del día:**
```
10:16:44  INFO     [ACEPTADO    ]  Juan Pérez                     UID: 3184920157
```

**Tarjeta ya escaneada antes ese mismo día:**
```
10:20:11  INFO     [YA_ESCANEADO]  Juan Pérez                     UID: 3184920157
```

**UID no registrado en el sistema:**
```
10:21:03  INFO     [REBOTE      ]  DESCONOCIDO                    UID: 2200981144
```

**Tarjeta o estudiante inactivo:**
```
10:22:15  INFO     [REBOTE      ]  María López                    UID: 3184920200
```

**Escaneo en modo administrador (alta de tarjeta nueva):**
```
10:25:40  INFO     [ADMIN-SCAN   ]  UID: 3184920321  → capturado (sin registro)
```

**Sin actividad del hardware — reinicio automático del chip:**
```
10:30:12  WARNING  Sin actividad del lector (8s), reinicializando RC522… (reinicio #1)
```

**Sin hardware disponible (modo espera — ver §4.4):**
```
10:15:02  WARNING  mfrc522 / RPi.GPIO no disponibles — modo simulación
10:15:02  WARNING  Sin hardware RFID — proceso en espera (simulación).
```

---

### 4.4 Modo simulación (sin hardware)

**Estado actual del código:** cuando `mfrc522`/`RPi.GPIO` no se pueden importar, `RFID_OK` queda en `False` y `main()` entra directo en un loop de espera pasivo:

```python
if not RFID_OK:
    log.warning("Sin hardware RFID — proceso en espera (simulación).")
    while True:
        time.sleep(60)
```

Es importante ser precisos: esto **no simula lecturas de tarjetas**, solo evita que el proceso truene por falta de hardware y lo deja "vivo" sin hacer
nada — para efectos prácticos, el lector queda inactivo mientras tanto. **Cómo probar la lógica de negocio sin hardware real:** la función que vale
la pena probar de forma aislada es `procesar()`, ya que ahí vive toda la lógica de aceptado/rebote/ya_escaneado y no depende del hardware en absoluto — solo de un UID (`string`) y acceso a `rfid.db`:

```bash
cd shared
python3 -c "
from rfid_reader import procesar
resultado = procesar('3184920157')  # UID de prueba, debe existir en tarjetas
print(resultado)
"
```

Esto ejecuta exactamente la misma lógica que correría el lector real ante una tarjeta física, sin necesitar el RC522 conectado.

**Cambiar entre modo real y espera pasiva** no requiere ninguna bandera: es automático según si `mfrc522`/`RPi.GPIO` están instalados en el entorno.
Para forzar el modo hardware en la propia Pi basta con tener el módulo conectado y las dependencias instaladas (incluidas en `requirements.txt`).

> **Nota para trabajo futuro:** si se necesita probar el flujo completo (loop, debounce, colores en consola) sin tarjeta física, una mejora razonable sería agregar un modo `--simulate` que acepte UIDs por teclado en vez de leer el RC522 — actualmente esa opción **no existe** en el código; el modo sin hardware únicamente mantiene el proceso vivo.

<a id="5"></a>
## 5. Software — estructura y servicios
[[Volver a la tabla de contenido]](#toc)

### 5.1 Árbol de directorios completo — propósito de cada archivo

```text
/home/admin/rfid-system/
├── shared/
│   ├── rfid.db                 # Base de datos SQLite (única fuente de verdad, modo WAL)
│   ├── rfid_reader.py          # Lector RFID: polling del RC522, debounce, modo admin,
│   │                           #   inserción de asistencia (ver sección 4)
│   ├── init_db.py              # Script de inicialización — crea las 3 tablas
│   │                           #   (estudiantes, tarjetas, registros_asistencia) y
│   │                           #   9 índices; se ejecuta una sola vez al desplegar
│   ├── network_watchdog.sh     # Ping periódico a 8.8.8.8/1.1.1.1; si falla 3 veces
│   │                           #   seguidas, reconecta a la red Wi-Fi conocida con
│   │                           #   mejor señal, o reinicia NetworkManager si ninguna
│   │                           #   red conocida está visible
│   ├── reader.log               # Log del lector (consola + archivo, ver §4.3)
│   ├── network_watchdog.log     # Log del watchdog de red
│   └── backups/                 # Respaldos de rfid.db generados bajo demanda
│                                 #   desde el panel CRUD (rfid_backup_YYYYMMDD_HHMMSS.db)
├── crud/
│   ├── app_crud.py             # API REST + panel administrativo (Flask). Expone
│   │                           #   los endpoints de la sección 7: CRUD de estudiantes
│   │                           #   y tarjetas, exportación CSV, gestión de servicios
│   │                           #   systemd, auditoría — protegido con Basic Auth
│   │                           #   global vía @app.before_request
│   ├── rfid_software_admin     # Módulo de soporte de app_crud.py: administra
│   │                           #   servicios systemd (start/stop/restart vía
│   │                           #   subprocess/SSH) y la base de datos (respaldo,
│   │                           #   restauración, purga filtrada por fecha/carrera/
│   │                           #   semestre/grupo)
│   ├── static/fotos/           # Fotografías de estudiantes subidas desde el CRUD
│   └── templates/
│       └── crud_dashboard.html  # Interfaz web del panel administrativo (una sola
│                                 #   plantilla, consume los endpoints de app_crud.py)
├── dashboard/
│   ├── app_dashboard.py        # Servidor Flask de solo lectura: calcula métricas
│   │                           #   del día (conteos por tipo de evento, top UIDs,
│   │                           #   distribución por hora) consultando rfid.db —
│   │                           #   ver sección 9 del notebook
│   └── templates/
│       └── dashboard.html       # Vista del dashboard en tiempo real, renderizada
│                                 #   en pantalla kiosco vía kiosk.service
├── venv/                       # Entorno virtual Python (no versionado en git)
├── requirements.txt            # Dependencias congeladas (pip freeze)
├── .env                        # Variables de entorno reales — credenciales,
│                                #   ALLOWED_SUBNET, RFID_SSH_PASSWORD (no versionado)
└── .env.example                # Plantilla de variables de entorno sin valores
                                 #   reales, sí versionada, para replicar el setup
```

*(fuera de `rfid-system/`, en `~/kiosk.sh`, vive el script que lanza Chromium en modo kiosco — invocado por `kiosk.service`, ver §5.2)*

---

### 5.2 Servicios systemd — contenido completo y explicación de directivas

**`rfid-reader.service`**
```ini
[Unit]
Description=RFID Reader Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/admin/rfid-system/shared
ExecStart=/home/admin/rfid-system/venv/bin/python3 /home/admin/rfid-system/shared/rfid_reader.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

| Directiva | Explicación |
|---|---|
| `After=network.target` | Espera a que la red esté disponible antes de arrancar (aunque el lector no depende de red directamente, mantiene el orden de arranque consistente con los demás servicios). |
| `Type=simple` | El proceso principal de `ExecStart` **es** el servicio — systemd no espera ninguna señal de "listo", lo considera activo en cuanto arranca. |
| `User=root` | Corre como `root` porque el acceso a GPIO/SPI del RC522 lo requiere en esta configuración. Es el único de los 5 servicios que corre con privilegios completos — vale la pena tenerlo presente como superficie de riesgo si el script llegara a tener una vulnerabilidad. |
| `WorkingDirectory` | Directorio desde el que se ejecuta — relevante porque `rfid_reader.py` resuelve rutas relativas (como `rfid.db`) a partir de su propia ubicación (`os.path.dirname(__file__)`), no de este directorio, pero es buena práctica mantenerlos alineados. |
| `ExecStart` | Usa el intérprete de Python **del entorno virtual** (`venv/bin/python3`), no el del sistema — así se usan las versiones exactas de `mfrc522`, `RPi.GPIO`, etc. fijadas en `requirements.txt`. |
| `Restart=always` / `RestartSec=5` | Si el proceso termina (por cualquier razón, incluyendo un crash), systemd lo reinicia automáticamente a los 5 segundos — da resiliencia sin intervención manual. |

**`rfid-crud.service`**
```ini
[Unit]
Description=RFID CRUD Service
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/rfid-system/crud
EnvironmentFile=/home/admin/rfid-system/.env
Nice=5
ExecStart=/home/admin/rfid-system/venv/bin/gunicorn -w 2 --threads 2 -b 0.0.0.0:5001 --timeout 120 app_crud:app
Restart=always
RestartSec=5
KillMode=process
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

| Directiva | Explicación |
|---|---|
| `User=admin` | A diferencia del lector, este servicio corre con el usuario normal `admin`, no `root` — no necesita acceso a hardware, solo a la base de datos y (para las acciones de administración de servicios) a `sudo` puntual. |
| `EnvironmentFile=/home/admin/rfid-system/.env` | Carga las variables de `.env` (credenciales, `ALLOWED_SUBNET`, `RFID_SSH_PASSWORD`) como variables de entorno del proceso — así el código las lee con `os.environ.get()` sin tenerlas escritas en el propio script. |
| `Nice=5` | Baja ligeramente la prioridad de planificación del proceso frente a otros procesos del sistema (valor por defecto es 0; rango típico -20 a 19) — evita que el panel administrativo compita en igualdad de condiciones por CPU con el lector, que es más sensible a temporización. |
| `ExecStart` (Gunicorn) | Ver el detalle completo en §5.4. |
| `KillMode=process` | Al detener el servicio, systemd solo mata el proceso principal de Gunicorn, no todo el *cgroup* — evita que se lleve por delante procesos hijos relacionados con sesiones SSH abiertas por el mismo usuario, si los hubiera. |
| `TimeoutStopSec=10` | Da hasta 10 segundos para que el proceso termine ordenadamente tras recibir la señal de parada antes de forzarlo — suficiente para que Gunicorn cierre conexiones en curso sin cortar peticiones a la mitad de forma abrupta. |

**`rfid-dashboard.service`**
```ini
[Unit]
Description=RFID Dashboard Service
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/rfid-system/dashboard
Nice=5
ExecStart=/home/admin/rfid-system/venv/bin/gunicorn -w 2 --threads 2 -b 127.0.0.1:5000 app_dashboard:app
Restart=always
RestartSec=5
KillMode=process
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

Misma lógica que `rfid-crud.service` en la mayoría de las directivas. Dos diferencias notables:
- **`-b 127.0.0.1:5000`** (vs `0.0.0.0:5001` en el CRUD): el dashboard solo escucha en *localhost* — no es accesible desde otros equipos de la red, solo desde la propia Raspberry Pi (por ejemplo, el navegador en modo kiosco). Es una superficie de exposición deliberadamente menor que la del CRUD.
- **Sin `EnvironmentFile`**: el dashboard no necesita las credenciales del `.env` porque no expone autenticación propia ni acciones administrativas, solo lectura de métricas.

**`kiosk.service`**
```ini
[Unit]
Description=Dashboard Kiosk
After=rfid-dashboard.service network.target

[Service]
Type=simple
User=root
Environment=DISPLAY=:0
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/xinit /home/admin/kiosk.sh -- :0 vt1 -nocursor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

| Directiva | Explicación |
|---|---|
| `After=rfid-dashboard.service` | Se asegura de arrancar **después** del dashboard — si Chromium abriera antes de que Flask esté escuchando, mostraría un error de conexión. |
| `Environment=DISPLAY=:0` | Define el display X sobre el que va a dibujar — necesario porque systemd no tiene un entorno gráfico por defecto. |
| `ExecStartPre=/bin/sleep 5` | Espera adicional de 5 segundos antes de arrancar, como margen de seguridad extra sobre el `After=` (que solo garantiza orden de arranque, no que el servidor Flask ya esté aceptando conexiones). |
| `ExecStart` | `xinit` levanta una sesión X mínima y ejecuta `kiosk.sh` dentro de ella, en la terminal virtual `vt1`, sin cursor visible (`-nocursor`) — apropiado para una pantalla dedicada sin interacción de mouse/teclado. |
| `User=root` | Necesario para poder inicializar la sesión X directamente desde systemd sin un login gráfico previo. |

**`network-watchdog.service`**
```ini
[Unit]
Description=Watchdog de conectividad Wi-Fi
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/bin/bash /home/admin/rfid-system/shared/network_watchdog.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

| Directiva | Explicación |
|---|---|
| `Wants=NetworkManager.service` | A diferencia de `After` (que solo define orden), `Wants` intenta **iniciar** `NetworkManager` si no estuviera activo — dependencia declarada explícitamente porque este script no tiene sentido sin él. |
| `RestartSec=10` (vs 5 en los demás) | Da un poco más de margen entre reintentos, apropiado para un script que ya maneja sus propios reintentos internos (`CHECK_INTERVAL`, `FAIL_THRESHOLD`) en un loop infinito — si el propio script termina inesperadamente, no tiene sentido reiniciarlo tan agresivamente como un servidor web. |

---

### 5.3 Habilitar, iniciar y verificar cada servicio

Tras crear o modificar cualquier archivo `.service` en `/etc/systemd/system/`, primero hay que recargar la configuración de systemd:

```bash
sudo systemctl daemon-reload
```

**Habilitar** (arranque automático en cada boot) y **arrancar** un servicio:

```bash
sudo systemctl enable rfid-reader
sudo systemctl start rfid-reader
```

(`enable` y `start` son independientes: `enable` sin `start` solo lo deja programado para el próximo reinicio; `start` sin `enable` lo arranca ahora pero no sobrevive a un reinicio del sistema.)

**Verificar estado:**

```bash
sudo systemctl status rfid-reader
```

Muestra si está `active (running)` o `failed`, el PID, uso de memoria, y las últimas líneas de log — suficiente para un diagnóstico rápido.

**Ver logs en vivo** (útil para depurar mientras se prueba algo):

```bash
sudo journalctl -u rfid-reader -f
```

`-f` sigue el log en tiempo real (como `tail -f`). Sin `-f`, muestra el historial completo disponible; se puede acotar con `-n 50` para las últimas 50 líneas, o `--since "10 min ago"`.

**Reiniciar** tras un cambio de código (no de configuración systemd — para eso hace falta `daemon-reload` primero):

```bash
sudo systemctl restart rfid-crud
```

**Repetir para cada servicio** (`rfid-reader`, `rfid-crud`, `rfid-dashboard`, `kiosk`, `network-watchdog`) según cuáles estén instalados en el equipo.

---

### 5.4 Configuración de Gunicorn

Ni `rfid-crud` ni `rfid-dashboard` usan un archivo `gunicorn.conf.py` separado — los parámetros van directo en la línea `ExecStart` de cada `.service`:

```bash
# rfid-crud
gunicorn -w 2 --threads 2 -b 0.0.0.0:5001 --timeout 120 app_crud:app

# rfid-dashboard
gunicorn -w 2 --threads 2 -b 127.0.0.1:5000 app_dashboard:app
```

| Parámetro | Valor | Qué hace |
|---|---|---|
| `-w 2` (workers) | 2 procesos | Cantidad de procesos independientes de Gunicorn que atienden peticiones. Cada worker es un proceso completo (no un hilo), con su propia memoria. |
| `--threads 2` | 2 hilos por worker | Dentro de cada worker, hasta 2 peticiones pueden atenderse de forma concurrente sin bloquear una a la otra — útil para peticiones que esperan I/O (como una consulta a SQLite) sin saturar CPU. |
| `-b` (bind) | `0.0.0.0:5001` en CRUD, `127.0.0.1:5000` en dashboard | Dirección y puerto de escucha — ver la diferencia de exposición explicada en §5.2. |
| `--timeout 120` | 120 segundos (solo en CRUD) | Tiempo máximo que Gunicorn espera a que un worker responda antes de considerarlo "colgado" y reiniciarlo. Un valor más alto que el default (30s) tiene sentido en el CRUD porque incluye operaciones potencialmente lentas: exportaciones CSV grandes (`stream_with_context`), respaldos de base de datos, o comandos systemd ejecutados vía subprocess/SSH que pueden tardar. El dashboard no define `--timeout` explícito porque sus consultas son agregaciones simples, más rápidas y predecibles — usa el valor por defecto de Gunicorn (30s). |

**Sobre el número de workers/threads elegido:** los comentarios dejados en los propios archivos `.service` (`# Reducir workers de 4 a 2, agregar threads`) indican que este valor fue ajustado deliberadamente a la baja respecto a una configuración anterior (probablemente `-w 4` sin threads) — consistente con correr en una Raspberry Pi 4, donde 4 workers completos (cada uno con su propio intérprete de Python cargado en memoria) compiten más agresivamente por los recursos limitados del equipo que 2 workers con threads, que comparten memoria dentro de cada proceso. `Nice=5` en ambos servicios refuerza esta misma prioridad: dejar más margen de CPU disponible para el lector RFID, que es el proceso más sensible a temporización de los cinco.

**Para probar Gunicorn manualmente** (fuera de systemd, útil al depurar):

```bash
cd crud
source ../venv/bin/activate
gunicorn -w 2 --threads 2 -b 0.0.0.0:5001 --timeout 120 app_crud:app
```

Esto corre en primer plano — `Ctrl+C` para detenerlo. Sirve para ver errores de arranque directo en la terminal, sin pasar por `journalctl`.

<a id="6"></a>
## 6. Base de datos
[[Volver a la tabla de contenido]](#toc)

**Motor:** SQLite en modo **WAL** (*Write-Ahead Logging*), que permite lecturas concurrentes sin bloquear las escrituras — importante porque el lector escribe constantemente mientras el dashboard y el CRUD leen en paralelo.

Esta sección incluye el script SQL completo, la explicación de las relaciones entre tablas, consultas de referencia, una guía de mantenimiento y una proyección de crecimiento de la base de datos.

---

### 6.1 Script SQL completo de creación (`init_db.py`)

El script se ejecuta **una sola vez** al desplegar el sistema (o al reconstruir la base desde cero). Usa `CREATE TABLE IF NOT EXISTS` para poder ejecutarse de forma segura más de una vez sin destruir datos existentes.

```sql
-- =========================================================
-- init_db.py — esquema completo de rfid.db
-- =========================================================

-- Activa el cumplimiento de llaves foráneas en esta conexión.
-- SQLite las ignora por defecto si no se activa explícitamente.
PRAGMA foreign_keys = ON;

-- Modo WAL: permite lecturas concurrentes (dashboard, CRUD)
-- mientras el lector RFID inserta registros de asistencia.
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------
-- Tabla: estudiantes
-- Fuente de verdad de la identidad de cada alumno.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS estudiantes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,  -- PK interno, autoincremental
    nombre            TEXT    NOT NULL,                   -- nombre(s) de pila
    apellido_paterno  TEXT    NOT NULL,
    apellido_materno  TEXT,                                -- opcional
    matricula         TEXT    NOT NULL UNIQUE,             -- clave institucional, única por definición
    carrera           TEXT,                                -- ej. "Ing. en TIC"
    semestre          INTEGER,                             -- 1–12, según programa
    grupo             TEXT,                                -- ej. "A", "B", "801"
    correo            TEXT,                                -- correo institucional o personal
    estado            TEXT    NOT NULL DEFAULT 'activo'
                        CHECK (estado IN ('activo', 'inactivo')),  -- baja lógica, nunca se borra el registro
    foto              TEXT,                                -- ruta relativa dentro de crud/static/fotos/
    creado_en         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------------------------------------------------------
-- Tabla: tarjetas
-- Vincula un UID físico (RFID) con un estudiante.
-- Relación 1 estudiante → N tarjetas (permite reposición
-- de tarjeta perdida sin perder historial).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tarjetas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT    NOT NULL UNIQUE,               -- UID leído por el RC522 (decimal, como string)
    id_estudiante   INTEGER,                                -- FK → estudiantes.id (nullable)
    activa          INTEGER NOT NULL DEFAULT 1
                        CHECK (activa IN (0, 1)),           -- 1 = habilitada, 0 = revocada (extravío, baja)
    asignada_en     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id)
        ON DELETE SET NULL                                  -- si se borra el estudiante, la tarjeta no se pierde
);

-- ---------------------------------------------------------
-- Tabla: registros_asistencia
-- Tabla de mayor crecimiento: un renglón por cada evento
-- de lectura (aceptado / rebote / ya_escaneado).
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS registros_asistencia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante   INTEGER,                                -- FK → estudiantes.id (nullable)
    uid             TEXT    NOT NULL,                        -- se conserva aunque la tarjeta se elimine
    timestamp       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),  -- fecha y hora exactas
    fecha_dia       TEXT    NOT NULL,                        -- 'YYYY-MM-DD', derivado del timestamp
    tipo_evento     TEXT    NOT NULL
                        CHECK (tipo_evento IN ('aceptado', 'rebote', 'ya_escaneado')),
    mensaje         TEXT,                                    -- motivo legible (ej. "UID no registrado")
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id)
        ON DELETE SET NULL                                   -- el historial de asistencia nunca se borra
);

-- ---------------------------------------------------------
-- Tabla: audit_log
-- Bitácora de acciones administrativas sensibles.
-- Sin FK hacia otras tablas: es un registro independiente
-- de "quién hizo qué" en el panel CRUD.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    ip          TEXT,                                        -- IP de origen de la petición
    accion      TEXT    NOT NULL,                             -- ej. "restart_service", "delete_estudiante"
    detalle     TEXT,                                         -- parámetros/contexto de la acción
    resultado   TEXT    NOT NULL
                        CHECK (resultado IN ('exito', 'fallo'))
);

-- ---------------------------------------------------------
-- Índices (9 en total) — ver §6.2 para el detalle de cada uno
-- ---------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tarjetas_uid              ON tarjetas(uid);
CREATE INDEX IF NOT EXISTS idx_tarjetas_id_estudiante     ON tarjetas(id_estudiante);
CREATE INDEX IF NOT EXISTS idx_estudiantes_matricula      ON estudiantes(matricula);
CREATE INDEX IF NOT EXISTS idx_estudiantes_estado         ON estudiantes(estado);
CREATE INDEX IF NOT EXISTS idx_estudiantes_semestre       ON estudiantes(semestre);
CREATE INDEX IF NOT EXISTS idx_registros_fecha_dia        ON registros_asistencia(fecha_dia);
CREATE INDEX IF NOT EXISTS idx_registros_tipo_evento      ON registros_asistencia(tipo_evento);
CREATE INDEX IF NOT EXISTS idx_registros_fecha_evento     ON registros_asistencia(fecha_dia, tipo_evento);
CREATE INDEX IF NOT EXISTS idx_registros_estudiante_evento ON registros_asistencia(id_estudiante, tipo_evento);
```

---

### 6.2 Explicación de índices

| Índice | Columnas | Consulta que acelera |
|---|---|---|
| `idx_tarjetas_uid` | `uid` | Búsqueda del lector al validar cada lectura (`SELECT ... WHERE uid = ?`) — es la consulta más frecuente del sistema, ejecutada en cada `POLL_S`. |
| `idx_tarjetas_id_estudiante` | `id_estudiante` | Listar las tarjetas de un estudiante en el panel CRUD. |
| `idx_estudiantes_matricula` | `matricula` | Búsqueda/validación de unicidad al dar de alta o editar un estudiante. |
| `idx_estudiantes_estado` | `estado` | Filtrar estudiantes activos/inactivos en listados y exportaciones. |
| `idx_estudiantes_semestre` | `semestre` | Reportes filtrados por semestre. |
| `idx_registros_fecha_dia` | `fecha_dia` | Consultas del dashboard limitadas "al día en curso" y exportación de asistencia por rango de fechas. |
| `idx_registros_tipo_evento` | `tipo_evento` | Conteo de eventos por tipo (aceptado/rebote/ya_escaneado) en el dashboard. |
| `idx_registros_fecha_evento` | `(fecha_dia, tipo_evento)` | Índice compuesto: la consulta más pesada del dashboard (conteo por tipo, filtrado por día) resuelve en un solo acceso al índice sin *table scan*. |
| `idx_registros_estudiante_evento` | `(id_estudiante, tipo_evento)` | "¿Ya se registró `aceptado` hoy para este estudiante?" — se ejecuta en cada lectura válida del RC522, es la ruta crítica de latencia del lector. |

> Sin estos índices, cada lectura de tarjeta obligaría a un recorrido secuencial de `registros_asistencia`, que crece indefinidamente (ver §6.6) — el costo de la consulta pasaría de O(log n) a O(n) conforme avanza el semestre.

---

### 6.3 Relaciones entre tablas

```
estudiantes (1) ──────< (N) tarjetas
     │                        │
     │                        │
     └────────< (N) registros_asistencia
                              
audit_log  (independiente, sin FK)
```

**`tarjetas.id_estudiante → estudiantes.id` (`ON DELETE SET NULL`)**
Un estudiante puede tener varias tarjetas a lo largo del tiempo (reposición por extravío), pero cada tarjeta pertenece a un solo estudiante. Si el estudiante se elimina físicamente de la tabla `estudiantes` (no solo se marca `inactivo`), la tarjeta **no se borra**: su columna `id_estudiante` pasa a `NULL`, quedando como una tarjeta huérfana identificable, en vez de desaparecer silenciosamente.

**`registros_asistencia.id_estudiante → estudiantes.id` (`ON DELETE SET NULL`)**
Mismo criterio, aplicado al historial de asistencia: es la relación más importante de proteger, porque `registros_asistencia` es evidencia histórica (útil para auditorías, reportes de servicio social, litigios administrativos, etc.). Borrar en cascada destruiría evidencia; `SET NULL` conserva el renglón (con su `uid`, `timestamp` y `tipo_evento` intactos) aunque pierda la referencia directa al estudiante.

**¿Por qué no se usa `ON DELETE CASCADE` en este esquema?**
`ON DELETE CASCADE` habría sido la alternativa natural si el objetivo fuera mantener la base de datos "limpia" borrando automáticamente todo lo relacionado con un estudiante eliminado (sus tarjetas y todo su historial de asistencia desaparecerían junto con él). Se descartó deliberadamente por dos razones:

1. **Valor probatorio del historial.** `registros_asistencia` documenta hechos ocurridos (una tarjeta pasó por el lector en tal fecha/hora) — es un log, no un dato editable, y borrarlo en cascada eliminaría evidencia que podría necesitarse después de que un estudiante cause baja.
2. **Recuperación ante errores administrativos.** Si un estudiante se elimina por error, con `SET NULL` sus registros de asistencia siguen existiendo (identificables por `uid`) y pueden reconciliarse manualmente; con `CASCADE` esa información se perdería de forma irreversible en el mismo instante del `DELETE`.

En términos prácticos, este sistema prefiere **bajas lógicas** (`estudiantes.estado = 'inactivo'`) sobre `DELETE` físico — la columna `estado` existe justamente para eso. El `DELETE` físico de un estudiante es una operación excepcional (ej. registro duplicado por error de captura), y para ese caso excepcional `SET NULL` es la opción segura. `CASCADE` sería apropiado en un esquema distinto donde los datos hijos no tuvieran valor una vez eliminado el padre — por ejemplo, si `tarjetas` tuviera una tabla de "notas internas" sin relevancia fuera del contexto de esa tarjeta específica, ahí sí tendría sentido borrarlas en cascada junto con la tarjeta.

---

### 6.4 Consultas SQL de referencia

**a) Insertar un registro de asistencia** (la operación que ejecuta `rfid_reader.py` en cada evento — ver §4.1):

```sql
INSERT INTO registros_asistencia (id_estudiante, uid, timestamp, fecha_dia, tipo_evento, mensaje)
VALUES (?, ?, datetime('now', 'localtime'), date('now', 'localtime'), ?, ?);
```
*(los `?` son parámetros preparados — nunca se concatenan strings del usuario, ver §12.2)*

**b) Consultar el último evento registrado de un estudiante** (útil en el panel CRUD, ficha del estudiante):

```sql
SELECT r.timestamp, r.tipo_evento, r.mensaje, r.uid
FROM registros_asistencia r
WHERE r.id_estudiante = ?
ORDER BY r.timestamp DESC
LIMIT 1;
```

**c) Verificar si un estudiante ya tiene un `aceptado` el día de hoy** (usada por `procesar()` del lector, ver §4.1 y el índice `idx_registros_estudiante_evento`):

```sql
SELECT COUNT(*) AS ya_registrado
FROM registros_asistencia
WHERE id_estudiante = ?
  AND tipo_evento = 'aceptado'
  AND fecha_dia = date('now', 'localtime');
```

**d) Estadísticas diarias del dashboard — conteo por tipo de evento (día en curso):**

```sql
SELECT tipo_evento, COUNT(*) AS total
FROM registros_asistencia
WHERE fecha_dia = date('now', 'localtime')
GROUP BY tipo_evento;
```

**e) Estadísticas diarias — distribución de escaneos por hora** (la consulta detrás de la gráfica de §9):

```sql
SELECT strftime('%H', timestamp) AS hora, COUNT(*) AS escaneos
FROM registros_asistencia
WHERE fecha_dia = date('now', 'localtime')
GROUP BY hora
ORDER BY hora;
```

**f) Top 10 UIDs con más escaneos repetidos en el día** (detección de estudiantes que insisten en pasar la tarjeta ya escaneada):

```sql
SELECT uid, COUNT(*) AS repeticiones
FROM registros_asistencia
WHERE fecha_dia = date('now', 'localtime')
  AND tipo_evento = 'ya_escaneado'
GROUP BY uid
ORDER BY repeticiones DESC
LIMIT 10;
```

**g) Exportar asistencia a CSV, filtrada por rango de fechas** (base de `/api/export/registros`, con `stream_with_context` para no cargar todo en memoria):

```sql
SELECT e.matricula, e.nombre, e.apellido_paterno, e.apellido_materno,
       r.timestamp, r.tipo_evento, r.mensaje
FROM registros_asistencia r
LEFT JOIN estudiantes e ON e.id = r.id_estudiante
WHERE r.fecha_dia BETWEEN ? AND ?
ORDER BY r.timestamp ASC;
```
*(`LEFT JOIN`, no `INNER JOIN`: así se incluyen registros cuyo estudiante fue eliminado — `id_estudiante` en `NULL` — y no desaparecen silenciosamente de la exportación.)*

**h) Exportar el padrón completo de estudiantes a CSV** (base de `/api/export/estudiantes`):

```sql
SELECT matricula, nombre, apellido_paterno, apellido_materno,
       carrera, semestre, grupo, correo, estado
FROM estudiantes
ORDER BY apellido_paterno, apellido_materno, nombre;
```

---

### 6.5 Guía de mantenimiento

**a) Backup manual**

Desde el panel CRUD (`/api/software/database/status` para ver el estado, y el botón de respaldo, que internamente llama a `DatabaseManager.create_backup`), o directamente por línea de comandos en la Raspberry Pi:

```bash
cd /home/admin/rfid-system/shared

# En modo WAL, SQLite mantiene cambios recientes en rfid.db-wal;
# un simple `cp` puede copiar un estado inconsistente si hay escrituras
# en curso. La forma segura es usar el propio comando de respaldo de SQLite:
sqlite3 rfid.db ".backup 'backups/rfid_backup_$(date +%Y%m%d_%H%M%S).db'"
```

El comando `.backup` de la CLI de `sqlite3` (o su equivalente, la API `sqlite3_backup_*` en Python) es *WAL-aware*: hace un checkpoint interno y copia un snapshot consistente, a diferencia de copiar el archivo `.db` con `cp` mientras el proceso lector sigue escribiendo.

El nombre resultante (`rfid_backup_YYYYMMDD_HHMMSS.db`) es el mismo formato validado por expresión regular estricta antes de cualquier restauración (ver §6.2 del documento original) — no renombrar manualmente los archivos de respaldo si se planea restaurarlos después desde el panel CRUD.

**b) Restaurar desde un backup**

⚠️ Esta operación **sobrescribe** la base de datos en producción — debe hacerse con los servicios detenidos.

```bash
# 1. Detener los servicios que escriben o leen la base de datos
sudo systemctl stop rfid-reader rfid-crud rfid-dashboard

# 2. Respaldar el estado actual antes de sobrescribir, por seguridad
cp shared/rfid.db shared/rfid.db.antes_de_restaurar

# 3. Restaurar el archivo elegido
cp shared/backups/rfid_backup_20260815_070000.db shared/rfid.db

# 4. Eliminar archivos WAL/SHM obsoletos del estado anterior, si existen,
#    para evitar que SQLite intente reconciliar un WAL que no corresponde
#    al nuevo archivo principal
rm -f shared/rfid.db-wal shared/rfid.db-shm

# 5. Reiniciar los servicios
sudo systemctl start rfid-reader rfid-crud rfid-dashboard
```

Si el panel CRUD expone la restauración vía `/api/software/database/*`, el mismo procedimiento ocurre internamente (validación del nombre de archivo, checkpoint, sustitución), pero conviene conocer la versión manual para escenarios donde el propio CRUD no esté disponible.

**c) Ejecutar migraciones de esquema (`/api/migrate`)**

El endpoint aplica migraciones incrementales (por ejemplo, así se añadió `audit_log` o la columna `grupo` sin reescribir `init_db.py` desde cero). Está protegido detrás de la variable de entorno `ALLOW_HTTP_MIGRATIONS`, que debe permanecer en `false`/ausente en operación normal:

```bash
# 1. Habilitar temporalmente el feature flag en .env
echo "ALLOW_HTTP_MIGRATIONS=true" >> /home/admin/rfid-system/.env
sudo systemctl restart rfid-crud

# 2. Respaldar la base ANTES de migrar (paso obligatorio, no opcional)
sqlite3 shared/rfid.db ".backup 'shared/backups/pre_migracion_$(date +%Y%m%d_%H%M%S).db'"

# 3. Disparar la migración (requiere las credenciales de Basic Auth)
curl -u admin:CONTRASEÑA -X POST http://127.0.0.1:5001/api/migrate

# 4. Verificar el resultado en audit_log y en el estado de la BD
curl -u admin:CONTRASEÑA http://127.0.0.1:5001/api/software/database/status

# 5. Deshabilitar el feature flag de inmediato — no dejarlo activo en producción
sed -i '/ALLOW_HTTP_MIGRATIONS/d' /home/admin/rfid-system/.env
sudo systemctl restart rfid-crud
```

**d) Compactar la base de datos (`VACUUM`)**

`DELETE` en SQLite no reduce el tamaño físico del archivo: las páginas liberadas quedan disponibles para reutilización interna pero el archivo no encoge. `VACUUM` reconstruye el archivo completo, eliminando el espacio libre interno:

```bash
cd /home/admin/rfid-system/shared

# Detener el lector (o al menos evitar escrituras) es recomendable,
# aunque VACUUM puede ejecutarse con el sistema en modo WAL activo.
# Es una operación que reescribe TODO el archivo: en una microSD,
# puede tardar varios segundos y generar carga de I/O notable.
sqlite3 rfid.db "VACUUM;"
```

**Cuándo ejecutarlo:** no es necesario de forma rutinaria si solo se insertan registros (no hay `DELETE` masivo que generar páginas libres). Se vuelve relevante después de una purga de datos antiguos (ver §6.6) o tras eliminar en bloque estudiantes/tarjetas dados de baja hace tiempo.

**Alternativa incremental:** si se prevén purgas periódicas (ver estrategia de archivado en §6.6), activar `PRAGMA auto_vacuum = INCREMENTAL;` **antes** de crear las tablas (no se puede cambiar en una base ya poblada sin un `VACUUM` completo primero) y ejecutar `PRAGMA incremental_vacuum;` tras cada purga — compacta en pasos pequeños en vez de reescribir el archivo completo de una sola vez, lo que es más amigable con una microSD.

---

### 6.6 Estrategia de crecimiento y archivado

**Estimación de tamaño con uso diario**

La tabla `registros_asistencia` es, por diseño, la única que crece sin límite natural (no hay purga automática). Con una población típica de una institución de este tamaño:

| Parámetro | Valor estimado |
|---|---|
| Estudiantes activos | ~300–500 |
| Escaneos por estudiante/día (incluye reintentos y `ya_escaneado`) | ~2–4 |
| Registros nuevos por día hábil | ~900–1,800 |
| Tamaño promedio por renglón (con overhead de índices) | ~120–180 bytes |
| Crecimiento diario aproximado | ~150–300 KB/día |
| Días hábiles por semestre (~18 semanas) | ~90 |
| Crecimiento por semestre | ~13–27 MB |
| Crecimiento anual (2 semestres + verano) | ~30–60 MB/año |

Las tablas `estudiantes` y `tarjetas` son comparativamente insignificantes en tamaño (cientos de renglones, no miles por día) y no representan un problema de crecimiento — el foco de esta sección es `registros_asistencia`.

```python
# Estimación reproducible (no requiere hardware ni datos reales)
estudiantes = 400
escaneos_por_dia = 3
bytes_por_registro = 150   # dato + overhead de 4 índices que lo referencian
dias_habiles_semestre = 90

registros_semestre = estudiantes * escaneos_por_dia * dias_habiles_semestre
mb_semestre = (registros_semestre * bytes_por_registro) / (1024 ** 2)

print(f"Registros por semestre: {registros_semestre:,}")
print(f"Crecimiento estimado: {mb_semestre:.1f} MB por semestre")
```

Incluso en un escenario de varios años de operación continua sin purgar nada, el archivo `rfid.db` se mantendría en el orden de unos pocos cientos de MB — muy por debajo de cualquier límite práctico de SQLite (que soporta bases de varios TB) o de espacio en una microSD moderna (16 GB o superior, ver §3.2). El riesgo real no es el espacio en disco, sino la **degradación de rendimiento** en consultas que no usan bien los índices conforme la tabla crece a cientos de miles de renglones a lo largo de varios años.

**Recomendaciones de archivado**

| Estrategia | Cuándo aplica | Notas |
|---|---|---|
| **No archivar (dejar crecer)** | Mientras el archivo se mantenga por debajo de ~500 MB–1 GB y las consultas del dashboard sigan respondiendo en milisegundos (gracias a los índices de §6.2) | Es la situación actual; no requiere acción mientras no se note degradación |
| **Archivado anual a base "fría"** | Al cierre de cada ciclo escolar (o año calendario) | Copiar los registros de `registros_asistencia` con `fecha_dia` fuera del ciclo actual a una base separada (`rfid_historico_2025.db`) mediante `ATTACH DATABASE`, y purgar esos renglones de `rfid.db` con `DELETE ... WHERE fecha_dia < ?` seguido de `VACUUM` |
| **Exportación + purga** | Alternativa más simple si no se necesita consultar el histórico por SQL después | Exportar a CSV con el endpoint `/api/export/registros` (filtrado por rango de fechas) antes de purgar, y conservar el CSV como respaldo frío (ej. en el mismo `shared/backups/` o fuera del equipo) |

Ejemplo de archivado con `ATTACH DATABASE` (mover registros de un ciclo cerrado a una base separada, preservando la posibilidad de consultarlos por SQL si hiciera falta):

```sql
ATTACH DATABASE 'shared/backups/rfid_historico_2025.db' AS historico;

-- Crear la tabla destino con la misma estructura, si no existe aún
CREATE TABLE IF NOT EXISTS historico.registros_asistencia AS
SELECT * FROM registros_asistencia WHERE 0;  -- copia solo la estructura

-- Mover los registros del ciclo cerrado
INSERT INTO historico.registros_asistencia
SELECT * FROM registros_asistencia
WHERE fecha_dia < '2026-01-01';

DELETE FROM registros_asistencia
WHERE fecha_dia < '2026-01-01';

DETACH DATABASE historico;

VACUUM;  -- compacta rfid.db tras la purga masiva
```

> **Importante:** cualquier operación de archivado o purga masiva debe ir precedida de un backup completo (§6.5-a) y, si el sistema está en producción activa, ejecutarse con los servicios detenidos o en una ventana de bajo uso (ej. fin de semana), dado que `DELETE` + `VACUUM` sobre decenas de miles de renglones bloquea escrituras del lector mientras se ejecuta.

<a id="7"></a>
## 7. API REST
[[Volver a la tabla de contenido]](#toc)

Documentación completa de la API, extraída directamente de `app_crud.py`. El servicio expone más de 50 rutas, agrupadas por función. Todo corre sobre Flask + Gunicorn en el puerto **5001** (ver §5.4).

---

### 7.1 Modelo de autenticación y control de acceso (corrección importante)

El sistema **no usa tokens** (JWT, OAuth, API keys) — la autenticación es **HTTP Basic Auth**, aplicada globalmente a **todas** las rutas mediante `@app.before_request`, sin excepción:

```python
@app.before_request
def _enforce_basic_auth():
    ...
    auth = request.authorization
    if not auth or not _check_credentials(auth.username, auth.password):
        _register_auth_failure(ip)
        return _auth_required_response()   # 401
```

Las credenciales se comparan con `hmac.compare_digest`, resistente a *timing attacks*, contra las variables de entorno `ADMIN_USER` / `ADMIN_PASSWORD` (obligatorias — el proceso ni siquiera arranca si faltan, ver `_get_required_env`). No hay endpoint de "login" que devuelva un token: cada petición debe incluir el encabezado `Authorization: Basic ...` (que `curl -u usuario:contraseña` genera automáticamente).

**Capas de protección, en el orden real en que se ejecutan** (según el orden de registro de los `before_request` en el código):

| Orden | Capa | Código | Efecto si falla |
|---|---|---|---|
| 1 | **Allowlist de IP** (`_enforce_ip_allowlist`) | Solo activa si `ALLOWED_SUBNET` está definida y no es `"disabled"` | `403` — nada más se ejecuta, ni siquiera se evalúa Basic Auth |
| 2 | **Rate limit global** (Flask-Limiter, `60/minuto` por IP) | Se **exime** automáticamente si la petición ya trae credenciales Basic Auth válidas (`_exempt_authenticated_admin_from_global_limit`) — en la práctica, solo protege contra *scanning* no autenticado | `429` |
| 3 | **Rate limit de intentos fallidos de auth** (`5/minuto` y `20/15 min` por IP, independiente del límite global) | Se evalúa antes de comprobar credenciales | `429`, y se registra en `audit_log` como `auth_rate_limited` |
| 4 | **Basic Auth** (`_enforce_basic_auth`) | Credenciales inválidas o ausentes | `401` con header `WWW-Authenticate: Basic realm="RFID Admin"` |
| 5 | **Encabezado anti-CSRF** (`require_xhr_header`, solo en rutas destructivas específicas, ver §7.2) | Falta `X-Requested-With: XMLHttpRequest` | `403` |

> **Nota de código:** existe una función `require_basic_auth` (decorador) definida en el archivo pero **no se usa en ninguna ruta** — toda la protección real viene del `before_request` global (`_enforce_basic_auth`). Es código muerto/redundante, no una segunda capa activa.

**Rutas que además exigen el encabezado anti-CSRF** `X-Requested-With: XMLHttpRequest` (vía `@require_xhr_header`), por ser destructivas o de alto impacto:

- `POST /api/hardware/system/optimize`
- `POST /api/hardware/system/reboot`
- `POST /api/hardware/system/shutdown`
- `POST /api/software/database/restore`
- `POST /api/software/database/purge`
- `POST /api/estudiantes/baja-masiva`

**Cabeceras de seguridad** (`_set_security_headers`, aplicadas a *toda* respuesta vía `@app.after_request`): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy` restrictiva, `Referrer-Policy: no-referrer`, `Permissions-Policy` que deshabilita cámara/micrófono/geolocalización.

**Límite de tamaño de petición:** `MAX_CONTENT_LENGTH = 5 MB` (`app.config`) — cualquier `POST`/`PUT` con cuerpo mayor es rechazado por Flask automáticamente (`413 Request Entity Too Large`, no capturado por el decorador `@api`).

---

### 7.2 Manejo de errores — el decorador `@api`

La mayoría de las rutas usan el decorador `@api`, que homogeniza los errores no controlados:

```python
def api(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except sqlite3.IntegrityError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            log.exception(f"Error en {f.__name__}")
            return jsonify({'success': False, 'error': 'Error interno'}), 500
    return wrapper
```

**Cuatro rutas NO usan `@api`** y por lo tanto no devuelven errores en JSON si algo truena internamente (devuelven la página de error HTML por defecto de Flask, `500`):

- `GET /` (página del panel)
- `GET /api/export/estudiantes`
- `GET /api/export/registros`
- `GET /api/software/database/backups/<filename>/download`

Esto es relevante al integrar la API con otro sistema: un `try/except` que espere siempre JSON debe contemplar este caso para esas cuatro rutas específicamente.

---

### 7.3 Estadísticas y analítica

| Método | Ruta | Query params | Descripción |
|---|---|---|---|
| GET | `/api/estadisticas` | — | Conteos globales: estudiantes, tarjetas, registros de hoy, aceptados hoy |
| GET | `/api/analytics` | — | Asistencia de los últimos 7 días, total del mes, distribución por semestre, distribución por hora (hoy), top 10 estudiantes con más asistencias |

**Ejemplo — `GET /api/estadisticas`**

```bash
curl -s -u admin:CONTRASEÑA http://127.0.0.1:5001/api/estadisticas
```
```json
{
  "success": true,
  "stats": {
    "total_estudiantes": 412,
    "estudiantes_activos": 398,
    "total_tarjetas": 405,
    "tarjetas_activas": 401,
    "registros_hoy": 634,
    "total_registros": 58210,
    "aceptados_hoy": 380
  }
}
```

> Nota: todas las consultas de estos dos endpoints filtran por `carrera = "ITIC's"` (constante `CARRERA` en el código) — el sistema, tal como está desplegado, está acotado a una sola carrera, no a todo el ITSOEH.

---

### 7.4 Hardware (monitoreo y control de la Raspberry Pi)

| Método | Ruta | Auth extra | Body / Query | Descripción |
|---|---|---|---|---|
| GET | `/api/hardware/status` | — | — | Temperatura CPU, uso de CPU/RAM/disco, estado del RC522 (`conectado`/`módulo_ok`/`spi_no_detectado`), tamaño y conteo de `rfid.db`, uptime |
| GET | `/api/hardware/services` | — | — | Estado (`active`/`enabled`) de los 3 servicios RFID |
| POST | `/api/hardware/services/<service_name>/<action>` | — | — | `action` ∈ `start,stop,restart,enable,disable,status`; `service_name` debe estar en la lista blanca `RFID_SERVICES` |
| GET | `/api/hardware/services/<service_name>/logs` | — | `?lines=N` (def. 50, máx. 500) | Últimas N líneas de `journalctl -u <servicio>` |
| GET | `/api/hardware/network/status` | — | — | Redes visibles, SSID conectado, IP, gateway, DNS, prueba de internet (ping a 8.8.8.8) |
| POST | `/api/hardware/network/scan` | — | — | Fuerza un `nmcli dev wifi rescan` |
| POST | `/api/hardware/network/connect` | — | `{"ssid": "...", "password": "..."}` | `ssid` requerido; conecta o crea el perfil de red |
| POST | `/api/hardware/network/disconnect` | — | — | Desconecta la interfaz Wi-Fi activa |
| POST | `/api/hardware/network/restart` | — | — | Reinicia `NetworkManager.service` — **sin exigir `confirm`** (ver nota abajo) |
| POST | `/api/hardware/system/optimize` | XHR | `{"confirm": true}` | Libera caché de memoria (`sync` + drop\_caches) |
| POST | `/api/hardware/system/reboot` | XHR | `{"confirm": true}` | Reinicia la Raspberry Pi; queda en `audit_log` |
| POST | `/api/hardware/system/shutdown` | XHR | `{"confirm": true}` | Apaga la Raspberry Pi; queda en `audit_log` |

**Nota:** `/api/hardware/network/restart` reinicia `NetworkManager` con solo un `POST` vacío — no exige `confirm` ni encabezado XHR, a diferencia de otras rutas destructivas de esta misma familia (§12.3-4 lo marca como hallazgo pendiente).

**Ejemplo — reiniciar el lector RFID**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  http://127.0.0.1:5001/api/hardware/services/rfid-reader.service/restart
```
```json
{
  "success": true,
  "service": "rfid-reader.service",
  "action": "restart",
  "active": true,
  "enabled": true,
  "active_text": "active",
  "enabled_text": "enabled",
  "result": {"success": true, "returncode": 0, "stdout": "", "stderr": ""}
}
```

Si el usuario `admin` no tiene permisos `sudo NOPASSWD` configurados para `systemctl`, la respuesta es:
```json
{"success": false, "error": "Permiso denegado. Configura sudo NOPASSWD.", "result": {"...": "..."}}
```
con código **403**.

**Ejemplo — apagar la Raspberry Pi (requiere encabezado anti-CSRF)**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true}' \
  http://127.0.0.1:5001/api/hardware/system/shutdown
```
Sin el header `X-Requested-With`, la respuesta es `403` con `{"success": false, "error": "Falta encabezado requerido."}`, **antes** de siquiera revisar el cuerpo.

---

### 7.5 Software admin — servicios (espejo de §7.4)

`app_crud.py` expone un **segundo conjunto de rutas idéntico en comportamiento** a las de hardware, bajo el prefijo `/api/software/` en vez de `/api/hardware/` — aparentemente para separar visualmente, en el panel, la pestaña "Hardware" de la pestaña "Software", aunque internamente llaman a las mismas funciones auxiliares (`_systemctl`, `_run`, lista blanca `RFID_SERVICES`).

| Método | Ruta | Equivale a |
|---|---|---|
| GET | `/api/software/services` | `GET /api/hardware/services` |
| POST | `/api/software/services/<service_name>/<action>` | `POST /api/hardware/services/<service_name>/<action>` |
| GET | `/api/software/services/<service_name>/logs?lines=` | `GET /api/hardware/services/<service_name>/logs` (default `lines=80` en vez de 50) |

---

### 7.6 Software admin — base de datos

| Método | Ruta | Auth extra | Body / Query | Descripción |
|---|---|---|---|---|
| GET | `/api/software/database/status` | — | — | Ruta y tamaño de `rfid.db`, conteos por tabla, número de respaldos |
| GET | `/api/software/database/backups` | — | — | Lista de respaldos existentes (nombre, tamaño, fecha) |
| POST | `/api/software/database/backup` | — | — | Crea un respaldo con `sqlite3.Connection.backup()` (WAL-aware) |
| POST | `/api/software/database/restore` | XHR | `{"filename": "...", "confirm": true}` | Restaura desde un respaldo; crea automáticamente un respaldo de seguridad del estado actual antes de sobrescribir |
| GET | `/api/software/database/backups/<filename>/download` | — | — | Descarga el archivo `.db` (streaming, `application/octet-stream`) — **sin `@api`** |
| DELETE | `/api/software/database/backups/<filename>` | — | `?confirm=1` o `{"confirm": true}` | Elimina un archivo de respaldo |
| POST | `/api/software/database/purge/preview` | — | filtros (ver abajo) | Cuenta cuántos registros coinciden con los filtros, **sin borrar nada** |
| POST | `/api/software/database/purge` | XHR | filtros + `{"confirm": true}` | Borra los registros que coinciden, tras crear automáticamente un respaldo de seguridad |

**Filtros aceptados por `purge/preview` y `purge`** (todos opcionales, se combinan con `AND`): `fecha_desde`, `fecha_hasta` (`YYYY-MM-DD`), `carrera`, `semestre`, `grupo`, `matricula`, `estudiante_id`.

**Detalle importante de `purge`:** si la creación del respaldo de seguridad falla por cualquier motivo, la purga se **cancela por completo** (`_PurgeBackupError` → `500`) y no se borra ningún registro — es decir, el sistema nunca purga sin haber logrado respaldar antes.

**Ejemplo — vista previa de purga (sin borrar nada)**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "Content-Type: application/json" \
  -d '{"fecha_hasta": "2025-12-31"}' \
  http://127.0.0.1:5001/api/software/database/purge/preview
```
```json
{"success": true, "count": 14832}
```

**Ejemplo — ejecutar la purga (requiere `confirm` y el header XHR)**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" \
  -d '{"fecha_hasta": "2025-12-31", "confirm": true}' \
  http://127.0.0.1:5001/api/software/database/purge
```
```json
{
  "success": true,
  "deleted": 14832,
  "safety_backup": "rfid_backup_20260827_113045.db",
  "mensaje": "14832 registro(s) eliminados"
}
```

**Ejemplo — restaurar un respaldo**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" \
  -d '{"filename": "rfid_backup_20260815_070000.db", "confirm": true}' \
  http://127.0.0.1:5001/api/software/database/restore
```
```json
{
  "success": true,
  "mensaje": "Base restaurada desde rfid_backup_20260815_070000.db",
  "safety_backup": "rfid_backup_20260827_113512.db"
}
```
Si el `filename` no cumple el patrón `rfid_backup_YYYYMMDD_HHMMSS.db` (regex `_BACKUP_RE`), la respuesta es `400` — esto es lo que impide *path traversal* (ej. `../../etc/passwd`) mencionado en §12.

---

### 7.7 RFID — escucha activa (alta rápida de una sola tarjeta)

Mecanismo simple usado por el CRUD para capturar **una** tarjeta nueva (por ejemplo, al dar de alta un estudiante desde su ficha):

| Método | Ruta | Body | Descripción |
|---|---|---|---|
| POST | `/api/rfid/listen/start` | `{"timeout": 30}` (segundos, opcional) | Activa el modo escucha |
| GET | `/api/rfid/listen/status` | — | Devuelve `{active, uid, timestamp, expires}`; se auto-desactiva al expirar |
| POST | `/api/rfid/listen/stop` | — | Cancela la escucha manualmente |
| POST | `/api/rfid/listen/capture` | `{"uid": "..."}` | Registra el UID capturado — devuelve `409` si el modo no estaba activo |

> Este mecanismo es distinto del flujo descrito en §4.1 del documento original (que usa el archivo de señal `/run/rfid-shared/`). `listen/capture` parece pensado para que **otro proceso o interfaz** empuje el UID directamente por HTTP, no necesariamente el lector físico — conviene aclarar con el equipo de desarrollo cuál de los dos flujos (archivo de señal vs. este endpoint) está realmente en uso en producción.

---

### 7.8 RFID — escaneo masivo administrativo

Flujo para dar de alta **varias** tarjetas nuevas en una sola sesión (ej. inicio de semestre), coordinado con el archivo de señal `/run/rfid-shared/rfid_admin_mode` que ya se documentó en §4.1:

| Método | Ruta | Body | Descripción |
|---|---|---|---|
| POST | `/api/rfid/admin-scan/start` | `{"timeout": 300}` (seg., opcional) | Crea el archivo de señal `ADMIN_FLAG`; el lector deja de registrar asistencia y empieza a capturar UIDs |
| GET | `/api/rfid/admin-scan/status` | — | Polling: lee `ADMIN_UID_FILE` (con `flock`), enriquece cada UID con datos de tarjeta/estudiante si ya existe, acumula la lista de la sesión |
| POST | `/api/rfid/admin-scan/stop` | — | Elimina los archivos de señal y cierra la sesión |
| POST | `/api/rfid/admin-scan/guardar` | `{"uids": ["123...", "456..."]}` | Inserta cada UID como tarjeta nueva sin estudiante asignado (`id_estudiante=NULL`); omite los que ya existen |
| POST | `/api/rfid/admin-scan/eliminar` | `{"uids": [...], "forzar": false}` | Elimina tarjetas de la tabla; si una ya tiene estudiante asignado, se rechaza salvo que `forzar: true` |

**Ejemplo — guardar 2 UIDs capturados en una sesión de alta masiva**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "Content-Type: application/json" \
  -d '{"uids": ["3184920321", "3184920399"]}' \
  http://127.0.0.1:5001/api/rfid/admin-scan/guardar
```
```json
{
  "success": true,
  "resultados": [
    {"uid": "3184920321", "ok": true,  "msg": "Guardada"},
    {"uid": "3184920399", "ok": false, "msg": "Ya existe en tarjetas"}
  ],
  "guardadas": 1,
  "total": 2
}
```

---

### 7.9 RFID — utilidades de consulta

| Método | Ruta | Query / Params | Descripción |
|---|---|---|---|
| GET | `/api/rfid/desconocidos` | — | Top 50 UIDs con eventos `rebote`/`desconocido` que **no** tienen tarjeta registrada, con conteo y último escaneo |
| POST | `/api/rfid/guardar-uid` | `{"uid": "..."}` | Registra un UID nuevo como tarjeta sin asignar, o informa por qué uno existente no es válido |
| GET | `/api/rfid/tarjetas-sin-asignar` | — | Últimas 100 tarjetas sin `id_estudiante` |
| GET | `/api/rfid/alumnos-sin-tarjeta` | — | Estudiantes activos de la carrera sin ninguna tarjeta asignada |
| GET | `/api/rfid/historial/<uid>` | `uid` en la ruta | Últimos 100 eventos de ese UID específico |
| GET | `/api/rfid/ultimo-scan` | — | El evento más reciente registrado en todo el sistema, con nombre/matrícula/foto del estudiante si aplica |

**Ejemplo — consultar el historial de una tarjeta**

```bash
curl -s -u admin:CONTRASEÑA http://127.0.0.1:5001/api/rfid/historial/3184920157
```
```json
{
  "success": true,
  "uid": "3184920157",
  "historial": [
    {"id": 58210, "id_estudiante": 87, "uid": "3184920157",
     "timestamp": "2026-08-27 07:16:44", "fecha_dia": "2026-08-27",
     "tipo_raw": "aceptado", "mensaje": null,
     "nombre": "Juan Pérez", "matricula": "22011200"}
  ]
}
```

---

### 7.10 Estudiantes

| Método | Ruta | Auth extra | Query / Body | Descripción |
|---|---|---|---|---|
| GET | `/api/estudiantes` | — | `?semestre=&grupo=&buscar=` | Lista con conteo de tarjetas y registros por estudiante; `buscar` compara nombre, apellido, matrícula **y** UID de tarjeta |
| GET | `/api/estudiantes/grupos` | — | — | Estudiantes activos agrupados por `semestre-grupo` |
| GET | `/api/estudiantes/<id>` | — | — | Ficha de un estudiante — `404` si no existe |
| POST | `/api/estudiantes` | — | JSON (ver abajo) | Crea un estudiante |
| PUT | `/api/estudiantes/<id>` | — | JSON (ver abajo) | Actualiza; si la `foto` cambia, borra el archivo anterior del disco |
| DELETE | `/api/estudiantes/<id>` | — | — | Elimina (físicamente); también borra su foto del disco |
| POST | `/api/estudiantes/promover` | — | `{"ids":[...]}` **o** `{"desde_semestre": N, "grupo": "..."}`, más `"confirmar": true/false` | Suma 1 al semestre de los estudiantes que coinciden. Sin `confirmar`, solo devuelve cuántos coinciden (vista previa) |
| POST | `/api/estudiantes/baja-masiva` | XHR | Igual patrón que `promover` (`ids` o `semestre`+`grupo`, + `confirmar`) | Marca `estado='inactivo'` en bloque |
| POST | `/api/estudiantes/alta-masiva` | — | `{"estudiantes": [{...}, ...]}` | Inserta varios estudiantes; devuelve `creados` y `errores` por fila |
| GET | `/api/estudiantes/<id>/perfil` | — | — | Estudiante + sus tarjetas + últimos 90 registros + total de asistencias + último acceso |

**Campos JSON de `POST`/`PUT /api/estudiantes`:** `nombre`, `apellido_paterno`, `apellido_materno`, `matricula`, `semestre`, `grupo`, `correo`, `estado` (`activo`/`inactivo`, por defecto `activo`), `foto` (URL relativa devuelta por `/api/upload-foto`, ver §7.12). El campo `carrera` **no se acepta del cliente** — el servidor siempre usa la constante `CARRERA = "ITIC's"`.

**Ejemplo — listar estudiantes de 5° semestre, grupo A**

```bash
curl -s -u admin:CONTRASEÑA \
  "http://127.0.0.1:5001/api/estudiantes?semestre=5&grupo=A"
```
```json
{
  "success": true,
  "estudiantes": [
    {
      "id": 87, "nombre": "Juan", "apellido_paterno": "Pérez", "apellido_materno": "López",
      "matricula": "22011200", "carrera": "ITIC's", "semestre": 5, "grupo": "A",
      "correo": "juan.perez@itsoeh.edu.mx", "estado": "activo", "foto": null,
      "creado_en": "2026-01-15 09:00:00",
      "tarjetas_asignadas": 1, "total_registros": 143
    }
  ]
}
```

**Ejemplo — dar de baja masiva a un grupo (vista previa, sin aplicar)**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "X-Requested-With: XMLHttpRequest" \
  -H "Content-Type: application/json" \
  -d '{"semestre": 9, "grupo": "A"}' \
  http://127.0.0.1:5001/api/estudiantes/baja-masiva
```
```json
{"success": true, "afectados": 28, "aplicado": false, "mensaje": "28 estudiante(s) coinciden"}
```
Repetir con `"confirmar": true` en el cuerpo para aplicarla de verdad.

---

### 7.11 Tarjetas

| Método | Ruta | Query / Body | Descripción |
|---|---|---|---|
| GET | `/api/tarjetas` | `?limit=&offset=` (limit máx. 200, def. 50) | Lista paginada, con nombre/matrícula del estudiante si tiene uno asignado |
| POST | `/api/tarjetas` | `{"uid":"...", "id_estudiante": N\|null, "activa": 1}` | Asigna/crea una tarjeta directamente (a diferencia de `/api/rfid/guardar-uid`, aquí sí puede asociarse a un estudiante en el mismo paso) |
| PUT | `/api/tarjetas/<id>` | `{"uid":"...", "id_estudiante": N\|null, "activa": 0\|1}` | Actualiza una tarjeta existente |
| DELETE | `/api/tarjetas/<id>` | — | Elimina la tarjeta |
| POST | `/api/tarjetas/bulk-toggle` | `{"ids":[...], "activa": 0\|1}` | Activa/desactiva varias tarjetas a la vez |

**Ejemplo — asignar una tarjeta ya capturada al estudiante 87**

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -H "Content-Type: application/json" \
  -d '{"uid": "3184920321", "id_estudiante": 87, "activa": 1}' \
  http://127.0.0.1:5001/api/tarjetas
```
```json
{"success": true, "id": 406, "mensaje": "Tarjeta asignada"}
```

Si el `uid` ya existe en la tabla (columna `UNIQUE`), la respuesta es `400`:
```json
{"success": false, "error": "UNIQUE constraint failed: tarjetas.uid"}
```
(este es el caso capturado por `except sqlite3.IntegrityError` dentro del decorador `@api`, ver §7.2).

---

### 7.12 Registros, auditoría, asistencia del día y fotos

| Método | Ruta | Query / Body | Descripción |
|---|---|---|---|
| GET | `/api/registros` | `?limit=&offset=&fecha=&estado=&uid=` (limit máx. 200, def. 25) | Listado paginado de eventos; `estado=aceptado` incluye también el valor legado `entrada`; `uid` hace `LIKE %valor%` |
| GET | `/api/audit-log` | `?limit=&offset=&accion=&ip=` (limit máx. 200, def. 25) | Bitácora administrativa; `400` si la tabla `audit_log` aún no existe (sugiere correr `/api/migrate`) |
| GET | `/api/asistencia/hoy` | — | Lista de `id_estudiante` con al menos un `aceptado` hoy (para marcar presentes en la UI) |
| POST | `/api/upload-foto` | `multipart/form-data`, campo `foto` | Sube y procesa una foto de estudiante |

**`POST /api/upload-foto` — detalle del procesamiento:**
1. Verifica extensión permitida (`png`, `jpg`, `jpeg`, `gif`, `webp`).
2. Verifica con Pillow (`Image.verify()` + `Image.load()`) que el contenido sea realmente una imagen válida — no solo el nombre del archivo.
3. Convierte a `RGB` y redimensiona si excede 2000 px en cualquier dimensión (`Image.thumbnail`, preserva proporción).
4. Guarda como `.jpg` con calidad 85, con nombre único con timestamp + nombre original saneado (`secure_filename`).
5. Devuelve la ruta relativa a usar en `foto` al crear/editar un estudiante.

```bash
curl -s -u admin:CONTRASEÑA -X POST \
  -F "foto=@/ruta/local/estudiante_87.jpg" \
  http://127.0.0.1:5001/api/upload-foto
```
```json
{"success": true, "foto_url": "/static/fotos/20260827_114501_123456_estudiante_87.jpg"}
```

---

### 7.13 Exportación CSV

| Método | Ruta | Query | Salida |
|---|---|---|---|
| GET | `/api/export/estudiantes` | — | CSV completo del padrón de la carrera configurada |
| GET | `/api/export/registros` | `?fecha=YYYY-MM-DD` (por defecto, **hoy**) | CSV de asistencia de **un solo día** |

**Nota:** `/api/export/registros` solo acepta una fecha puntual (`?fecha=`, por defecto el día actual) — no admite un rango de fechas vía la API. Si se necesita un rango, hay que llamar al endpoint una vez por cada día y concatenar los CSV, o construir la consulta directamente contra `rfid.db` (ver §6.4-g, que sí soporta `BETWEEN` por SQL directo).

Dos detalles de seguridad/compatibilidad en la generación del CSV que vale la pena documentar:

- **BOM UTF-8** (`\ufeff`) al inicio del archivo — necesario para que Excel abra los acentos correctamente sin configurarlo manualmente.
- **Neutralización de inyección de fórmulas CSV** (`_csv_safe`): cualquier campo de texto (nombre, correo, grupo, mensaje) cuyo primer carácter sea `=`, `+`, `-` o `@` se antepone con una comilla simple. Esto evita que un nombre malicioso como `=cmd|'/c calc'!A1` se interprete como fórmula al abrir el CSV en Excel/Sheets — una protección que no estaba documentada en la revisión de seguridad original (§12) y que conviene añadir a la lista de buenas prácticas ya implementadas.

```bash
curl -s -u admin:CONTRASEÑA \
  "http://127.0.0.1:5001/api/export/registros?fecha=2026-08-27" \
  -o registros_2026-08-27.csv
```

```
ID,Timestamp,Tipo,UID,Nombre,Matrícula,Semestre,Grupo,Mensaje
58210,2026-08-27 07:16:44,aceptado,3184920157,Juan Pérez,22011200,5,A,
58211,2026-08-27 07:18:02,rebote,2200981144,DESCONOCIDO,,,,UID no registrado
```

---

### 7.14 Migración de esquema

| Método | Ruta | Body | Descripción |
|---|---|---|---|
| POST | `/api/migrate` | — | Aplica migraciones incrementales (agrega `estudiantes.grupo`, `registros_asistencia.fecha_dia`, crea `audit_log` y su índice) |

**Detalle de diseño relevante para seguridad:** cuando `ALLOW_HTTP_MIGRATIONS` no está activo, el endpoint no responde `403` (que confirmaría que la ruta existe pero está bloqueada) sino `abort(404)` — se hace pasar por una ruta inexistente para no revelar su presencia a quien esté explorando la API sin autorización:

```python
if not ALLOW_HTTP_MIGRATIONS:
    log.warning(...)
    abort(404)
```

Cada sentencia SQL se ejecuta en su propio `try/except sqlite3.OperationalError`, así que volver a correr `/api/migrate` sobre una base ya migrada es seguro (los `ALTER TABLE` que fallan porque la columna ya existe simplemente se reportan con `"ok": false` en el resultado, sin detener las demás).

```bash
curl -s -u admin:CONTRASEÑA -X POST http://127.0.0.1:5001/api/migrate
```
```json
{
  "success": true,
  "results": [
    {"sql": "ALTER TABLE estudiantes ADD COLUMN grupo TEXT DEFAULT ''", "ok": false,
     "msg": "duplicate column name: grupo"},
    {"sql": "ALTER TABLE registros_asistencia ADD COLUMN fecha_dia TEXT", "ok": false,
     "msg": "duplicate column name: fecha_dia"},
    {"sql": "CREATE TABLE IF NOT EXISTS audit_log (...)", "ok": true},
    {"sql": "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ...", "ok": true}
  ]
}
```

---

### 7.15 Códigos de respuesta

| Código | Significado en este sistema | Dónde aparece |
|---|---|---|
| **200** | Operación exitosa | Toda respuesta normal. **Ojo:** algunas operaciones "fallidas desde el punto de vista de negocio" (ej. UID inválido en `/api/rfid/guardar-uid`) devuelven `200` con `"success": false` en el cuerpo — hay que revisar siempre el campo `success`, no solo el código HTTP |
| **400** | Petición mal formada o violación de restricción de datos | Parámetros faltantes/inválidos (`SSID requerido`, `UID requerido`, `filename inválido`); `sqlite3.IntegrityError` capturado por `@api` (ej. UID duplicado); falta `confirm` en operaciones destructivas |
| **401** | Credenciales de Basic Auth ausentes o incorrectas | Cualquier ruta, ya que la autenticación es global |
| **403** | Acceso denegado por política, no por credenciales | IP fuera de `ALLOWED_SUBNET`; servicio fuera de la lista blanca `RFID_SERVICES`; falta el header `X-Requested-With` en rutas protegidas; `sudo` sin permisos configurados |
| **404** | Recurso no encontrado | Estudiante/respaldo inexistente; interfaz Wi-Fi no encontrada; `/api/migrate` cuando está deshabilitado (deliberadamente, ver §7.14) |
| **409** | Conflicto de estado | `/api/rfid/listen/capture` cuando el modo escucha no está activo |
| **429** | Demasiadas solicitudes | Límite global (60/min) o límite específico de intentos fallidos de autenticación (5/min o 20/15min) |
| **500** | Error interno no controlado | Cualquier excepción no prevista dentro de una ruta con `@api`; en las 4 rutas sin `@api` (§7.2), un error interno da la página HTML de error estándar de Flask, no JSON |
| **413** | Cuerpo de la petición demasiado grande | Automático por Flask/Werkzeug si el `POST`/`PUT` supera `MAX_CONTENT_LENGTH` (5 MB) |

---

### 7.16 Probar la API localmente con Postman o Insomnia

1. **Crear una colección/workspace nuevo** apuntando a `http://127.0.0.1:5001` (o la IP de la Raspberry Pi en la red local, puerto 5001) como variable de entorno base (`{{base_url}}`).
2. **Configurar autenticación a nivel de colección**, no por petición: en Postman, pestaña *Authorization* de la colección → tipo **Basic Auth** → usuario/contraseña de `ADMIN_USER`/`ADMIN_PASSWORD`. Todas las peticiones hijas heredan esa configuración automáticamente (equivalente a `curl -u`). En Insomnia, se configura igual a nivel de *Folder* raíz.
3. **Variables de entorno recomendadas:** `base_url`, `admin_user`, `admin_password`, y una variable `estudiante_id` de prueba para reutilizar en varias peticiones (`{{base_url}}/api/estudiantes/{{estudiante_id}}`).
4. **Para rutas con el header anti-CSRF** (§7.1): agregar manualmente en cada petición destructiva el header `X-Requested-With: XMLHttpRequest` — ni Postman ni Insomnia lo agregan por defecto, a diferencia de un navegador con `fetch()`/`XMLHttpRequest` real.
5. **Para `/api/upload-foto`:** usar el modo `form-data` (no `raw`/JSON) y definir el campo `foto` como tipo **File**, seleccionando una imagen local.
6. **Para probar el rate limiting de autenticación** (5/min): usar credenciales incorrectas a propósito varias veces seguidas contra cualquier endpoint y verificar que, tras el quinto intento en un minuto, la respuesta cambia de `401` a `429` con `{"error": "Demasiados intentos fallidos..."}`.
7. **Precaución con endpoints destructivos durante las pruebas:** `/api/software/database/purge`, `/api/estudiantes/baja-masiva`, `/api/hardware/system/reboot` y `/api/hardware/system/shutdown` tienen efectos reales e irreversibles (o que requieren estar físicamente en la Pi para revertir). Se recomienda **probarlos primero contra una copia de la base de datos** (`cp shared/rfid.db shared/rfid_test.db`, cambiando temporalmente la variable `DB` del script) en vez de contra `rfid.db` de producción, y usar siempre primero la variante `/preview` cuando exista (ej. `purge/preview`, o `promover`/`baja-masiva` sin `confirmar`).
8. **Generar la colección automáticamente (opcional):** ya que el formato elegido para esta documentación es Markdown + `curl` (no un archivo `openapi.yaml`), la forma más rápida de tener algo importable en Postman es usar su función *Import → Raw text → From cURL* pegando, uno por uno, los comandos `curl` de esta sección — Postman los convierte automáticamente en peticiones de la colección.

---

> **Nota:** esta documentación se generó leyendo directamente `app_crud.py`. Si el archivo cambia — nuevos endpoints, nuevos parámetros, cambios en las respuestas — esta sección debe regenerarse contra el código actualizado para no quedar desincronizada.

<a id="8"></a>
## 8. Flujo de datos de extremo a extremo
[[Volver a la tabla de contenido]](#toc)

```python
fig, ax = new_canvas(13, 4.6, "Flujo de datos — de la tarjeta a la pantalla")

steps = [
    ("Tarjeta\nacercada", COLOR['neutral']),
    ("Lector RC522\nlee UID", COLOR['primary']),
    ("INSERT en\nrfid.db (WAL)", COLOR['accent']),
    ("Dashboard consulta\ncada refresco", COLOR['secondary']),
    ("Se renderiza en\npantalla kiosco", COLOR['neutral']),
]

x = 0.4
w, h, gap = 2.1, 1.6, 0.55
y = 2.1
positions = []
for label, c in steps:
    p = draw_box(ax, (x, y), w, h, label, fc=c, fs=9.5)
    positions.append((x, x + w))
    x += w + gap

for i in range(len(positions) - 1):
    draw_arrow(ax, (positions[i][1], y + h/2), (positions[i+1][0], y + h/2))

ax.text(6.5, 0.55,
        "En paralelo: el panel CRUD (puerto 5001) permite exportar CSV bajo demanda\n" "y administrar estudiantes/tarjetas, sin interferir con el flujo de registro.", ha='center', fontsize=9.5, style='italic', color=COLOR['neutral'])

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_23_0.png)
    


<a id="9"></a>
## 9. Analítica y panel de control (dashboard)

El dashboard (`app_dashboard.py`) calcula, todo referido **al día en curso**:

- Conteo de eventos por tipo (`aceptado`, `rebote`, `ya_escaneado`)
- Total de tarjetas activas
- Top 10 UIDs con más escaneos repetidos en el día
- Listado de eventos recientes (con datos del estudiante)
- Distribución de escaneos por hora del día (única gráfica del sistema, dibujada con
  `<canvas>` + JavaScript plano, sin librería externa)

La siguiente gráfica **ilustra el tipo de visualización** que genera el sistema en producción (distribución horaria de escaneos), con datos de ejemplo — no son datos reales extraídos de `rfid.db`, sino una representación del patrón típico esperado en un horario escolar.


```python
horas = list(range(6, 22))
# Datos ILUSTRATIVOS (patrón típico de entrada escolar) — no son datos reales del sistema
escaneos_ejemplo = [0,0,3,45,78,22,8,5,4,30,60,15,6,3,2,1]

fig, ax = plt.subplots(figsize=(11, 4.5))
bars = ax.bar(horas, escaneos_ejemplo, color=COLOR['secondary'], edgecolor='white', width=0.7)
peak = escaneos_ejemplo.index(max(escaneos_ejemplo))
bars[peak].set_color(COLOR['accent'])

ax.set_title("Ejemplo ilustrativo — Distribución de escaneos por hora", fontsize=13, weight='bold', color=COLOR['primary'])
ax.set_xlabel("Hora del día")
ax.set_ylabel("Escaneos (ejemplo)")
ax.spines[['top', 'right']].set_visible(False)
ax.set_xticks(horas)
ax.text(0.5, 0.95, "⚠ Datos de ejemplo — no representan lecturas reales del sistema",
        transform=ax.transAxes, ha='center', fontsize=8.5, color=COLOR['danger'], style='italic')

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_25_0.png)
    



> **Para reemplazar con datos reales:** conecta esta celda a `rfid.db` con `sqlite3`/`pandas`
> y agrupa `registros_asistencia` por `strftime('%H', timestamp)` — la misma consulta que usa
> `/api/estado` internamente. Se deja como ejemplo para no exponer datos de estudiantes reales
> en un repositorio público.

**Lo que el dashboard *no* incluye actualmente** (áreas de oportunidad, ver
[sección 14](#14)): analítica histórica por semana/mes/semestre, reportes por grupo o carrera,
y modelos predictivos de asistencia.


<a id="10"></a>
## 10. Procesamiento de datos

El sistema **no implementa un pipeline ETL**: todo el procesamiento es inserción directa (lector) o consulta directa (CRUD/dashboard) contra `rfid.db`. La única transformación real es la **exportación bajo demanda a CSV**, generada con *streaming* (`stream_with_context`) para no cargar el archivo completo en memoria:

| Endpoint | Salida |
|---|---|
| `/api/export/estudiantes` | CSV con datos completos de estudiantes |
| `/api/export/registros` | CSV de asistencia filtrable por fecha |

El endpoint `/api/migrate` aplica migraciones incrementales de esquema (por ejemplo, así se añadieron las columnas `grupo`, `fecha_dia` y la tabla `audit_log` sin reescribir `init_db.py`), protegido por la variable de entorno `ALLOW_HTTP_MIGRATIONS` — debe permanecer deshabilitada en producción salvo durante una actualización controlada.

<a id="11"></a>
## 11. Registros y bitácoras (logs)

| Fuente | Ubicación | Rotación |
|---|---|---|
| Lector RFID | `shared/reader.log` | `logrotate` (`/etc/logrotate.d/rfid-reader`) |
| Watchdog de red | `shared/network_watchdog.log` | `logrotate` (`/etc/logrotate.d/network-watchdog`) |
| Auditoría administrativa | Tabla `audit_log` en `rfid.db` | Sin rotación automática — crece indefinidamente |
| Servicios systemd | `journalctl -u <servicio>` | Gestionado por `journald` |

`audit_log` registra acciones administrativas sensibles (ej. reinicios de servicio, apagados) con IP de origen, acción y resultado — clave para trazabilidad ante un incidente.

<a id="12"></a>
## 12. Seguridad

Se realizó una revisión de código enfocada en dos riesgos principales: **inyección de comandos** (por la capacidad del sistema de reiniciar servicios systemd remotamente) y **control de acceso** (por exponer la API a la red local).

### 12.1 Resultado de la revisión
| Hallazgo | Severidad | Estado |
|---|---|---|
| Inyección de comandos vía `service_name` | — | **Descartado** — lista blanca estricta + `shlex.quote()` en ambos puntos de entrada |
| Autenticación ausente en algún endpoint | — | **Descartado** — `@app.before_request` cubre el 100% de las rutas |
| Basic Auth sin TLS (credenciales en texto claro sobre la red) | Alta | Pendiente (decisión del responsable del sistema) |
| Contraseña de administrador débil (`admin12345`) | Media-Alta | Pendiente |
| `ALLOWED_SUBNET` deshabilitado (mecanismo ya implementado, sin usar) | Media | Pendiente |
| `/api/hardware/network/restart` sin confirmación explícita | Baja | Pendiente |
| Fallback SSH con contraseña por defecto débil y `AutoAddPolicy` | Media | Solo aplica si se usa SSH remoto |


```python
hallazgos = [
    "Inyección de comandos",
    "Endpoint sin autenticación",
    "Basic Auth sin TLS",
    "Contraseña admin débil",
    "Subred permitida desactivada",
    "Restart de red sin confirmación",
    "SSH fallback débil",
]
severidad = [0, 0, 4.5, 3.5, 2.5, 1.5, 2.5]
colores = []
for s in severidad:
    if s == 0:
        colores.append(COLOR['success'])
    elif s >= 4:
        colores.append(COLOR['danger'])
    elif s >= 2.5:
        colores.append(COLOR['warning'])
    else:
        colores.append('#F1C40F')

fig, ax = plt.subplots(figsize=(10, 5))
y_pos = np.arange(len(hallazgos))
ax.barh(y_pos, severidad, color=colores, edgecolor='white', height=0.6)
ax.set_yticks(y_pos)
ax.set_yticklabels(hallazgos, fontsize=10)
ax.invert_yaxis()
ax.set_xlim(0, 5)
ax.set_xlabel("Severidad estimada (0 = resuelto/descartado · 5 = crítico)")
ax.set_title("Panorama de seguridad — hallazgos por severidad", fontsize=13, weight='bold', color=COLOR['primary'])
ax.spines[['top', 'right']].set_visible(False)

for i, s in enumerate(severidad):
    label = "Resuelto" if s == 0 else f"{s}/5"
    ax.text(s + 0.08, i, label, va='center', fontsize=9, color=COLOR['primary'])

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_30_0.png)
    


### 12.2 Buenas prácticas ya implementadas
- Comparación de credenciales resistente a *timing attacks* (`hmac.compare_digest`)
- *Rate limiting* específico anti fuerza bruta (5 intentos/minuto, 20/15 min)
- Auditoría automática de bloqueos por exceso de intentos
- Cabeceras de seguridad `Content-Security-Policy` correctamente restrictivas
- Consultas SQL parametrizadas (sin concatenación de strings del usuario)
- Validación de nombres de archivo de respaldo contra *path traversal*
- Mecanismo de *allowlist* de IP ya construido (solo falta activarlo)

### 12.3 Recomendaciones priorizadas
1. **Alta:** colocar un proxy inverso con TLS (ej. Caddy o nginx) delante del puerto 5001.
2. **Media:** rotar `ADMIN_PASSWORD` por una contraseña generada con `secrets.token_urlsafe`.
3. **Media:** activar `ALLOWED_SUBNET` restringiendo el acceso a la subred institucional.
4. **Baja:** exigir `confirm` en `/api/hardware/network/restart`, igual que en endpoints similares.

<a id="13"></a>
## 13. Mapa de dependencias


```python

fig, ax = new_canvas(12, 8, "Mapa de dependencias y criticidad")

p_db = draw_box(ax, (4.4, 3.6), 3.2, 1.3, "rfid.db\n SPOF del sistema", fc=COLOR['danger'], fs=10.5)

p_reader = draw_box(ax, (0.4, 5.8), 3.0, 1.1, "rfid-reader\n.service", fc=COLOR['primary'])
p_crud = draw_box(ax, (4.8, 5.8), 3.0, 1.1, "rfid-crud\n.service", fc=COLOR['secondary'])
p_dash = draw_box(ax, (9.0, 5.8), 2.6, 1.1, "rfid-dashboard\n.service", fc=COLOR['secondary'])

p_kiosk = draw_box(ax, (9.0, 3.8), 2.6, 1.0, "kiosk.service", fc=COLOR['neutral'])
p_shared = draw_box(ax, (0.4, 3.7), 3.0, 1.1, "/run/rfid-shared/", fc=COLOR['neutral'])
p_watch = draw_box(ax, (0.4, 1.6), 3.0, 1.1, "network-watchdog\n.service", fc=COLOR['warning'])
p_bak = draw_box(ax, (4.8, 1.6), 3.2, 1.0, "shared/backups/\n(única mitigación del SPOF)", fc=COLOR['success'], fs=8.8)

draw_arrow(ax, (1.9, 5.8), (5.2, 4.9), color=COLOR['primary'])
draw_arrow(ax, (6.3, 5.8), (6.0, 4.9), color=COLOR['secondary'])
draw_arrow(ax, (9.0, 5.9), (7.6, 4.6), color=COLOR['secondary'])
draw_arrow(ax, (10.3, 5.8), (10.3, 4.8), "consume")
draw_arrow(ax, (1.9, 5.8), (1.9, 4.8), "modo admin", color=COLOR['neutral'])
draw_arrow(ax, (1.9, 3.7), (1.9, 2.7), color=COLOR['neutral'])
draw_arrow(ax, (6.0, 3.6), (6.0, 2.6), "respalda a", color=COLOR['success'])
draw_arrow(ax, (3.4, 2.15), (4.8, 2.4), "acceso remoto\nal CRUD depende de", color=COLOR['warning'])

ax.text(6.0, 0.5,
        "Reader / Dashboard siguen funcionando localmente si el CRUD cae.\n"
        "Si rfid.db se corrompe, TODO el sistema queda ciego — no hay réplica en caliente.",
        ha='center', fontsize=9.5, color=COLOR['primary'], weight='bold')

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_33_0.png)
    



### Tabla de criticidad

| Componente | Si falla… | Criticidad |
|---|---|---|
| `rfid.db` | Todo el sistema queda ciego (nada lee ni escribe) | 🔴 Crítico — SPOF real |
| `rfid-reader.service` | Deja de registrarse asistencia nueva | 🔴 Crítico |
| `rfid-crud.service` | Se pierde administración, pero el lector sigue operando | 🟡 No crítico para operación diaria |
| `rfid-dashboard.service` | Se pierde visualización en vivo y pantalla del kiosco | 🟡 No crítico |
| `kiosk.service` | Solo afecta la pantalla física | 🟢 Cosmético |
| `network-watchdog.service` | El Wi-Fi no se autorrepara ante una caída | 🟡 Afecta solo acceso remoto |


<a id="14"></a>
## 14. Conclusiones y recomendaciones

### 14.1 Conclusiones
El sistema desarrollado cumple su objetivo principal: automatizar el registro de asistencia
mediante RFID de forma confiable, con una arquitectura simple, autocontenida y con buenas
prácticas de seguridad ya presentes en el código (listas blancas, autenticación global,
consultas parametrizadas). El diseño modular (lector / administración / visualización como
servicios independientes) permite que una falla parcial no derribe todo el sistema, salvo por
la dependencia común de una única base de datos SQLite.

### 14.2 Recomendaciones para trabajo futuro

| Prioridad | Recomendación |
|---|---|
| 🔴 Alta | Cifrar el tráfico de la API (TLS) antes de operar en producción sin supervisión |
| 🔴 Alta | Rotar la contraseña de administrador por una robusta y única |
| 🟠 Media | Activar la restricción de subred ya implementada en el código |
| 🟠 Media | Registrar `network-watchdog.service` con un nombre consistente (`rfid-*`) para facilitar auditorías futuras |
| 🟡 Baja | Ampliar el dashboard con analítica histórica (semana/mes/semestre) |
| 🟡 Baja | Evaluar autenticación por sector cifrado MIFARE si el caso de uso lo amerita a futuro |
| 🟡 Baja | Automatizar respaldos de `rfid.db` con una tarea programada, en vez de solo bajo demanda |

<a id="15"></a>
## 15. Glosario

| Término | Definición |
|---|---|
| **RFID** | *Radio-Frequency Identification* — identificación por radiofrecuencia |
| **UID** | Identificador único de una tarjeta/etiqueta RFID |
| **HF** | *High Frequency* — banda de 13.56 MHz usada por tarjetas MIFARE |
| **SPI** | *Serial Peripheral Interface* — bus de comunicación entre RC522 y Raspberry Pi |
| **WAL** | *Write-Ahead Logging* — modo de SQLite que permite lecturas concurrentes sin bloqueo |
| **systemd** | Sistema de gestión de servicios e inicio de Linux |
| **Gunicorn** | Servidor WSGI para aplicaciones Python/Flask en producción |
| **Basic Auth** | Esquema de autenticación HTTP mediante usuario y contraseña |
| **SPOF** | *Single Point of Failure* — punto único cuya falla detiene todo el sistema |
| **CSP** | *Content Security Policy* — cabecera HTTP que restringe fuentes de contenido activo |
| **Debounce** | Técnica para ignorar lecturas repetidas en un intervalo corto de tiempo |

<a id="16"></a>
## 16. Referencias y anexos

- Documentación oficial de [SQLite — WAL mode](https://www.sqlite.org/wal.html)
- Documentación oficial de [Flask](https://flask.palletsprojects.com/) y [Gunicorn](https://gunicorn.org/)
- Datasheet del módulo **MFRC522** (fabricante NXP)
- Documentación de [systemd.service](https://www.freedesktop.org/software/systemd/man/systemd.service.html)

### Anexo A — Esquema completo de la base de datos
Ver `init_db.py` en el repositorio para el script SQL completo de creación de tablas e índices.

### Anexo B — Créditos
Documento generado como parte del Servicio Social en el ITSOEH. Este notebook es reproducible: todos los diagramas se generan con código Python (matplotlib), sin dependencias externas de diagramación, para que cualquier persona pueda clonar el repositorio y regenerarlos.

---

<div align="center">

**ITSOEH — Ingeniería en Tecnologías de la Información y Comunicación**
_Servicio Social · Sistema de Control de Asistencia RFID_

</div>
