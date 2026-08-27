<div align="center">

# Sistema de Control de Asistencia RFID
## Documentación Técnica Integral

**Instituto Tecnológico Superior del Occidente del Estao de Hidalgo (ITSOEH)**
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
> | **Fecha del reporte** | 18 de Junio del 2026 (Actualizado a Agosto) |

---

## Acerca de este documento

Este notebook documenta de forma técnica y visual el **Sistema de Control de Asistencia por RFID** desarrollado como parte del Servicio Social en el ITSOEH. Cubre arquitectura, hardware, software, base de datos, seguridad y dependencias del sistema, con diagramas generados en Python para que el reporte sea reproducible, versionable en Git y visualmente claro tanto en Jupyter como en GitHub.

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

Si las librerías `mfrc522`/`RPi.GPIO` no están disponibles en el entorno (por
ejemplo, ejecutando el script fuera de la Raspberry Pi), `RFID_OK` queda en
`False`. Esto determina qué rama del `main()` se ejecuta — ver §4.4.

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

Si la misma tarjeta se lee de nuevo dentro de `DEBOUNCE_S` (2 s) desde su
última lectura, se ignora — evita que una sola pasada de tarjeta genere
múltiples registros mientras el usuario la retira del lector.

**Modo administrador**

```python
if _modo_admin_activo():
    _notificar_admin_scan(uid_s)
    log.info(f"[ADMIN-SCAN   ]  UID: {uid_s}  → capturado (sin registro)")
    time.sleep(POLL_S)
    continue
```

`_modo_admin_activo()` revisa si existe el archivo de señal
`/run/rfid-shared/rfid_admin_mode`, creado por el panel CRUD cuando un
administrador va a dar de alta una tarjeta nueva. Mientras ese archivo
existe, el lector **no** registra asistencia: solo captura el UID y lo
escribe (con bloqueo exclusivo `fcntl.flock`) en
`/run/rfid-shared/rfid_admin_uid`, para que el CRUD lo lea y lo asocie al
estudiante en alta. Así se comunican dos procesos independientes (`root` y
`admin`) sin tocar la base de datos directamente.

**Inserción en base de datos (`procesar`)**

Fuera de modo admin, cada UID pasa por `procesar()`, que resuelve uno de
cuatro escenarios (ver el diagrama de decisión más arriba en esta sección) y
siempre inserta un registro en `registros_asistencia`:

1. UID no encontrado en `tarjetas` → `rebote`, `"UID no registrado"`.
2. Tarjeta inactiva o estudiante inactivo → `rebote`, motivo correspondiente.
3. Ya existe un `aceptado` ese mismo día para ese UID → `ya_escaneado`, con
   contador de reincidencia.
4. Primer escaneo válido del día → `aceptado`.

Todas las inserciones usan parámetros preparados (`?`), sin concatenación
de strings — evita inyección SQL.

**Reinicio automático del chip**

```python
if time.time() - ultima_lectura_ok > REINIT_TIMEOUT:
    reinicios += 1
    reader.MFRC522_Init()
```

Si pasan más de `REINIT_TIMEOUT` (8 s) sin que el propio hardware responda
(no se refiere a la ausencia de tarjetas, sino a fallos de comunicación con
el chip), se reinicializa el RC522 — compensa fallos intermitentes de SPI,
comunes en módulos económicos.

---

### 4.2 Protocolo MIFARE — por qué no se usa autenticación de sector

Las tarjetas MIFARE Classic organizan su memoria en **sectores protegidos**
por llaves criptográficas (Key A / Key B). Leer o escribir *datos* dentro de
esos sectores requiere autenticación (`MFRC522_Auth`).

Este sistema **no lee ni escribe datos dentro de la tarjeta** — únicamente
necesita el **UID de fábrica**, que se obtiene con el procedimiento de
*Request* + *Anticollision* durante la fase de **selección** de la tarjeta,
la cual ocurre **antes** de cualquier autenticación de sector en el
protocolo ISO14443A. El flujo se detiene justo ahí porque no hay necesidad
de autenticar si nunca se va a acceder a un bloque de datos.

**Implicación de seguridad:** en tarjetas MIFARE Classic estándar el UID es
de solo lectura, pero existen tarjetas regrabables ("*magic cards*")
diseñadas para clonar UIDs arbitrarios. Es decir, el sistema no verifica una
identidad criptográficamente firmada, sino un número de serie — la
seguridad del control de acceso descansa en que la lista de UIDs válidos en
`rfid.db` esté bien controlada administrativamente, **no** en una propiedad
criptográfica de la tarjeta. Es un nivel de seguridad razonable para control
de asistencia (bajo riesgo), pero insuficiente si en el futuro el sistema
protegiera activos críticos — en ese caso, la vía sería migrar a MIFARE
DESFire (autenticación AES) u otro esquema con autenticación mutua.

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

