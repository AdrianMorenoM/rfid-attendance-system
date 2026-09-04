<div align="center">

Sistema de Control de Asistencia por RFID

ITSOEH · Ingeniería en Tecnologías de la Información y Comunicación







Sistema local de registro de asistencia mediante tarjetas RFID, desarrollado para automatizar la identificación de estudiantes, almacenar sus registros y facilitar su consulta y administración.

</div>

📌 Descripción general

El Sistema de Control de Asistencia por RFID fue desarrollado como parte del Servicio Social en el Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH).

Su objetivo es sustituir el registro manual de asistencia por un proceso automatizado: el estudiante acerca una tarjeta RFID a un lector, el sistema identifica su tarjeta, valida su estado y registra el evento en una base de datos local. La información puede administrarse desde un panel web y consultarse mediante un dashboard de visualización.

El proyecto está diseñado para funcionar de manera local y autónoma, sin depender de servicios en la nube ni de APIs externas.

Idea central: una tarjeta identifica al estudiante → el lector captura el identificador → el sistema valida la información → la base de datos conserva el evento → los paneles muestran y administran los datos.

👤 Información del proyecto

Campo

Información

Institución

Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH)

Programa académico

Ingeniería en Tecnologías de la Información y Comunicación (ITIC)

Modalidad

Servicio Social

Estudiante

Adrián Moreno Méndez

Matrícula

22011747

Asesor

José Martín Oropeza Méndez

Reporte original

18 de junio de 2026

Actualización

Agosto de 2026

Alcance actual

Un punto de lectura RFID

Operación

Red local institucional

🎯 Objetivos

Objetivo general

Diseñar, construir y documentar un sistema de asistencia mediante RFID que sea funcional, razonablemente seguro y fácil de mantener, permitiendo su utilización diaria y facilitando la continuidad del proyecto.

Objetivos específicos

Automatizar la lectura de tarjetas RFID mediante un módulo RC522 conectado a una Raspberry Pi 4.

Mantener organizada la información de estudiantes, tarjetas y registros de asistencia.

Proporcionar un panel administrativo para gestionar estudiantes y tarjetas.

Mostrar las métricas de asistencia mediante un dashboard.

Incorporar mecanismos de recuperación ante fallas comunes.

Mantener una bitácora de acciones administrativas importantes.

Generar reportes exportables en formato CSV.

Documentar la arquitectura para facilitar el mantenimiento y transferencia del proyecto.

🧭 Índice

Arquitectura general

Flujo de funcionamiento

Hardware

Software y estructura del proyecto

Base de datos

Panel administrativo

Dashboard

Reportes y respaldos

Seguridad

Disponibilidad y recuperación

Rendimiento

Limitaciones actuales

Mejoras futuras

Estructura recomendada del repositorio

Tecnologías utilizadas

Referencias

Créditos

🏗️ Arquitectura general

El sistema está dividido en varios componentes con responsabilidades específicas. Esta separación permite que el lector RFID, la administración y la visualización funcionen como partes independientes.

flowchart LR
    A["🎫 Tarjeta RFID"] --> B["📡 RC522"]
    B --> C["🍓 Raspberry Pi 4"]

    C --> D["⚙️ Servicio lector"]
    D --> E[("🗄️ SQLite<br/>rfid.db")]

    E --> F["🖥️ Panel administrativo"]
    E --> G["📊 Dashboard"]

    F --> H["👤 Personal autorizado"]
    G --> I["👀 Visualización"]

    J["📶 Watchdog de red"] --> C
    E --> K["💾 Respaldos"]

Componentes principales

Componente

Función

Tarjeta RFID

Identifica al estudiante mediante su UID.

RC522

Detecta la tarjeta y obtiene su identificador.

Raspberry Pi 4

Ejecuta los servicios principales del sistema.

Lector RFID

Procesa las lecturas y determina el resultado del evento.

SQLite

Almacena estudiantes, tarjetas, asistencia y auditoría.

Panel administrativo

Permite administrar información y operaciones del sistema.

Dashboard

Presenta métricas y eventos recientes en modo de solo lectura.

Watchdog de red

Vigila la conexión Wi-Fi y permite recuperar conectividad.

Respaldos

Protegen la información ante fallas de la base de datos.

