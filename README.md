<div align="center">

# Sistema de Control de Asistencia por RFID
### Documentación técnica completa · ITSOEH — ITIC's

**Instituto Tecnológico Superior del Occidente del Estado de Hidalgo**  
**Ingeniería en Tecnologías de la Información y Comunicaciones**

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Gunicorn](https://img.shields.io/badge/Gunicorn-26.0-499848?logo=gunicorn&logoColor=white)](https://gunicorn.org/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20mode-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/wal.html)
[![Estado](https://img.shields.io/badge/Estado-Producci%C3%B3n-success)](https://github.com/AdrianMorenoM/rfid-attendance-system)
[![Tests](https://img.shields.io/badge/Tests-pytest-blue?logo=pytest)](https://docs.pytest.org/)

</div>

---

> **Datos del proyecto**
>
> | Campo | Valor |
> |---|---|
> | **Estudiante** | Adrián Moreno Méndez |
> | **Matrícula** | 22011747 |
> | **Asesor** | José Martín Oropeza Méndez |
> | **Modalidad** | Servicio Social |
> | **Última actualización** | Octubre 2026 |

---

## Tabla de contenido

1. [Descripción general](#1-descripción-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Requisitos de hardware](#4-requisitos-de-hardware)
5. [Instalación y puesta en marcha](#5-instalación-y-puesta-en-marcha)
6. [Configuración](#6-configuración)
7. [Servicios systemd](#7-servicios-systemd)
8. [Base de datos](#8-base-de-datos)
9. [API — referencia rápida](#9-api--referencia-rápida)
10. [Seguridad](#10-seguridad)
11. [Pruebas](#11-pruebas)
12. [Mantenimiento y operación](#12-mantenimiento-y-operación)
13. [Troubleshooting](#13-troubleshooting)
14. [Glosario](#14-glosario)

---
15. [Seguridad y operación](#15-seguridad-y-operación)
16. [Directorios de ejecución (tmpfiles)](#16-directorios-de-ejecución-tmpfiles)
17. [Respaldo fuera de la Pi](#17-respaldo-fuera-de-la-pi)
18. [Cortes de energía](#18-cortes-de-energía)

## 1. Descripción general

Sistema completo de control de asistencia mediante tarjetas RFID, desarrollado sobre **Raspberry Pi 4 + lector RC522**, que automatiza el registro de entradas sin intervención manual. Cada estudiante acerca su tarjeta al lector; el sistema la identifica, decide si el acceso es válido y guarda el evento en una base de datos local SQLite en modo WAL.

El sistema está compuesto por **tres servicios independientes** más dos procesos de apoyo:

| Servicio | Puerto | Descripción |
|---|---|---|
| `rfid-reader` | — | Lee tarjetas via SPI, aplica lógica de acceso, escribe en la DB |
| `rfid-crud` | 5001 | Panel administrativo Flask — CRUD completo, API REST, gestión de hardware |
| `rfid-dashboard` | 5000 | Dashboard de visualización en tiempo real (solo lectura) |
| `network-watchdog` | — | Reconecta Wi-Fi automáticamente ante caídas de conectividad |
| `rfid-incremental-vacuum` | — | Timer diario a las 03:30 h que ejecuta VACUUM INCREMENTAL en la DB |

---

## 2. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────┐
│                     Raspberry Pi 4                      │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐  ┌─────────────┐ │
│  │ rfid-reader  │    │  rfid-crud   │  │rfid-dashboard│ │
│  │  (root/SPI)  │    │  :5001       │  │  :5000      │ │
│  └──────┬───────┘    └──────┬───────┘  └──────┬──────┘ │
│         │                   │                  │        │
│         └───────────────────┼──────────────────┘        │
│                             │                           │
│                     ┌───────▼────────┐                  │
│                     │   rfid.db      │                  │
│                     │  (SQLite WAL)  │                  │
│                     └───────────────┘                   │
│                                                         │
│  ┌────────────────────┐   ┌──────────────────────────┐  │
│  │  network-watchdog  │   │ rfid-incremental-vacuum  │  │
│  │  (bash, 30s loop)  │   │ (timer: diario 03:30 h)  │  │
│  └────────────────────┘   └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Comunicación entre reader y CRUD (modo admin-scan):**  
Se usan archivos de señal en `/run/rfid-shared/`:

| Archivo | Propósito |
|---|---|
| `rfid_admin_mode` | Flag: activa el modo captura masiva de UIDs |
| `rfid_admin_uid` | UID leído en modo admin (con flock exclusivo) |
| `rfid_reader_status` | Estado actual del reader (`ok` / `error`) |
| `fijar_hora.req` | Buzón de entrada: petición de fijar la hora (la deja el CRUD) |

---

## 3. Estructura del repositorio

```
rfid-system/
├── common/        # init_db.py, rfid_reloj.py, run_incremental_vacuum.py
├── reader/        # rfid_reader.py y su log (reader.log)
├── crud/          # app_crud.py, reloj_api.py, rfid_software_admin.py, static/, templates/
├── dashboard/     # app_dashboard.py (puerto 5000) y templates/
├── data/          # rfid.db y backups/ (no versionado)
├── deploy/        # systemd/, nginx/, polkit/, system/ (ver deploy/README.md)
├── scripts/       # fijar hora, watchdog, wrapper de systemctl, health_check, run_backup
├── logs/          # access.log, error.log, backup_auto.log, health_check.log
├── shared/        # log del watchdog de red
├── requirements.txt
└── tests/         # unit/ (CI) y system/ (en la Pi)
```

---

## 4. Requisitos de hardware

### 4.1 Componentes

| Componente | Especificación mínima |
|---|---|
| Raspberry Pi | 4 Model B (2 GB RAM o más) |
| Lector RFID | RC522 (SPI, 3.3 V) |
| Tarjetas | MIFARE Classic 1K / 4K o MIFARE Ultralight |
| MicroSD | 16 GB clase 10 (A1 o superior recomendado) |
| Fuente | Oficial 5 V / 3 A USB-C |

### 4.2 Conexión RC522 → Raspberry Pi 4

| RC522 | Función | Pin físico RPi4 | GPIO BCM |
|---|---|---|---|
| 3.3V | Alimentación | 1 | — |
| RST | Reset | 22 | GPIO25 |
| GND | Tierra | 6 | — |
| IRQ | No conectar | — | — |
| MISO | SPI MISO | 21 | GPIO9 |
| MOSI | SPI MOSI | 19 | GPIO10 |
| SCK | SPI CLK | 23 | GPIO11 |
| SDA/SS | SPI CE0 | 24 | GPIO8 |

> ⚠️ **El RC522 opera a 3.3 V. Conectarlo a 5 V daña el módulo y puede dañar la Pi.**

### 4.3 Habilitar SPI en Raspberry Pi OS

```bash
sudo raspi-config
# Interfacing Options → SPI → Enable
sudo reboot
# Verificar:
ls /dev/spidev*   # debe aparecer spidev0.0
```

---

## 5. Instalación y puesta en marcha

### 5.1 Clonar el repositorio

```bash
cd /home/admin
git clone <URL-del-repositorio> rfid-system
cd rfid-system
```

### 5.2 Crear entorno virtual e instalar dependencias

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5.3 Crear el archivo de variables de entorno

```bash
cp .env.example .env   # o crear desde cero
nano .env
```

Contenido mínimo requerido (ver sección 6 para la referencia completa):

```ini
ADMIN_USER=admin
ADMIN_PASSWORD=cambia_esto_por_una_contraseña_fuerte
```

### 5.4 Inicializar la base de datos

```bash
python common/init_db.py
# Salida esperada:
# ✅ Base de datos lista en: /home/admin/rfid-system/data/rfid.db
# WAL mode activado — lecturas concurrentes sin bloqueo.
```

### 5.5 Directorios de señal (tmpfiles)

`/run` vive en RAM, así que los directorios se crean en cada arranque con tmpfiles
(ver sección 16). No los crees a mano.

```bash
sudo groupadd -f rfid-shared
sudo usermod -aG rfid-shared rfid-svc
sudo install -o root -g root -m 644 deploy/system/rfid-shared.conf deploy/system/rfid-reloj.conf /etc/tmpfiles.d/
sudo systemd-tmpfiles --create && sync
```

### 5.6 Instalar y habilitar los servicios systemd

```bash
# Copiar unidades al directorio de systemd
sudo cp /home/admin/rfid-system/deploy/systemd/rfid-incremental-vacuum.service /etc/systemd/system/
sudo cp /home/admin/rfid-system/deploy/systemd/rfid-incremental-vacuum.timer   /etc/systemd/system/
# (Los archivos .service de reader, crud y dashboard se crean según la plantilla de la Wiki)

sudo systemctl daemon-reload
sudo systemctl enable rfid-reader rfid-crud rfid-dashboard rfid-incremental-vacuum.timer
sudo systemctl start  rfid-reader rfid-crud rfid-dashboard rfid-incremental-vacuum.timer
```

### 5.7 Verificar que todo esté activo

```bash
sudo systemctl status rfid-reader rfid-crud rfid-dashboard
# Acceder al panel admin:
# https://<IP-de-la-Pi>:8443  (LAN) o https://<IP-Tailscale> (443)
# Acceder al dashboard (desde la Pi o red local):
# https://<IP-de-la-Pi>:8443  (el dashboard sale por nginx)
```

---

## 6. Configuración

Todas las variables se leen desde el archivo `.env` en la raíz del proyecto.  
Las marcadas con ★ son **obligatorias**; el servicio no arranca sin ellas.

| Variable | Obligatoria | Valor por defecto | Descripción |
|---|---|---|---|
| `ADMIN_USER` | ★ | — | Usuario del panel administrativo |
| `ADMIN_PASSWORD` | ★ | — | Contraseña del panel administrativo |
| `ALLOWED_SUBNET` | — | `disabled` | CIDR(s) permitidos, ej. `192.168.1.0/24`. `disabled` = sin restricción de IP |
| `ALLOW_HTTP_MIGRATIONS` | — | `false` | Activa el endpoint `/api/migrate` (solo para migraciones manuales) |
| `RFID_SSH_HOST` | — | `127.0.0.1` | Host para modo SSH remoto en `rfid_software_admin.py` |
| `RFID_SSH_USER` | — | `admin` | Usuario SSH |
| `RFID_SSH_KEY_PATH` | — | — | Llave privada SSH (obligatoria si se usa SSH remoto; ya no hay contraseña) |
| `RFID_SSH_KNOWN_HOSTS` | — | `~/.ssh/known_hosts` | Archivo con la huella del host, verificada a mano |
| `RFID_SSH_PORT` | — | `22` | Puerto SSH |
| `RFID_USE_SSH` | — | `auto` | `auto`, `always`, `never` |

---

## 7. Servicios systemd

> **Nota:** los ejemplos siguientes son ilustrativos. Las unidades reales y sus drop-ins (hardening, watchdog, espera de hora) están versionados en `deploy/systemd/`; los servicios corren como `rfid-svc`, no como root.

### 7.1 rfid-reader

```ini
[Unit]
Description=RFID Reader Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/admin/rfid-system/reader
EnvironmentFile=/home/admin/rfid-system/.env
ExecStart=/home/admin/rfid-system/venv/bin/python /home/admin/rfid-system/reader/rfid_reader.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7.2 rfid-crud

```ini
[Unit]
Description=RFID CRUD Service (Puerto 5001)
After=network.target rfid-reader.service

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/rfid-system/crud
EnvironmentFile=/home/admin/rfid-system/.env
ExecStart=/home/admin/rfid-system/venv/bin/gunicorn \
    --workers 2 --threads 2 \
    --timeout 120 \
    --bind 0.0.0.0:5001 \
    app_crud:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7.3 rfid-dashboard

```ini
[Unit]
Description=RFID Dashboard Service (Puerto 5000)
After=network.target rfid-reader.service

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/rfid-system/dashboard
EnvironmentFile=/home/admin/rfid-system/.env
ExecStart=/home/admin/rfid-system/venv/bin/gunicorn \
    --workers 2 --threads 2 \
    --timeout 30 \
    --bind 127.0.0.1:5000 \
    app_dashboard:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **Nota:** El dashboard escucha solo en `127.0.0.1` (loopback) intencionalmente; para exponerlo en la red local, usar un proxy reverso (nginx) con control de acceso.

### 7.4 rfid-incremental-vacuum (timer)

Ejecuta un `PRAGMA incremental_vacuum` diario a las 03:30 h ± 5 min (aleatorio) para recuperar páginas libres sin bloquear la DB.

```bash
# Estado del timer:
systemctl status rfid-incremental-vacuum.timer
systemctl list-timers | grep rfid
```

### 7.5 network-watchdog

Script bash en `scripts/rfid-network-watchdog.sh` (se instala en `/usr/local/sbin/`). Ya existe `deploy/systemd/network-watchdog.service`; ejemplo equivalente:

```ini
[Unit]
Description=RFID Network Watchdog
After=network-online.target

[Service]
Type=simple
User=root
ExecStart=/bin/bash /usr/local/sbin/rfid-network-watchdog.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Parámetros relevantes en el script:

| Variable | Valor | Descripción |
|---|---|---|
| `CHECK_INTERVAL` | 30 s | Segundos entre chequeos de conectividad |
| `FAIL_THRESHOLD` | 3 | Chequeos fallidos consecutivos antes de reconectar |
| `PING_TARGETS` | 8.8.8.8, 1.1.1.1 | Destinos de ping para verificar internet |
| `PING_TIMEOUT` | 3 s | Timeout por intento de ping |

---

## 8. Base de datos

### 8.1 Esquema

```sql
-- Estudiantes
CREATE TABLE estudiantes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT NOT NULL,
    apellido_paterno TEXT NOT NULL,
    apellido_materno TEXT,
    matricula        TEXT UNIQUE NOT NULL,
    carrera          TEXT DEFAULT 'ITIC''s',
    semestre         INTEGER,
    grupo            TEXT DEFAULT '',
    correo           TEXT,
    estado           TEXT DEFAULT 'activo' CHECK(estado IN ('activo','inactivo')),
    foto             TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Tarjetas RFID
CREATE TABLE tarjetas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT UNIQUE NOT NULL,       -- número de fábrica de la tarjeta
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    activa        INTEGER DEFAULT 1 CHECK(activa IN (0,1)),
    asignada_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Registros de asistencia
CREATE TABLE registros_asistencia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante INTEGER REFERENCES estudiantes(id) ON DELETE SET NULL,
    uid           TEXT NOT NULL,
    timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_dia     TEXT NOT NULL,              -- 'YYYY-MM-DD', indexado
    tipo_evento   TEXT NOT NULL
                  CHECK(tipo_evento IN ('aceptado','rebote','ya_escaneado','desconocido','entrada')),
    mensaje       TEXT DEFAULT ''
);

-- Bitácora de auditoría
CREATE TABLE audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ip        TEXT,
    accion    TEXT NOT NULL,
    detalle   TEXT,
    resultado TEXT NOT NULL
);
```

### 8.2 Índices

```sql
CREATE INDEX idx_reg_fecha         ON registros_asistencia(fecha_dia);
CREATE INDEX idx_reg_uid           ON registros_asistencia(uid);
CREATE INDEX idx_reg_evento        ON registros_asistencia(tipo_evento);
CREATE INDEX idx_reg_fecha_evento  ON registros_asistencia(fecha_dia, tipo_evento);
CREATE INDEX idx_reg_est_evento    ON registros_asistencia(id_estudiante, tipo_evento);
CREATE INDEX idx_tarj_uid          ON tarjetas(uid);
CREATE INDEX idx_tarj_est_activa   ON tarjetas(id_estudiante, activa);
CREATE INDEX idx_est_estado        ON estudiantes(estado);
CREATE INDEX idx_est_semestre      ON estudiantes(semestre);
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp);
```

### 8.3 Pragmas de conexión

```python
PRAGMA journal_mode=WAL;      # lectura concurrente sin bloqueo
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;    # balance durabilidad/rendimiento
PRAGMA auto_vacuum=INCREMENTAL; # vacuum controlado (ver timer)
```

### 8.4 Crecimiento estimado

| Alumnos activos | Escaneos/día | Crecimiento/día | Por semestre | Por año |
|---|---|---|---|---|
| 300 | 2–4 por alumno | ~150 KB | ~13 MB | ~30 MB |
| 500 | 2–4 por alumno | ~300 KB | ~27 MB | ~60 MB |

---

## 9. API — referencia rápida

Todas las rutas del panel admin (`:5001`) requieren **HTTP Basic Auth**.  
Formato de respuesta: `{"success": true|false, ...}` salvo exportaciones y `/`.

### Estadísticas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/estadisticas` | Contadores del día (aceptados, tarjetas activas, total registros) |
| GET | `/api/analytics` | Asistencia 7 días, por semestre, por hora, top 10 alumnos |
| GET | `/api/asistencia/hoy` | IDs de estudiantes presentes hoy |

### Estudiantes

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/estudiantes` | Lista (filtros: `semestre`, `grupo`, `buscar`) |
| POST | `/api/estudiantes` | Crear estudiante |
| GET | `/api/estudiantes/<id>` | Obtener uno |
| PUT | `/api/estudiantes/<id>` | Actualizar |
| DELETE | `/api/estudiantes/<id>` | Eliminar (foto se borra del disco) |
| GET | `/api/estudiantes/grupos` | Agrupados por semestre/grupo |
| GET | `/api/estudiantes/<id>/perfil` | Perfil completo con tarjetas y últimos 90 registros |
| POST | `/api/estudiantes/promover` | Sube semestre a un grupo o lista de IDs |
| POST | `/api/estudiantes/baja-masiva` | Marca como inactivos en bloque |
| POST | `/api/estudiantes/alta-masiva` | Importación masiva (array JSON) |

### Tarjetas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/tarjetas` | Lista paginada. Parámetros: `limit` (máx. 200), `offset`, `semestre`, `grupo`, `sin_asignar=1`. Orden `asignada_en DESC, id DESC` |
| GET | `/api/tarjetas/<id>` | Una tarjeta (404 si no existe) |
| POST | `/api/tarjetas` | Crear/asignar tarjeta |
| PUT | `/api/tarjetas/<id>` | Actualizar |
| DELETE | `/api/tarjetas/<id>` | Eliminar |
| POST | `/api/tarjetas/bulk-toggle` | Activar/desactivar por lista de IDs |
| GET | `/api/rfid/desconocidos` | UIDs rebotados no registrados (top 50) |
| GET | `/api/rfid/tarjetas-sin-asignar` | Tarjetas sin estudiante asignado |
| GET | `/api/rfid/alumnos-sin-tarjeta` | Alumnos activos sin tarjeta |
| GET | `/api/rfid/historial/<uid>` | Últimos 100 registros de un UID |
| GET | `/api/rfid/ultimo-scan` | Último evento registrado |

### RFID — captura de UID

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/rfid/listen/start` | Activa modo escucha para capturar 1 UID |
| GET | `/api/rfid/listen/status` | Estado del modo escucha |
| POST | `/api/rfid/listen/stop` | Cancela modo escucha |
| POST | `/api/rfid/admin-scan/start` | Inicia sesión de captura masiva (hasta expirar) |
| GET | `/api/rfid/admin-scan/status` | UIDs capturados en la sesión |
| POST | `/api/rfid/admin-scan/stop` | Cierra sesión de captura masiva |
| POST | `/api/rfid/admin-scan/guardar` | Persiste UIDs capturados en `tarjetas` |
| POST | `/api/rfid/admin-scan/eliminar` | Elimina UIDs de `tarjetas` (opción `forzar`) |

### Registros y auditoría

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/registros` | Lista paginada (filtros: `fecha`, `estado`, `uid`) |
| GET | `/api/audit-log` | Bitácora de auditoría (filtros: `accion`, `ip`) |

### Hardware y sistema

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/hardware/status` | CPU temp, RAM, disco, uptime, estado RFID y DB |
| GET | `/api/hardware/services` | Estado de los 3 servicios RFID |
| POST | `/api/hardware/services/<svc>/<action>` | start/stop/restart/enable/disable |
| GET | `/api/hardware/services/<svc>/logs` | Últimas N líneas de journalctl |
| GET | `/api/hardware/network/status` | IP, gateway, DNS, redes Wi-Fi disponibles |
| POST | `/api/hardware/network/scan` | Rescan de redes Wi-Fi |
| POST | `/api/hardware/network/connect` | Conectar a red (SSID + password) |
| POST | `/api/hardware/network/disconnect` | Desconectar |
| POST | `/api/hardware/system/reboot` | Reiniciar Pi (requiere `confirm: true`) |
| POST | `/api/hardware/system/shutdown` | Apagar Pi (requiere `confirm: true`) |
| POST | `/api/hardware/system/optimize` | Liberar caché del sistema |

### Base de datos — desde el panel

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/software/database/status` | Tamaño, conteos, número de respaldos |
| GET | `/api/health/db` | Integridad (`PRAGMA integrity_check`) |
| POST | `/api/software/database/backup` | Crear respaldo ahora |
| GET | `/api/software/database/backups` | Listar respaldos |
| POST | `/api/software/database/restore` | Restaurar (requiere `confirm: true`) |
| DELETE | `/api/software/database/backups/<file>` | Eliminar respaldo |
| POST | `/api/software/database/purge/preview` | Previsualizar cuántos registros se borrarían |
| POST | `/api/software/database/purge` | Purgar registros (crea respaldo previo automático) |

### Exportación

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/export/estudiantes` | CSV streaming — padrón completo |
| GET | `/api/export/registros?fecha=YYYY-MM-DD` | CSV streaming — asistencia de una fecha |

---

## 10. Seguridad

### 10.1 Mecanismos implementados

| Mecanismo | Estado | Detalle |
|---|---|---|
| HTTP Basic Auth en todas las rutas | ✅ Activo | Comparación con `hmac.compare_digest` (resistente a timing attacks) |
| Rate limiting global | ✅ Activo | 60 req/min por IP; exento para usuarios autenticados |
| Rate limiting de fallos de auth | ✅ Activo | 5 intentos/min · 20 intentos/15 min por IP |
| Registro de IPs bloqueadas en audit_log | ✅ Activo | — |
| Restricción por subred (allowlist) | ⚙️ Listo, inactivo | Activar con `ALLOWED_SUBNET=192.168.x.0/24` en `.env` |
| Content Security Policy | ✅ Activo | Cabecera en todas las respuestas |
| X-Frame-Options, X-Content-Type-Options | ✅ Activo | — |
| Prevención de inyección SQL | ✅ Activo | 100% consultas parametrizadas |
| Validación de nombres de respaldo | ✅ Activo | Regex `rfid_backup_\d{8}_\d{6}\.db` |
| Neutralización de fórmulas CSV | ✅ Activo | Prefijo `'` en campos iniciados con `= + - @` |
| Cabecera `X-Requested-With` en destructivos | ✅ Activo | Operaciones de reboot, shutdown, restore, baja masiva |
| Confirmación explícita en destructivos | ✅ Activo | Campo `confirm: true` requerido |
| HTTPS | ✅ Activo | nginx con TLS (ver 15.3) |

### 10.2 Recomendaciones pendientes (priorizadas)

1. **[Alta]** Cambiar `ADMIN_PASSWORD` por una cadena aleatoria de ≥16 caracteres.
2. **[Media]** Activar `ALLOWED_SUBNET` con el rango de la red institucional.
3. **[Baja]** Añadir confirmación explícita a `/api/hardware/network/restart`.

---

## 11. Pruebas

### 11.1 Ejecutar la suite completa

```bash
cd shared
bash tests/run_tests.sh
# o directamente:
source ../venv/bin/activate
pytest tests/ -v --tb=short
```

### 11.2 Archivos de prueba

| Archivo | Qué cubre |
|---|---|
| `test_smoke.py` | Arranque básico de cada módulo |
| `test_reader.py` | Lógica de acceso del lector (mocks de hardware) |
| `test_reader_extended.py` | Casos límite: debounce, modo admin, estado de archivos de señal |
| `test_crud_api.py` | Endpoints REST del panel administrativo |
| `test_dashboard_y_db.py` | Dashboard y consultas a la DB |
| `test_software_admin.py` | `ServiceManager` y `DatabaseManager` |

### 11.3 Dependencias de prueba

```bash
pip install -r requirements-ci.txt
```

El hardware RC522 se excluye automáticamente en entornos sin SPI; el reader opera en "modo simulación" (proceso en espera).

---

## 12. Mantenimiento y operación

### 12.1 Health check

El script `scripts/health_check.sh` llama a `/api/health/db` y registra cualquier fallo en `logs/health_check.log`. Se recomienda añadirlo a un cron:

```bash
# Cada 5 minutos
*/5 * * * * /bin/bash /home/admin/rfid-system/scripts/health_check.sh
```

### 12.2 Respaldos manuales vs automáticos

Desde el panel: **Base de datos → Crear respaldo**.  
Para automatizar (recomendado), añadir a crontab:

```bash
# Respaldo cada 2 horas en horario escolar (07–20 h)
0 7-20/2 * * * curl -s -u $ADMIN_USER:$ADMIN_PASSWORD \
    -X POST http://127.0.0.1:5001/api/software/database/backup
```

Los respaldos se nombran `rfid_backup_YYYYMMDD_HHMMSS.db` y se guardan en `data/backups/`.

### 12.3 Rotación de logs

El lector genera `reader.log` en `reader/`; el watchdog genera `network_watchdog.log`.  
Se recomienda añadir una regla logrotate:

```
/home/admin/rfid-system/shared/*.log
/home/admin/rfid-system/logs/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
```

### 12.4 Vacuum incremental

El timer `rfid-incremental-vacuum.timer` ejecuta `run_incremental_vacuum.py` cada día a las 03:30 h ± 5 min. No bloquea la base de datos. Para forzar manualmente:

```bash
sudo systemctl start rfid-incremental-vacuum.service
```

### 12.5 Actualizar el esquema de la base de datos

```bash
# 1. Crear un respaldo antes de migrar
curl -s -u admin:pass -X POST http://127.0.0.1:5001/api/software/database/backup

# 2. Activar migraciones en .env
echo "ALLOW_HTTP_MIGRATIONS=true" >> .env
sudo systemctl restart rfid-crud

# 3. Ejecutar migración
curl -s -u admin:pass -X POST http://127.0.0.1:5001/api/migrate

# 4. Desactivar migraciones
sed -i 's/ALLOW_HTTP_MIGRATIONS=true/ALLOW_HTTP_MIGRATIONS=false/' .env
sudo systemctl restart rfid-crud
```

---

## 13. Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| El reader no detecta tarjetas | SPI no habilitado o cableado suelto | `ls /dev/spidev*` — si no aparece, volver a habilitar SPI en `raspi-config` |
| `rfid-crud` no arranca | Faltan `ADMIN_USER`/`ADMIN_PASSWORD` en `.env` | Verificar `.env` y reiniciar el servicio |
| Error 401 en todas las rutas | Credenciales incorrectas | Verificar usuario y contraseña |
| Error 429 en login | Demasiados intentos fallidos | Esperar 1–15 min según el límite alcanzado |
| Lectura duplicada en el mismo segundo | Debounce de 2 s no suficiente | Ajustar `DEBOUNCE_S` en `rfid_reader.py` |
| DB crece más de lo esperado | No se depuran registros viejos | Usar `/api/software/database/purge` al cierre de semestre |
| `audit_log` no existe | Migración no aplicada | Ejecutar `/api/migrate` (ver sección 12.5) |
| Wi-Fi se cae y no se recupera | `network-watchdog` detenido | `sudo systemctl restart network-watchdog` |
| Fotos no aparecen en el dashboard | Ruta relativa incorrecta | El dashboard sirve fotos desde `crud/static/fotos/` vía `/fotos/<filename>` |

---

## 14. Glosario

| Término | Significado |
|---|---|
| **UID** | Número único de fábrica de la tarjeta RFID (4 bytes, leído sin autenticar) |
| **SPI** | Serial Peripheral Interface — bus de comunicación usado entre la Pi y el RC522 |
| **WAL** | Write-Ahead Logging — modo SQLite que permite lecturas concurrentes sin bloqueo de escritura |
| **Debounce** | Ignorar lecturas repetidas de la misma tarjeta dentro de un intervalo (2 s por defecto) |
| **Tipo de evento** | `aceptado` / `rebote` / `ya_escaneado` / `desconocido` / `entrada` |
| **Modo admin-scan** | Sesión de captura masiva de UIDs sin registrar asistencia; controlada por archivos de señal en `/run/rfid-shared/` |
| **CRUD** | Create, Read, Update, Delete — panel de administración completo |
| **CSP** | Content Security Policy — cabecera HTTP que limita los recursos que el navegador puede cargar |
| **Rate limiting** | Límite de peticiones por unidad de tiempo para prevenir abuso |
| **HMAC** | Hash-based Message Authentication Code — usado aquí para comparación segura de credenciales |

---

<div align="center">

**ITSOEH · ITIC's · Servicio Social 2026**  
Adrián Moreno Méndez — Asesor: José Martín Oropeza Méndez

</div>

---

## 15. Seguridad y operación

### 15.1 Privilegios
- Los servicios corren como `rfid-svc` (sin root) con `NoNewPrivileges` y `PrivateTmp`.
- Un único archivo polkit (`deploy/polkit/50-rfid-svc.rules`) permite a `rfid-svc` controlar solo sus servicios, reiniciar/apagar y operar NetworkManager (escaneo y conexión).
- `rfid-svc` usa sudo únicamente para `rfid-systemctl-wrapper.sh`, que valida acción y servicio contra una lista blanca.
- No existe regla polkit amplia para `admin`: crear unidades requiere contraseña.

### 15.2 Reloj
La Pi no tiene RTC. Se usa `fake-hwclock` (guarda la hora cada hora y al apagar) y NTP cuando hay red.
- Reloj sincronizado: lecturas con `reloj_confiable = 1`.
- Sin NTP: fijar la hora desde el panel. El CRUD deja `fijar_hora.req` en `/run/rfid-shared/`; una unidad de root la valida y escribe la respuesta y `reloj_manual_ok` en `/run/rfid-reloj/` (solo root escribe).
- `/run` es tmpfs: la marca manual se pierde en cada arranque. Tras un apagón sin internet hay que volver a fijar la hora.

### 15.3 Acceso
- LAN: `https://<IP>:8443` (solo redes privadas).
- Tailscale: puerto 443 y SSH.
- ufw y nginx aplican doble filtro; el 443 por LAN está denegado.

### 15.4 Recuperación
1. Servicios caídos: `sudo systemctl restart rfid-reader rfid-crud rfid-dashboard`.
2. Hora incorrecta tras un apagón sin internet: fijarla desde el panel.
3. Restaurar la base: desde el panel (endpoint `/api/software/database/restore`), eligiendo un respaldo de `data/backups/`. Crea un respaldo de seguridad previo. Los respaldos se generan a diario a las 19:00. Además, cada día a las 19:30 se envía una copia fuera de la Pi (sección 17).
4. Verificar: `systemctl is-active rfid-reader rfid-crud rfid-dashboard nginx`.


---

## 16. Directorios de ejecución (tmpfiles)

| Archivo en `deploy/system/` | Contenido |
|---|---|
| `rfid-shared.conf` | `d /run/rfid-shared 2770 rfid-svc rfid-shared -` |
| `rfid-reloj.conf`  | `d /run/rfid-reloj 0750 root rfid-shared -` |

Comprobación (un `.conf` vacío falla en silencio y el directorio no se crea):

```bash
for f in /etc/tmpfiles.d/rfid-shared.conf /etc/tmpfiles.d/rfid-reloj.conf; do
  test -s "$f" || echo "ERROR: $f vacío"
done
ls -ld /run/rfid-shared /run/rfid-reloj
```

Síntoma si falta `/run/rfid-shared`: el lector registra `Permission denied ... status file`
y el escaneo masivo responde "No se pudo crear señal admin".

## 17. Respaldo fuera de la Pi

Cada día a las 19:30 (±5 min), `rfid-offsite.timer` ejecuta `rfid-offsite-backup.sh` como root:
crea un snapshot con `sqlite3 .backup`, verifica `PRAGMA integrity_check` y lo envía por `scp`
a una PC. Si hay una USB montada en `USB_DIR`, también copia ahí; si no, la omite.
Si la PC no está disponible, el servicio termina con error (`systemctl status rfid-offsite`).

### Configuración
1. Llave dedicada, sin passphrase, solo para este servicio:
   ```bash
   sudo ssh-keygen -t ed25519 -N "" -C "rfid-offsite" -f /root/.ssh/rfid_offsite
   sudo cat /root/.ssh/rfid_offsite.pub
   ```
2. Autoriza esa línea en la PC destino. En Windows, si el usuario es administrador, va en
   `C:\ProgramData\ssh\administrators_authorized_keys` (permisos solo para Administrators y SYSTEM);
   si no, en `C:\Users\<usuario>\.ssh\authorized_keys`.
3. Registra la huella del host y compárala con la de la PC antes de continuar:
   ```bash
   sudo ssh-keyscan -t ed25519 <IP_DESTINO> | sudo tee -a /root/.ssh/known_hosts
   sudo ssh-keygen -lf /root/.ssh/known_hosts
   ```
   En Windows: `ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub`.
4. Prueba: `sudo ssh -i /root/.ssh/rfid_offsite -o BatchMode=yes <usuario>@<IP_DESTINO> "echo conectado"`
5. `/etc/rfid-offsite.conf` (modo 600; hay un `deploy/system/rfid-offsite.conf.example`):
   ```
   REMOTE=<usuario>@<IP_DESTINO>
   REMOTE_DIR=rfid-backups
   KEY=/root/.ssh/rfid_offsite
   USB_DIR=/mnt/rfid-usb
   ```
6. Instala `deploy/system/rfid-offsite-backup.sh` en `/usr/local/sbin/` (modo 750) y las
   unidades `rfid-offsite.service` y `.timer` de `deploy/systemd/` en `/etc/systemd/system/`:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now rfid-offsite.timer
   ```

### Verificación
```bash
sudo systemctl start rfid-offsite.service
journalctl -u rfid-offsite -n 20 --no-pager      # debe decir: OK windows
systemctl list-timers rfid-offsite.timer
```
Prueba de restauración: descarga el snapshot y compara conteos con la base viva.
```bash
sudo scp -i /root/.ssh/rfid_offsite <usuario>@<IP_DESTINO>:rfid-backups/<archivo>.db /tmp/
sudo sqlite3 /tmp/<archivo>.db "PRAGMA integrity_check; select count(*) from estudiantes;"
sudo rm -f /tmp/<archivo>.db
```

### Mantenimiento
- La PC destino debe estar encendida y alcanzable (p. ej. por Tailscale) a la hora de la copia.
- Los snapshots no se borran solos en la PC; elimina los antiguos de vez en cuando.
- Para revocar el acceso, borra la línea de la llave en la PC destino.

## 18. Cortes de energía

La Pi no tiene RTC y un apagado brusco puede dejar archivos vacíos (se vieron `.conf` de
tmpfiles y un objeto de `.git` en 0 bytes). Tras cambiar configuración en `/etc`, ejecuta `sync`;
sube los commits con `git push` de inmediato; y no dependas solo de `data/backups/`
(ver sección 17). Recuperar un `.git` dañado:

```bash
find .git/objects -type f -size 0 -delete
git fetch origin && git reset --soft origin/main
git fsck --full
```