**Estado actual del código:** cuando `mfrc522`/`RPi.GPIO` no se pueden
importar, `RFID_OK` queda en `False` y `main()` entra directo en un loop de
espera pasivo:

```python
if not RFID_OK:
    log.warning("Sin hardware RFID — proceso en espera (simulación).")
    while True:
        time.sleep(60)
```

Es importante ser precisos: esto **no simula lecturas de tarjetas**, solo
evita que el proceso truene por falta de hardware y lo deja "vivo" sin hacer
nada — para efectos prácticos, el lector queda inactivo mientras tanto.

**Cómo probar la lógica de negocio sin hardware real:** la función que vale
la pena probar de forma aislada es `procesar()`, ya que ahí vive toda la
lógica de aceptado/rebote/ya_escaneado y no depende del hardware en
absoluto — solo de un UID (`string`) y acceso a `rfid.db`:

```bash
cd shared
python3 -c "
from rfid_reader import procesar
resultado = procesar('3184920157')  # UID de prueba, debe existir en tarjetas
print(resultado)
"
```

Esto ejecuta exactamente la misma lógica que correría el lector real ante
una tarjeta física, sin necesitar el RC522 conectado.

**Cambiar entre modo real y espera pasiva** no requiere ninguna bandera: es
automático según si `mfrc522`/`RPi.GPIO` están instalados en el entorno.
Para forzar el modo hardware en la propia Pi basta con tener el módulo
conectado y las dependencias instaladas (incluidas en `requirements.txt`).

> **Nota para trabajo futuro:** si se necesita probar el flujo completo
> (loop, debounce, colores en consola) sin tarjeta física, una mejora
> razonable sería agregar un modo `--simulate` que acepte UIDs por teclado
> en vez de leer el RC522 — actualmente esa opción **no existe** en el
> código; el modo sin hardware únicamente mantiene el proceso vivo.

<a id="5"></a>
## 5. Software — estructura y servicios

### 5.1 Estructura de carpetas

```text
/home/admin/rfid-system/
├── shared/
│   ├── rfid.db                 # Base de datos SQLite (única fuente de verdad)
│   ├── rfid_reader.py          # Lector RFID (servicio root)
│   ├── init_db.py              # Script de inicialización de esquema
│   ├── network_watchdog.sh     # Vigilancia y reconexión Wi-Fi automática
│   ├── reader.log
│   └── backups/                # Respaldos periódicos de rfid.db
├── crud/
│   ├── app_crud.py             # API REST + panel administrativo (Flask)
│   ├── rfid_software_admin.py  # Gestión de servicios systemd y respaldos
│   ├── static/fotos/           # Fotografías de estudiantes
│   └── templates/
├── dashboard/
│   ├── app_dashboard.py        # Panel de métricas en tiempo real (Flask)
│   └── templates/dashboard.html
├── .env                        # Variables de entorno (credenciales, subred permitida)
└── seed_test_data.py           # Generador de datos de prueba
```

### 5.2 Servicios systemd

| Servicio | Usuario | Binding | Función | Arranque |
|---|---|---|---|---|
| `rfid-reader.service` | `root` | — | Lectura RFID y registro de asistencia | Automático, `Restart=always` |
| `rfid-crud.service` | `admin` | `0.0.0.0:5001` | API REST + panel administrativo | Automático, `Restart=always` |
| `rfid-dashboard.service` | `admin` | `127.0.0.1:5000` | Métricas y dashboard en vivo | Automático, `Restart=always` |
| `kiosk.service` | `root` | — | Chromium en modo kiosco (pantalla física) | Automático, tras `rfid-dashboard` |
| `network-watchdog.service` | `root` | — | Reconexión automática de Wi-Fi | Automático |

Los tres servicios de aplicación corren detrás de **Gunicorn** (2 workers, 2 hilos cada uno),
lo que permite atender varias peticiones concurrentes sin bloquear el proceso principal.


<a id="6"></a>
## 6. Base de datos

**Motor:** SQLite en modo **WAL** (*Write-Ahead Logging*), que permite lecturas concurrentes sin bloquear las escrituras — importante porque el lector escribe constantemente mientras el dashboard y el CRUD leen en paralelo.


