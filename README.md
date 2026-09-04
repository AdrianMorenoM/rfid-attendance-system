<div align="center">

# Sistema de Control de Asistencia por RFID
### Guía del proyecto

**Instituto Tecnológico Superior del Occidente del Estado de Hidalgo**

**Ingeniería en Tecnologías de la Información y Comunicación**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?logo=raspberrypi&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Gunicorn-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL%20mode-003B57?logo=sqlite&logoColor=white)
![Estado](https://img.shields.io/badge/Estado-Producci%C3%B3n-success)

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
> | **Fecha del reporte original** | 15 de mayo de 2026 (actualizado a septiembre de 2026) |

---

## Acerca de este documento

Este README explica, de manera clara y sin tecnicismos innecesarios, cómo funciona el Sistema de Control de Asistencia por RFID desarrollado durante el Servicio Social en el ITSOEH. Su propósito es [...]

El contenido conserva todos los datos técnicos reales del proyecto (nombres de archivos, tablas de la base de datos, tiempos de respuesta, hallazgos de seguridad, etc.), pero los explica con anal[...]

## Tabla de contenido

1. [Introducción y objetivos](#1-introducción-y-objetivos)
2. [Cómo está organizado el sistema, en conjunto](#2-cómo-está-organizado-el-sistema-en-conjunto)
3. [El hardware: las piezas físicas](#3-el-hardware-las-piezas-físicas-del-sistema)
4. [Qué hace el sistema cuando se acerca una tarjeta](#4-qué-hace-el-sistema-cada-vez-que-se-acerca-una-tarjeta)
5. [Cómo está organizado el software](#5-cómo-está-organizado-el-software)
6. [La base de datos](#6-la-base-de-datos-qué-información-se-guarda-y-cómo)
7. [El panel administrativo](#7-el-panel-administrativo-qué-se-puede-hacer-desde-ahí)
8. [El recorrido de un dato: de la tarjeta a la pantalla](#8-el-recorrido-completo-de-un-dato-de-la-tarjeta-a-la-pantalla)
9. [El panel de visualización en tiempo real](#9-el-panel-de-visualización-en-tiempo-real)
10. [Exportación de reportes y actualización del sistema](#10-exportación-de-reportes-y-actualización-del-sistema)
11. [Registros y bitácoras](#11-registros-y-bitácoras-del-sistema)
12. [Seguridad del sistema](#12-seguridad-del-sistema)
13. [¿Qué pasa si algo falla?](#13-qué-pasa-si-algo-falla)
14. [Conclusiones y recomendaciones](#14-conclusiones-y-recomendaciones)
15. [Glosario de términos](#15-glosario-de-términos)
16. [Referencias](#16-referencias)

---

## 1. Introducción y objetivos

### 1.1 ¿Por qué se hizo este proyecto?

Tomar la asistencia a mano —pasando lista o firmando en una hoja— es lento y da pie a errores: alguien puede firmar por otra persona, se pueden perder las hojas, o simplemente toma tiempo de c[...]

### 1.2 Objetivo general

Diseñar, construir y documentar un sistema de asistencia por RFID (identificación por radiofrecuencia, es decir, tarjetas que se leen sin contacto físico) que sea funcional, razonablemente segu[...]

### 1.3 Objetivos específicos

- Leer tarjetas RFID mediante un lector físico conectado a una computadora pequeña (una Raspberry Pi 4).
- Guardar de forma ordenada la información de los estudiantes, sus tarjetas y cada registro de asistencia.
- Construir un panel de administración desde el cual dar de alta y baja estudiantes y tarjetas, y exportar la información.
- Construir una pantalla de visualización en tiempo real con las cifras del día.
- Hacer que el sistema se recupere solo ante fallas comunes, como una desconexión de red, y que quede constancia de quién hizo qué dentro del panel de administración.
- Revisar la seguridad del sistema e identificar qué se podría mejorar.
- Dejar todo documentado, para que el conocimiento no se pierda cuando termine el Servicio Social.

### 1.4 ¿Qué tan grande es el sistema?

El sistema funciona de manera local, dentro de la propia red del plantel: no depende de internet ni de ningún servicio externo para operar. Está pensado para un solo punto de lectura (un lector [...]

---

## 2. Cómo está organizado el sistema, en conjunto

El sistema se compone de varias piezas que trabajan juntas, cada una con una responsabilidad clara. Pensarlo como una pequeña fábrica ayuda a entenderlo: una tarjeta llega a la "entrada" (el lec[...]

```mermaid
flowchart TD
    A["Tarjeta RFID<br/>(la trae el estudiante)"] --> B["Lector RC522 + Raspberry Pi<br/>servicio: rfid-reader<br/>(corre como administrador)"]
    B -->|"guarda cada lectura"| C[("rfid.db<br/>Base de datos SQLite<br/>ÚNICO punto de falla")]
    C -->|"lee y escribe"| D["Panel administrativo<br/>servicio: rfid-crud<br/>accesible en toda la red local"]
    C -->|"solo lectura"| E["Panel de visualización<br/>servicio: rfid-dashboard<br/>solo accesible en la propia Pi"]
    E --> F["Pantalla física (kiosco)<br/>previsto a futuro"]
    G["Vigilante de red<br/>reconecta el Wi-Fi solo"] -.->|"vigila la conexión"| B
    D -->|"respalda periódicamente"| H[("Respaldos<br/>carpeta backups/")]

    classDef db fill:#16A085,stroke:#0e6655,color:#fff
    classDef svc fill:#2980B9,stroke:#1b4f72,color:#fff
    classDef ext fill:#7F8C8D,stroke:#4d5656,color:#fff
    class C db
    class B,D,E svc
    class A,F,G,H ext
```
*Diagrama 1. Visión general del sistema — cómo se conectan sus piezas.*

> **Punto importante:** como toda la información vive en un único archivo (la base de datos), ese archivo es el eslabón más delicado de todo el sistema. Si se dañara y no existiera un respal[...]

El panel administrativo (que escucha en el puerto de red 5001) sí es accesible desde otros equipos de la red local, mientras que el panel de visualización (puerto 5000) solo puede verse desde l[...]

---

## 3. El hardware: las piezas físicas del sistema

El sistema utiliza componentes electrónicos sencillos y económicos, elegidos porque son suficientes para esta tarea y fáciles de conseguir y reemplazar.

### 3.1 Lista de materiales

| Componente | ¿Para qué sirve? | Cantidad |
|---|---|---|
| Raspberry Pi 4 Model B | Es la computadora que corre todo el sistema (el lector, el panel administrativo y el panel de visualización). | 1 |
| Lector RFID RC522 | Detecta las tarjetas cuando se acercan y lee su número de identificación. | 1 |
| Tarjetas o llaveros MIFARE | Es lo que cada estudiante presenta ante el lector. | Una por usuario |
| Tarjeta microSD (16 GB o más, clase 10) | Guarda el sistema operativo, la base de datos y los archivos de registro. | 1 |
| Fuente de alimentación oficial de 5 V / 3 A (USB-C) | Alimenta tanto a la Raspberry Pi como al lector. | 1 |
| Cables tipo Dupont (hembra-hembra) | Conectan el lector a la Raspberry Pi. | 7 |
| Gabinete ventilado con acceso al conector de pines | Protege el equipo y permite el cableado hacia el lector. | 1 |

*Tabla 1. Materiales utilizados para construir el sistema.*

### 3.2 Cómo se conecta el lector a la Raspberry Pi

El lector RC522 se conecta mediante un estándar de comunicación llamado SPI (un protocolo de datos rápido usado entre módulos electrónicos cercanos), usando siete cables. La tabla siguiente [...]

| Pin del lector RC522 | Función | Se conecta al pin físico de la Raspberry Pi |
|---|---|---|
| 3.3V | Alimentación (energía) | Pin 1 |
| RST | Reinicio del módulo | Pin 22 |
| GND | Tierra (referencia eléctrica común) | Pin 6 |
| IRQ | No se usa en este proyecto | Sin conectar |
| MISO | Envío de datos del lector hacia la Pi | Pin 21 |
| MOSI | Envío de datos de la Pi hacia el lector | Pin 19 |
| SCK | Señal de reloj (sincroniza la comunicación) | Pin 23 |
| SDA / SS | Selección del dispositivo | Pin 24 |

*Tabla 2. Conexión física entre el lector RC522 y la Raspberry Pi 4.*

> **Advertencia importante:** el lector trabaja con 3.3 voltios. Conectarlo por error a la salida de 5 voltios de la Raspberry Pi puede dañar de forma permanente tanto el lector como el p[...]

### 3.3 Requisitos de energía

La Raspberry Pi necesita una fuente oficial de 5 voltios y 3 amperes; usar un cargador de celular genérico puede provocar caídas de voltaje que, en el peor de los casos, corrompan la base de da[...]

### 3.4 Cómo se monta físicamente

El montaje sigue un orden sencillo:

1. Se prepara la tarjeta microSD con el sistema operativo ya instalado.
2. Se fija la Raspberry Pi dentro del gabinete, dejando accesible el conector de pines.
3. Se cablea el lector siguiendo la Tabla 2, cuidando que cada cable quede bien insertado, ya que una conexión floja es la causa más común de lecturas fallidas.
4. El lector se coloca lejos de superficies metálicas (tornillos, chasis, la propia fuente de alimentación), porque el metal cercano reduce mucho su alcance de lectura.
5. Se orienta el lector hacia el punto donde la persona acercará su tarjeta, dejando un pequeño espacio libre frente a él.
6. Se aseguran los cables con cinta o una brida para que no se aflojen por el uso diario.
7. Se conecta la alimentación solo hasta el final, después de revisar que todo el cableado esté correcto.
8. Antes de cerrar el gabinete definitivamente, se comprueba que el sistema esté funcionando con una lectura de prueba.

---

## 4. Qué hace el sistema cada vez que se acerca una tarjeta

El programa que controla el lector revisa constantemente si hay una tarjeta cerca (cada 150 milisegundos, es decir, unas seis o siete veces por segundo). Cuando detecta una, sigue una serie de pr[...]

```mermaid
flowchart TD
    A["Tarjeta detectada<br/>(se lee su número, UID)"] --> B{"¿Modo alta de<br/>tarjeta nueva activo?"}
    B -->|Sí| C["Se captura el número<br/>para darla de alta<br/>(no cuenta como asistencia)"]
    B -->|No| D{"¿El número ya está<br/>registrado en el sistema?"}
    D -->|No| E["Rebote<br/>'tarjeta no reconocida'"]
    D -->|Sí| F{"¿Tarjeta y estudiante<br/>están activos?"}
    F -->|No| G["Rebote<br/>'tarjeta o estudiante inactivo'"]
    F -->|Sí| H{"¿Ya se registró su<br/>entrada hoy?"}
    H -->|No, es la primera vez hoy| I["Aceptado<br/>cuenta como asistencia"]
    H -->|Sí, ya había pasado hoy| J["Ya escaneado<br/>no duplica la asistencia"]

    classDef ok fill:#27AE60,stroke:#196f3d,color:#fff
    classDef bad fill:#C0392B,stroke:#78281f,color:#fff
    classDef warn fill:#E67E22,stroke:#9c4a12,color:#fff
    classDef neutral fill:#7F8C8D,stroke:#4d5656,color:#fff
    class I ok
    class E,G bad
    class J warn
    class C neutral
```
*Diagrama 2. Lógica de decisión del lector ante cada tarjeta.*

Para evitar que una sola pasada de tarjeta genere varios registros mientras la persona la retira del lector, el sistema ignora lecturas repetidas de la misma tarjeta durante dos segundos (a esto [...]

### 4.1 Por qué el sistema solo lee el número de la tarjeta

Las tarjetas que usa el sistema pueden guardar información en su interior protegida con una contraseña criptográfica, pero este proyecto no lee ni escribe esa información: únicamente lee el [...]

### 4.2 Qué pasa si no hay lector conectado

Si el programa se ejecuta en una computadora que no tiene el lector conectado (por ejemplo, durante pruebas o desarrollo), el sistema lo detecta automáticamente y simplemente se queda a la esper[...]

---

## 5. Cómo está organizado el software

El sistema está compuesto por tres programas principales, cada uno enfocado en una sola tarea, y dos programas de apoyo que corren en segundo plano. Separarlos así tiene una ventaja práctica: [...]

| Programa | Qué hace | Quién puede usarlo |
|---|---|---|
| Lector de tarjetas | Vigila el lector físico, decide si un escaneo cuenta como asistencia y lo guarda en la base de datos. | Nadie directamente; corre solo, en segundo plano. |
| Panel administrativo | Página web para dar de alta y baja estudiantes y tarjetas, generar reportes, hacer respaldos y administrar el equipo. | Personal autorizado, con usuario y contraseña. |
| Panel de visualización (dashboard) | Pantalla de solo lectura con las cifras del día en tiempo real. | Cualquiera con acceso a la pantalla física o a la red local. |
| Vigilante de red | Revisa la conexión Wi-Fi y la restablece sola si se cae. | Nadie directamente; corre solo, en segundo plano. |
| Modo kiosco (previsto a futuro) | Abriría el panel de visualización a pantalla completa en un monitor dedicado. | No implementado aún; el acceso actual es vía navegador en la red local. |

*Tabla 3. Los cinco programas que componen el sistema y su función.*

### 5.1 Cómo se mantienen siempre encendidos

Cada uno de estos programas está registrado ante el propio sistema operativo (mediante un mecanismo llamado *systemd*) para que arranque automáticamente cuando se enciende la Raspberry Pi y, si[...]

El panel administrativo y el panel de visualización usan un servidor llamado Gunicorn, configurado con dos procesos y dos "hilos" de atención cada uno; esto le permite responder varias peticion[...]

---

## 6. La base de datos: qué información se guarda y cómo

Toda la información del sistema vive en un solo archivo, usando un motor de base de datos llamado SQLite, configurado en un modo (llamado WAL) que permite que varios programas lean la informaci�[...]

### 6.1 Qué información guarda cada tabla

```mermaid
erDiagram
    ESTUDIANTES ||--o{ TARJETAS : "puede tener varias, a lo largo del tiempo"
    ESTUDIANTES ||--o{ REGISTROS_ASISTENCIA : "genera"
    ESTUDIANTES {
        string nombre
        string matricula "único"
        string carrera
        int semestre
        string estado "activo / inactivo"
    }
    TARJETAS {
        string uid "número de la tarjeta, único"
        bool activa
    }
    REGISTROS_ASISTENCIA {
        string uid
        datetime timestamp
        string tipo_evento "aceptado / rebote / ya_escaneado"
    }
    AUDIT_LOG {
        datetime timestamp
        string ip
        string accion
        string resultado "éxito / error"
    }
```
*Diagrama 3. Relación entre la información que guarda el sistema. La bitácora de auditoría (`AUDIT_LOG`) es independiente: no está ligada a estudiantes ni tarjetas.*

| Tabla | Qué guarda | Dato más importante |
|---|---|---|
| Estudiantes | Nombre, matrícula, carrera, semestre, grupo, correo, foto y si está activo o inactivo. | La matrícula debe ser única para cada estudiante. |
| Tarjetas | El número de cada tarjeta física y a qué estudiante pertenece (si ya fue asignada). | Un mismo estudiante puede tener varias tarjetas a lo largo del tiempo (por ejemplo, si repone[...]
| Registros de asistencia | Cada evento de lectura: quién, cuándo y si fue aceptado, rechazado o ya se había registrado ese día. | Es la tabla que más crece; nunca se borra automáticamente.[...]
| Bitácora de auditoría | Qué acciones administrativas sensibles se realizaron (reinicios, restauraciones, bajas masivas), desde qué dirección de red y si tuvieron éxito. | Sirve para recon[...]

*Tabla 4. Las cuatro tablas que componen la base de datos del sistema.*

### 6.2 Por qué borrar un estudiante no borra su historial

Cuando se elimina un estudiante de la base de datos, sus tarjetas y su historial de asistencia no desaparecen con él: quedan como registros "huérfanos", identificables por el número de tarjeta[...]

### 6.3 Mantenimiento: respaldos, restauración y crecimiento

El panel administrativo permite generar un respaldo de la base de datos con un solo botón, en cualquier momento; ese respaldo usa el propio mecanismo de SQLite para garantizar que la copia quede[...]

Con un uso típico —entre 300 y 500 estudiantes activos y unos 2 a 4 escaneos por estudiante al día, incluyendo reintentos— la base de datos crece aproximadamente entre 150 y 300 kilobytes p[...]

---

## 7. El panel administrativo: qué se puede hacer desde ahí

El panel administrativo es una página web que se comunica con el sistema mediante más de cincuenta funciones internas (en informática, a este conjunto de funciones se le llama una API). No es [...]

### 7.1 Cómo se protege el acceso

Cada vez que alguien intenta usar el panel administrativo, el sistema exige un usuario y una contraseña (un esquema llamado "autenticación básica"); no existe una sesión que se quede abierta [...]

Además de la contraseña, el sistema tiene varias capas adicionales de protección: un límite de intentos fallidos por minuto (para frenar intentos de adivinar la contraseña por fuerza bruta),[...]

### 7.2 Qué se puede hacer desde el panel

| Área | Qué permite hacer |
|---|---|
| Estadísticas y análisis | Ver cifras del día y de los últimos siete días, así como comparativas por semestre y por hora. |
| Estudiantes | Dar de alta, editar, dar de baja o eliminar estudiantes, de forma individual o en bloque (por ejemplo, promover a todo un grupo de semestre, o dar de baja a una generación comple[...]
| Tarjetas | Asignar, activar, desactivar o eliminar tarjetas, y asociarlas a un estudiante. |
| Alta rápida de tarjetas | Activar un modo de "escucha" para capturar el número de una tarjeta nueva con solo acercarla al lector, en lugar de teclearlo a mano; también admite capturar varias[...]
| Reportes y exportación | Descargar en formato CSV (compatible con Excel) el padrón completo de estudiantes o la asistencia de un día específico. |
| Hardware y red | Consultar temperatura, uso de memoria y espacio en disco del equipo, ver el estado de la conexión Wi-Fi, y reiniciar o apagar la Raspberry Pi de forma remota. |
| Base de datos | Ver su estado, crear y descargar respaldos, restaurar un respaldo anterior, y depurar registros antiguos según fecha, carrera, semestre o grupo (con una vista previa antes de b[...]
| Bitácora de auditoría | Consultar el historial de acciones administrativas sensibles realizadas en el sistema. |

*Tabla 5. Principales funciones disponibles desde el panel administrativo.*

Una particularidad digna de mención: cuando algo falla dentro de una operación de depuración de registros ("purga"), el sistema garantiza que nunca se borre información sin haber logrado ante[...]

### 7.3 Formato de las respuestas

Casi todas las funciones del panel devuelven la información en un formato estándar y homogéneo, de manera que un error inesperado en cualquiera de ellas se reporta siempre de forma consistente[...]

---

## 8. El recorrido completo de un dato: de la tarjeta a la pantalla

Para entender qué tan rápido responde el sistema, conviene seguir paso a paso lo que ocurre desde que alguien acerca su tarjeta hasta que ese evento aparece reflejado en la pantalla de visualiz[...]

```mermaid
sequenceDiagram
    participant T as Tarjeta
    participant L as Lector (rfid-reader)
    participant DB as Base de datos
    participant P as Panel de visualización
    participant N as Navegador (pantalla)

    T->>L: Se acerca al lector
    L->>DB: ¿Existe este número de tarjeta?
    DB-->>L: Sí, pertenece a Juan Pérez
    L->>DB: ¿Ya se registró hoy?
    DB-->>L: No, es la primera vez
    L->>DB: Guarda el registro ("aceptado")
    Note over L,DB: ~160 ms en total, dominado por el<br/>intervalo de revisión del lector
    N->>P: ¿Hay un evento nuevo? (cada 800 ms)
    P->>DB: Consulta el último registro
    DB-->>P: Entrega los datos
    P-->>N: Envía nombre, foto y resultado
    N->>N: Muestra el aviso en pantalla
```
*Diagrama 4. Secuencia completa desde que se acerca la tarjeta hasta que aparece en pantalla.*

| Etapa | Tiempo típico | Peor caso |
|---|---|---|
| Detección de la tarjeta por el lector | 0–75 ms | 150 ms |
| Consulta a la base de datos y guardado del registro | 3–11 ms | 30–65 ms |
| La pantalla detecta el evento nuevo | 0–800 ms | 800 ms |
| **Total, desde que se acerca la tarjeta hasta que aparece en pantalla** | **~250–350 ms** | **hasta ~1.1 s** |

*Tabla 6. Tiempos aproximados de respuesta del sistema, de la tarjeta a la pantalla.*

Vale la pena señalar con honestidad los puntos donde el sistema podría ser más eficiente. El más notable es que, para saber si el programa lector sigue activo, el panel de visualización le pregun[...]

---

## 9. El panel de visualización en tiempo real

Esta pantalla, pensada para mostrarse en un monitor dedicado o consultarse desde cualquier equipo de la red local, resume lo que ha ocurrido durante el día: cuántos accesos fueron aceptados, cuánto[...]

La actualización de esta pantalla ocurre en dos velocidades distintas, cada una ajustada a lo que realmente necesita. Cada 800 milisegundos, el sistema revisa si hubo un evento nuevo (una consul[...]

El diseño visual del panel está centralizado: todos los colores del panel están definidos en un solo lugar del código, así que cambiar, por ejemplo, el tono de azul institucional actualiza a[...]

---

## 10. Exportación de reportes y actualización del sistema

El sistema no cuenta con un proceso automático que transforme datos entre distintos sistemas (lo que en informática se conoce como un proceso ETL); toda la información se guarda y se consulta [...]

### 10.1 Reportes en CSV

El panel administrativo permite descargar tanto el padrón completo de estudiantes como la asistencia de un día concreto, en un formato de texto separado por comas (CSV) que Excel puede abrir di[...]

### 10.2 Cómo evoluciona la estructura de la base de datos

Cuando ha sido necesario agregar información nueva a la base de datos —por ejemplo, cuando se añadió la bitácora de auditoría—, esto se hizo mediante actualizaciones incrementales que se[...]

---

## 11. Registros y bitácoras del sistema

Además de la información de asistencia, el sistema guarda distintos tipos de registros técnicos que sirven para dar seguimiento y diagnosticar problemas.

| Fuente | Qué contiene | Cuánto tiempo se conserva |
|---|---|---|
| Registro del lector | Cada lectura de tarjeta, aceptada o no, con fecha y hora. | Aproximadamente un mes (últimas cuatro semanas). |
| Registro del vigilante de red | Intentos de reconexión Wi-Fi. | Aproximadamente un mes. |
| Bitácora de auditoría | Acciones administrativas sensibles: quién, qué, desde dónde y si tuvo éxito. | Indefinido; no se depura automáticamente todavía. |
| Registros del propio sistema operativo | Actividad general de cada uno de los cinco programas del sistema. | Gestionado por el sistema operativo, generalmente limitado por espacio en disco. |

*Tabla 7. Fuentes de registro del sistema y su política de conservación.*

La bitácora de auditoría merece una mención aparte, porque es la que documenta acciones con posible impacto real: reinicios o apagados del equipo, creación o restauración de respaldos, elimi[...]

---

## 12. Seguridad del sistema

Se realizó una revisión de seguridad enfocada en dos riesgos principales: que alguien pudiera ejecutar comandos no autorizados en el equipo (aprovechando que el panel puede reiniciar servicios [...]

### 12.1 Qué se encontró

| Hallazgo | Situación |
|---|---|
| Posible ejecución de comandos no autorizados | Descartado: el sistema solo acepta nombres de servicio de una lista predefinida y cerrada, y sanea cualquier valor antes de usarlo. |
| Endpoints sin autenticación | Descartado: la exigencia de usuario y contraseña cubre absolutamente todas las funciones del panel, sin excepción. |
| Las credenciales viajan sin cifrar por la red | Pendiente. Es el hallazgo de mayor prioridad: se recomienda cifrar la conexión (HTTPS) antes de operar el sistema sin supervisión directa.[...]
| Contraseña de administrador poco robusta | Pendiente. Se recomienda sustituirla por una generada de forma aleatoria y no reutilizada en ningún otro sistema. |
| Restricción por red institucional, construida pero apagada | Pendiente activar. El mecanismo ya existe en el código; solo falta configurarlo y encenderlo. |
| Falta una confirmación explícita al reiniciar la conexión de red | Pendiente, de baja prioridad. Otras operaciones similares sí piden confirmación; esta debería seguir el mismo crite[...]
| Contraseña débil en el mecanismo de respaldo por SSH | Solo aplica si llegara a usarse ese modo alterno de conexión remota; no está en uso en la operación normal. |

*Tabla 8. Hallazgos de la revisión de seguridad y su estado actual.*

### 12.2 Buenas prácticas que ya están implementadas

- Comparación de contraseñas resistente a ataques que intentan medir el tiempo de respuesta.
- Límite de intentos fallidos de acceso, para frenar intentos de adivinar la contraseña.
- Registro automático en la bitácora de auditoría cuando una dirección de red queda bloqueada por exceso de intentos.
- Encabezados de seguridad en las respuestas del panel, que dificultan ataques comunes en páginas web.
- Todas las consultas a la base de datos usan parámetros seguros, nunca texto del usuario pegado directamente en la consulta —lo que previene el ataque conocido como inyección SQL.
- Validación estricta del nombre de archivo al restaurar un respaldo, que impide intentar acceder a archivos fuera de la carpeta permitida.
- Mecanismo de restricción por red institucional ya construido, listo para activarse.

### 12.3 Recomendaciones, en orden de prioridad

| Prioridad | Recomendación | Qué logra |
|---|---|---|
| Alta | Colocar un intermediario con cifrado (HTTPS) delante del panel administrativo. | Evita que las credenciales viajen legibles por la red. |
| Media | Cambiar la contraseña de administrador por una generada aleatoriamente. | Reduce el riesgo de que alguien la adivine o la reutilice de otro sistema. |
| Media | Activar la restricción de acceso por red institucional. | Limita quién puede siquiera intentar entrar al panel, según su ubicación en la red. |
| Baja | Exigir una confirmación explícita antes de reiniciar la conexión de red. | Evita reinicios accidentales de la conectividad. |

*Tabla 9. Recomendaciones de seguridad, priorizadas.*

---

## 13. ¿Qué pasa si algo falla?

Ninguna de las piezas del sistema es completamente independiente de las demás; sin embargo, están organizadas de tal forma que una falla parcial no necesariamente detiene todo el sistema.

```mermaid
flowchart TD
    DB[("rfid.db<br/>ÚNICO PUNTO DE FALLA")] --> R["rfid-reader"]
    DB --> C["rfid-crud"]
    DB --> D["rfid-dashboard"]
    D --> K["kiosk (futuro)"]
    W["network-watchdog"] -.-> R

    classDef critico fill:#C0392B,stroke:#78281f,color:#fff
    classDef noCritico fill:#E8A020,stroke:#9c6b0a,color:#fff
    classDef cosmetico fill:#95A5A6,stroke:#616a6b,color:#fff

    class DB,R critico
    class C,D noCritico
    class K,W cosmetico
```
*Diagrama 5. Qué tan grave es la falla de cada componente — crítico, no crítico para la operación diaria, afecta solo lo cosmético o el acceso remoto.*

| Si esto falla… | …esto es lo que pasa | Qué tan grave es |
|---|---|---|
| La base de datos se daña | Todo el sistema queda ciego: nada puede leerse ni escribirse, en ninguna de sus partes. | Crítico — es el único punto que, si falla, afecta a todo a la vez.[...]
| El programa del lector se detiene | Deja de registrarse asistencia nueva, aunque el resto del sistema sigue funcionando con la información ya existente. Se reinicia solo, generalmente en segun[...]
| El panel administrativo se detiene | Se pierde la posibilidad de administrar el sistema, pero el lector sigue registrando asistencia con normalidad. | No crítico para la operación diaria[...]
| El panel de visualización se detiene | Se pierde la pantalla en tiempo real, pero los datos se siguen guardando sin problema y aparecerán en cuanto el panel se recupere. | No crítico. |
| El vigilante de red se detiene | El Wi-Fi deja de repararse solo si se cae, pero mientras la conexión actual siga viva, no hay impacto inmediato. | Afecta solo el acceso remoto. |

*Tabla 10. Qué ocurre si cada componente del sistema falla, y qué tan grave es.*

Esto deja claro por qué la base de datos es, con diferencia, el punto más delicado del sistema: hoy no existe una copia "en caliente" que pueda tomar su lugar automáticamente si falla, solo re[...]

1. **Respaldos automáticos frecuentes** (por ejemplo, cada dos horas en horario escolar) — no requiere ningún cambio al sistema y reduce drásticamente cuánta información se podría perder [...]
2. **Copia periódica hacia otro equipo de la red** — una segunda red de seguridad fuera de la propia tarjeta de memoria de la Raspberry Pi.
3. **Migrar a un motor de base de datos con replicación automática** — ofrecería continuidad real ante una falla, pero implicaría reescribir buena parte del sistema y añadir la dependencia[...]

Ante una falla real, el procedimiento es restaurar el respaldo más reciente confiable, verificando primero que ese respaldo esté íntegro antes de ponerlo en producción. En el escenario extrem[...]

---

## 14. Conclusiones y recomendaciones

El sistema cumple con el objetivo que se planteó desde el inicio: automatizar el registro de asistencia mediante tarjetas RFID de forma confiable, con una arquitectura sencilla, autosuficiente ([...]

| Prioridad | Recomendación para trabajo futuro |
|---|---|
| Alta | Cifrar el tráfico del panel administrativo (HTTPS) antes de operar sin supervisión constante. |
| Alta | Cambiar la contraseña de administrador por una robusta y exclusiva de este sistema. |
| Media | Activar la restricción de acceso por red institucional, ya construida en el código. |
| Media | Dar al vigilante de red un nombre más consistente con el resto de los servicios, para facilitar futuras auditorías. |
| Baja | Ampliar el panel de visualización con análisis histórico (por semana, mes o semestre). |
| Baja | Evaluar, si el caso de uso lo llegara a requerir, un tipo de tarjeta con autenticación criptográfica más fuerte. |
| Baja | Automatizar los respaldos de la base de datos con una tarea programada, en lugar de solo bajo demanda. |

*Tabla 11. Recomendaciones para la continuidad del proyecto.*

---

## 15. Glosario de términos

| Término | Qué significa |
|---|---|
| RFID | Identificación por radiofrecuencia: tecnología que permite leer una tarjeta sin necesidad de contacto físico. |
| UID | El número de identificación único que trae cada tarjeta de fábrica. |
| SPI | El tipo de conexión por cable que usan el lector y la Raspberry Pi para comunicarse entre sí. |
| Base de datos | El archivo donde se guarda de forma organizada toda la información del sistema. |
| WAL | Un modo de funcionamiento de la base de datos que permite que varios programas la lean al mismo tiempo sin bloquearse. |
| API | El conjunto de funciones internas mediante las cuales el panel administrativo se comunica con el sistema. |
| Panel administrativo | La página web protegida donde el personal autorizado administra el sistema. |
| Dashboard (panel de visualización) | La pantalla de solo lectura con las cifras del día en tiempo real. |
| Debounce (anti-rebote) | Técnica para ignorar lecturas repetidas de una misma tarjeta en un intervalo muy corto de tiempo. |
| Autenticación básica | El esquema de usuario y contraseña que exige el panel administrativo en cada solicitud. |
| Punto único de falla (SPOF) | Un componente cuya falla detiene todo el sistema; en este proyecto, es la base de datos. |
| Bitácora de auditoría | El registro de quién hizo qué acción administrativa sensible, cuándo y con qué resultado. |

*Tabla 12. Glosario de términos técnicos usados en este documento.*

---

## 16. Referencias

Este documento se elaboró revisando directamente el código fuente del sistema; si el código cambia en el futuro (nuevas funciones, cambios en el comportamiento), este documento debería actual[...]

- SQLite — documentación oficial del modo WAL: [sqlite.org/wal.html](https://www.sqlite.org/wal.html)
- Flask — documentación oficial del framework web utilizado: [flask.palletsprojects.com](https://flask.palletsprojects.com/)
- Gunicorn — documentación oficial del servidor usado para ejecutar el panel administrativo y el panel de visualización: [gunicorn.org](https://gunicorn.org/)
- Hoja de datos técnica del módulo lector MFRC522, publicada por su fabricante, NXP.
- systemd — documentación oficial de la gestión de servicios en Linux: [freedesktop.org/software/systemd/man/systemd.service.html](https://www.freedesktop.org/software/systemd/man/systemd.ser[...]

### Anexo A — Esquema completo de la base de datos

La estructura completa de las tablas e índices de la base de datos —incluyendo cada columna con su tipo de dato— se encuentra en el archivo de inicialización del proyecto (`init_db.py`), di[...]

### Anexo B — Créditos

Documento elaborado como parte del Servicio Social en el Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH), por **Adrián Moreno Méndez**, estudiante de Ingeniería en[...]

<div align="center">

---

**ITSOEH — Ingeniería en Tecnologías de la Información y Comunicación**
*Servicio Social · Sistema de Control de Asistencia RFID*

</div>