Punto crítico: rfid.db concentra la información utilizada por los principales componentes. Por ello representa el punto único de falla del sistema y los respaldos son una medida fundamental de continuidad.

🔄 Flujo de funcionamiento

El proceso completo desde que un estudiante presenta su tarjeta hasta que la asistencia aparece en pantalla puede resumirse así:

sequenceDiagram
    participant E as Estudiante
    participant R as RC522
    participant P as Raspberry Pi
    participant DB as SQLite
    participant D as Dashboard

    E->>R: Acerca tarjeta
    R->>P: Envía UID
    P->>DB: Consulta tarjeta y estudiante
    DB-->>P: Información y estado

    alt Tarjeta válida y estudiante activo
        P->>DB: Guarda asistencia
        DB-->>P: Registro confirmado
        D->>DB: Consulta evento reciente
        DB-->>D: Nuevo registro
        D-->>E: Muestra acceso aceptado
    else Tarjeta no válida/inactiva
        P->>DB: Guarda evento rechazado
        D->>DB: Consulta evento
        D-->>E: Muestra acceso rechazado
    end

Decisiones que toma el sistema

Cuando se detecta una tarjeta, se comprueba:

¿Está activo el modo de alta de tarjeta?

Si está activo, el UID se captura para asociarlo a un estudiante.

No se registra como asistencia.

¿Existe la tarjeta?

Si no existe, se registra un evento de rechazo.

¿La tarjeta y el estudiante están activos?

Si alguno está inactivo, el acceso se rechaza.

¿Ya se registró asistencia ese día?

Primera lectura válida → aceptado.

Lectura posterior → ya_escaneado.

¿La lectura es un duplicado inmediato?

Se utiliza un periodo de debounce de 2 segundos para evitar múltiples registros causados por una sola pasada de tarjeta.

🔌 Hardware

El sistema utiliza componentes relativamente económicos y fáciles de reemplazar.

Componente

Especificación

Cantidad

Raspberry Pi

Raspberry Pi 4 Model B

1

Lector RFID

RC522 / MFRC522, 13.56 MHz

1

Tarjetas

MIFARE Classic o compatibles

Según usuarios

Almacenamiento

microSD Clase 10, 16 GB o superior

1

Fuente

5 V / 3 A USB-C

1

Cableado

Dupont hembra-hembra

7

Gabinete

Ventilado, con acceso al GPIO

1

Conexión RC522 → Raspberry Pi

RC522

Función

Raspberry Pi

3.3V

Alimentación

Pin 1

RST

Reinicio

Pin 22 / GPIO25

GND

Tierra

Pin 6

IRQ

No utilizado

Sin conectar

MISO

Datos hacia la Pi

Pin 21 / GPIO9

MOSI

Datos hacia el lector

Pin 19 / GPIO10

SCK

Reloj SPI

Pin 23 / GPIO11

SDA / SS

Selección del dispositivo

Pin 24 / GPIO8

⚠️ Importante: el RC522 trabaja con lógica de 3.3 V. No debe conectarse a 5 V.

Alimentación

La Raspberry Pi utiliza una fuente recomendada de 5 V / 3 A. El RC522 se alimenta desde el riel de 3.3 V de la Raspberry Pi.

Una alimentación inestable puede provocar reinicios, fallos de lectura o incluso corrupción de datos si ocurre una interrupción mientras SQLite está escribiendo.

💻 Software y estructura del proyecto

El software está organizado en servicios independientes. El sistema utiliza Python, Flask, Gunicorn, SQLite y servicios de systemd.

rfid-system/
│
├── shared/
│   ├── rfid_reader.py
│   ├── init_db.py
│   ├── rfid.db
│   ├── reader.log
│   ├── network_watchdog.log
│   └── backups/
│
├── crud/
│   ├── app_crud.py
│   ├── rfid_software_admin
│   ├── static/
│   │   └── fotos/
│   └── templates/
│       └── crud_dashboard.html
│
├── dashboard/
│   ├── app_dashboard.py
│   └── templates/
│       └── dashboard.html
│
├── requirements.txt
├── .env.example
└── .gitignore

Servicios principales

Servicio

Responsabilidad

rfid-reader.service

Lectura RFID y registro de eventos

rfid-crud.service