```python
fig, ax = new_canvas(13, 8, "Modelo entidad-relación — rfid.db")

def table_box(ax, xy, w, h, title, fields, fc):
    x, y = xy
    outer = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.05",
                            linewidth=1.6, edgecolor='white', facecolor=fc, zorder=2)
    ax.add_patch(outer)
    header_h = 0.55
    ax.add_patch(mpatches.Rectangle((x, y + h - header_h), w, header_h,
                 facecolor='none', edgecolor='white', linewidth=1.2, zorder=3))
    ax.text(x + w/2, y + h - header_h/2, title, ha='center', va='center',
             fontsize=10.5, weight='bold', color='white', zorder=4)
    field_text = "\n".join(fields)
    ax.text(x + 0.15, y + h - header_h - 0.12, field_text, ha='left', va='top',
             fontsize=8.2, color='white', zorder=4, linespacing=1.55, family='monospace')
    return (x, y, w, h)

t1 = table_box(ax, (0.3, 4.6), 3.6, 3.2, "estudiantes", [
    "PK id", "nombre", "apellido_paterno", "apellido_materno",
    "matricula (UNIQUE)", "carrera", "semestre", "grupo",
    "correo", "estado (activo/inactivo)", "foto"], COLOR['secondary'])

t2 = table_box(ax, (5.0, 4.6), 3.4, 2.0, "tarjetas", [
    "PK id", "uid (UNIQUE)", "FK id_estudiante",
    "activa (0/1)", "asignada_en"], COLOR['accent'])

t3 = table_box(ax, (9.2, 4.6), 3.6, 2.4, "registros_asistencia", [
    "PK id", "FK id_estudiante", "uid",
    "timestamp", "fecha_dia", "tipo_evento", "mensaje"], COLOR['primary'])

t4 = table_box(ax, (5.0, 1.0), 3.4, 2.2, "audit_log", [
    "PK id", "timestamp", "ip", "accion",
    "detalle", "resultado"], COLOR['warning'])

draw_arrow(ax, (3.9, 6.2), (5.0, 5.8), "1 estudiante\n→ N tarjetas")
draw_arrow(ax, (8.4, 5.8), (9.2, 6.2), "1 tarjeta\n→ N registros")
draw_arrow(ax, (6.7, 4.6), (6.7, 3.2), "acciones\nadministrativas", color=COLOR['neutral'])

ax.text(6.5, 0.5, "Relaciones con ON DELETE SET NULL — un registro histórico\n"
                    "sobrevive aunque se elimine el estudiante o la tarjeta.",
         ha='center', fontsize=9, style='italic', color=COLOR['neutral'])

plt.tight_layout()
plt.show()
```


    
![png](README_files/README_19_0.png)
    



### 6.1 Índices y rendimiento

Se definieron **9 índices** sobre las columnas más consultadas (fecha, UID, tipo de evento,
estado, semestre, y combinaciones fecha+evento / estudiante+evento), pensados para las
consultas frecuentes del dashboard y las exportaciones — evitan *table scans* completos
conforme la tabla `registros_asistencia` crece con el uso diario.

### 6.2 Respaldos
Los respaldos se generan bajo demanda (`DatabaseManager.create_backup`) con nombre
`rfid_backup_YYYYMMDD_HHMMSS.db`, validado contra una expresión regular estricta antes de
cualquier operación de restauración — evita *path traversal* al construir la ruta del archivo.
No existe replicación en tiempo real: el respaldo es la única defensa ante corrupción del
archivo principal (ver [sección 13](#13)).


<a id="7"></a>
## 7. API REST

Expuesta por `app_crud.py` en el puerto **5001**, protegida con Basic Auth (`hmac.compare_digest`, resistente a *timing attacks*) aplicada globalmente vía `@app.before_request` — ninguna ruta queda desprotegida por descuido.

| Endpoint | Método | Función |
|---|---|---|
| `/api/estudiantes` | GET | Lista/búsqueda de estudiantes |
| `/api/tarjetas` | GET | Lista de tarjetas registradas |
| `/api/rfid/guardar-uid` | POST | Asocia un UID capturado a un estudiante |
| `/api/rfid/admin-scan/status` | GET | Estado del modo "escaneo administrativo" |
| `/api/audit-log` | GET | Consulta la bitácora de auditoría |
| `/api/export/estudiantes` | GET | Descarga CSV de estudiantes (streaming) |
| `/api/export/registros` | GET | Descarga CSV de asistencia por fecha (streaming) |
| `/api/hardware/services` | GET | Estado de los servicios systemd |
| `/api/hardware/services/<servicio>/<accion>` | POST | Start/stop/restart de un servicio (lista blanca) |
| `/api/hardware/network/restart` | POST | Reinicia NetworkManager |
| `/api/hardware/system/optimize` | POST | Libera caché de memoria |
| `/api/software/database/status` | GET | Tamaño de BD, conteos, respaldos disponibles |
| `/api/migrate` | POST | Aplica migraciones de esquema (protegido por *feature flag*) |

El panel **dashboard** (puerto 5000, solo accesible en `localhost`) expone por separado `/api/estado` y `/api/ultimo-evento`, consumidos por el propio navegador en modo kiosco.

<a id="8"></a>
## 8. Flujo de datos de extremo a extremo


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