Administración y API

rfid-dashboard.service

Visualización de métricas

network-watchdog.service

Recuperación de conectividad

kiosk.service

Modo kiosco previsto para pantalla dedicada

Los servicios se configuran para iniciar automáticamente con el sistema operativo y reiniciarse si el proceso termina inesperadamente.

🗄️ Base de datos

La información se concentra en una base de datos SQLite denominada:

rfid.db

SQLite utiliza el modo WAL (Write-Ahead Logging) para permitir que varios componentes consulten la información mientras el lector continúa escribiendo nuevos registros.

Modelo conceptual

erDiagram
    ESTUDIANTES ||--o{ TARJETAS : "puede tener"
    ESTUDIANTES ||--o{ REGISTROS_ASISTENCIA : "genera"

    ESTUDIANTES {
        integer id PK
        string nombre
        string apellido_paterno
        string apellido_materno
        string matricula UK
        string carrera
        integer semestre
        string grupo
        string correo
        string foto
        boolean activo
    }

    TARJETAS {
        integer id PK
        string uid UK
        integer estudiante_id FK
        boolean activo
    }

    REGISTROS_ASISTENCIA {
        integer id PK
        integer id_estudiante FK
        string uid
        datetime timestamp
        date fecha_dia
        string tipo_evento
        string mensaje
    }

    AUDIT_LOG {
        integer id PK
        string accion
        string resultado
        string ip
        datetime timestamp
    }

Tablas principales

Tabla

Propósito

estudiantes

Información académica y de contacto.

tarjetas

Relación entre tarjetas RFID y estudiantes.

registros_asistencia

Historial de todas las lecturas realizadas.

audit_log

Registro de operaciones administrativas sensibles.

Conservación del historial

El sistema evita eliminar automáticamente el historial cuando un estudiante deja de estar activo.

Esto permite conservar evidencia de eventos que ya ocurrieron y facilita auditorías o correcciones administrativas.

Por ello, dar de baja un estudiante es preferible a eliminarlo físicamente.

🖥️ Panel administrativo

El panel administrativo es una aplicación web protegida mediante autenticación.

Desde este panel se pueden realizar operaciones como:

👨‍🎓 Estudiantes

Alta de estudiantes.

Edición de información.

Baja individual.

Operaciones masivas.

Consulta del padrón.

🎫 Tarjetas

Asignación de tarjetas.

Activación y desactivación.

Eliminación.

Alta rápida mediante lectura RFID.

📊 Reportes

Consulta de estadísticas.

Consulta de asistencia.

Exportación del padrón.

Exportación de asistencia en CSV.

🛠️ Administración del sistema

Consulta del estado de servicios.

Consulta de recursos de la Raspberry Pi.

Reinicio de servicios.

Reinicio o apagado del equipo.

Consulta de logs.

Gestión de respaldos.

🗃️ Base de datos

Consulta del estado.

Creación de respaldos.

Restauración.

Vista previa de depuración.

Depuración filtrada por fecha, carrera, semestre, grupo o estudiante.

📊 Dashboard de visualización

El dashboard está diseñado principalmente para consulta, no para administración.

Presenta información como:

Accesos aceptados.

Accesos rechazados.

Tarjetas activas.

Eventos recientes.

Distribución de eventos por hora.

Identificación visual del último evento registrado.

El sistema separa la frecuencia de actualización:

Cada 800 ms: búsqueda de nuevos eventos.

Cada 5 s: actualización de métricas generales.

Esto evita realizar cálculos pesados con la misma frecuencia que una notificación inmediata.

📤 Reportes y respaldos

Exportación CSV

El sistema permite exportar:

Padrón completo de estudiantes.

Asistencia de un día determinado.

Las exportaciones se generan progresivamente para evitar consumir innecesariamente la memoria de la Raspberry Pi.

Además, se consideran caracteres especiales como acentos y ñ, y se aplican medidas para evitar que valores de texto sean interpretados accidentalmente como fórmulas por aplicaciones como Excel.

Respaldos

La base de datos debe respaldarse mediante los mecanismos propios de SQLite, especialmente porque el sistema utiliza WAL.

Ejemplo:

sqlite3 rfid.db ".backup 'backups/rfid_backup_$(date +%Y%m%d_%H%M%S).db'"

No se recomienda copiar simplemente rfid.db con cp mientras existen escrituras activas.

Restauración

Una restauración sustituye la base de datos utilizada por el sistema. Por ello, primero deben detenerse los servicios que la utilizan, conservar una copia del estado actual y posteriormente reiniciar los servicios.

🔐 Seguridad

La revisión del sistema identificó medidas de protección ya implementadas y algunos puntos que deben reforzarse.

Medidas implementadas

Autenticación obligatoria para el panel administrativo.

Comparación de credenciales mediante hmac.compare_digest.

Limitación de intentos de autenticación.

Registro de bloqueos por exceso de intentos.

Consultas SQL parametrizadas.

Cabeceras de seguridad HTTP.

Validación estricta de nombres de archivos de respaldo.

Lista blanca de servicios que pueden ser administrados.

Mecanismos de confirmación para operaciones sensibles.

Bitácora de operaciones administrativas.

Consideración importante sobre RFID

El sistema identifica las tarjetas mediante su UID físico. No utiliza autenticación criptográfica de sectores de la tarjeta.

Esto resulta suficiente para un sistema de asistencia de bajo riesgo, pero significa que el UID por sí mismo no debe considerarse una credencial criptográficamente fuerte.

Para escenarios donde RFID controle activos, instalaciones o información de mayor valor, sería recomendable utilizar un mecanismo de autenticación más robusto.

⚠️ Hallazgos de seguridad y mejoras

Prioridad

Situación

Recomendación

🔴 Alta

El panel administrativo utiliza HTTP local

Incorporar HTTPS/TLS

🔴 Alta

Credencial administrativa debe mantenerse robusta y exclusiva

Rotar por una contraseña aleatoria y única

🟠 Media

Restricción por subred disponible pero no activada

Activarla para limitar el acceso

🟡 Baja

Reinicio de red requiere mayor consistencia con otras operaciones

Añadir confirmación y auditoría

🟡 Baja

SSH alternativo no es el mecanismo principal

Preferir autenticación mediante llave SSH

🟡 Baja

RFID basado únicamente en UID

Evaluar autenticación criptográfica si aumenta el nivel de riesgo

Importante: las recomendaciones anteriores provienen de la revisión de seguridad documentada del proyecto y deben tratarse como tareas de mejora, no como funcionalidades actualmente garantizadas.

🛡️ Disponibilidad y recuperación

El diseño intenta evitar que una falla aislada detenga todo el sistema.

flowchart TD
    DB[("rfid.db")]
    READER["Servicio lector"]
    CRUD["Panel administrativo"]
    DASH["Dashboard"]
    WATCH["Watchdog de red"]
    BACKUP["Respaldos"]

    READER --> DB
    CRUD --> DB
    DASH --> DB
    WATCH --> READER
    DB --> BACKUP

    DB -. "Punto único de falla" .-> X["⚠️"]

¿Qué ocurre ante una falla?

Falla

Impacto

Base de datos dañada

Puede afectar simultáneamente a lector, panel y dashboard

Servicio lector detenido

No se generan nuevas asistencias hasta su recuperación

Dashboard detenido

Se pierde la visualización, pero el registro puede continuar

Panel administrativo detenido

Se pierde la administración, pero el lector puede continuar

Wi-Fi desconectado

El watchdog intenta recuperar la conectividad

Corte de energía

Existe riesgo de interrupción y corrupción; los respaldos ayudan a recuperar información

El principal riesgo arquitectónico sigue siendo la dependencia de una sola base de datos.

⚡ Rendimiento

Los tiempos documentados muestran que el sistema está orientado a una respuesta rápida para el escenario de uso previsto.

Etapa

Tiempo aproximado

Detección de tarjeta

0–75 ms

Peor caso de detección

150 ms

Consulta y escritura en SQLite

3–11 ms

Peor caso de consulta/escritura

30–65 ms

Detección del evento por dashboard

Hasta 800 ms

Tiempo total típico

~250–350 ms

Peor caso total

~1.1 s

Estos valores corresponden al comportamiento documentado del sistema y pueden variar dependiendo de la carga del equipo y del entorno.

🚧 Limitaciones actuales

El proyecto presenta algunas limitaciones que conviene conocer antes de ampliarlo:

Actualmente está pensado para un solo lector RFID.

Opera de forma local.

No depende de una plataforma cloud.

La base de datos es un único archivo SQLite.

El dashboard utiliza consultas periódicas en lugar de comunicación en tiempo real mediante WebSockets o eventos.

El modo kiosco está contemplado en la arquitectura, pero su implementación depende del despliegue de una pantalla dedicada.

La identificación RFID se basa en UID.

Los respaldos automáticos programados todavía representan una mejora pendiente.

La restricción de acceso por subred existe en el código, pero debe activarse y validarse antes de utilizarla.

🚀 Mejoras futuras

El roadmap recomendado, tomando como base la documentación del proyecto, es:

Prioridad alta

Incorporar HTTPS/TLS al panel administrativo.

Rotar la credencial administrativa por una contraseña fuerte y exclusiva.

Automatizar respaldos periódicos.

Prioridad media

Activar la restricción por subred institucional.

Mejorar la consistencia de nombres y administración de servicios.

Mantener pruebas de seguridad documentadas.

Separar o archivar registros históricos al cierre de cada ciclo escolar.

Prioridad baja

Añadir analítica histórica semanal, mensual y semestral.

Incorporar nuevas métricas al dashboard.

Evaluar mecanismos RFID con autenticación criptográfica.

Sustituir el polling del dashboard por un mecanismo de eventos en tiempo real.

📁 Estructura recomendada del repositorio

Para GitHub, se recomienda mantener separada la documentación, el código y los archivos sensibles:

rfid-system/
│
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── .env.example
│
├── docs/
│   ├── architecture/
│   ├── hardware/
│   ├── database/
│   └── security/
│
├── shared/
│   ├── rfid_reader.py
│   ├── init_db.py
│   └── ...
│
├── crud/
│   ├── app_crud.py
│   ├── templates/
│   └── static/
│
├── dashboard/
│   ├── app_dashboard.py
│   └── templates/
│
└── services/
    ├── rfid-reader.service
    ├── rfid-crud.service
    ├── rfid-dashboard.service
    ├── network-watchdog.service
    └── kiosk.service

🔒 Archivos que NO deben subirse

Nunca incluir en Git:

.env
rfid.db
*.db
*.db-wal
*.db-shm
backups/
*.log
venv/
__pycache__/

Especialmente, el archivo .env puede contener credenciales y configuración sensible.

🧰 Tecnologías utilizadas

Tecnología

Uso

Python

Lógica principal del sistema

Raspberry Pi 4

Plataforma de ejecución

RC522 / MFRC522

Lectura RFID

SPI / GPIO

Comunicación Raspberry Pi ↔ RC522

Flask

Aplicaciones web y API

Gunicorn

Servidor de aplicaciones

SQLite

Persistencia de datos

systemd

Gestión y recuperación de servicios

CSV

Exportación de información

HTML/CSS/JavaScript

Interfaces web

Wi-Fi

Conectividad local

📚 Referencias

La documentación del proyecto se elaboró a partir de la revisión del código fuente y se recomienda mantenerla sincronizada con futuras modificaciones del sistema.

Fuentes oficiales sugeridas por la documentación:

SQLite — Write-Ahead Logging:
https://www.sqlite.org/wal.html

Flask — documentación oficial:
https://flask.palletsprojects.com/

Gunicorn — documentación oficial:
https://gunicorn.org/

systemd — documentación:
https://www.freedesktop.org/software/systemd/man/systemd.service.html

MFRC522 — documentación técnica del fabricante (NXP):
https://www.nxp.com/products/rfid-nfc/mifare-hf/mifare-classic

Si el código del proyecto cambia, esta documentación también debe actualizarse para evitar que el README describa un comportamiento diferente al sistema real.

👨‍💻 Créditos

Proyecto desarrollado como parte del Servicio Social en el:

Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH)
Ingeniería en Tecnologías de la Información y Comunicación

Estudiante: Adrián Moreno Méndez
Matrícula: 22011747
Asesor: José Martín Oropeza Méndez

<div align="center">

Sistema de Control de Asistencia por RFID

Documentación orientada a facilitar la comprensión, operación, mantenimiento y continuidad del proyecto.

</div>
