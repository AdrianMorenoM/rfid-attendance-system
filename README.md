<div align="center">

# Sistema de Control de Asistencia por RFID
## Documentación del proyecto, explicada en lenguaje sencillo

**Instituto Tecnológico Superior del Occidente del Estado de Hidalgo (ITSOEH)**
**Ingeniería en Tecnologías de la Información y Comunicación**

</div>

---

> **Ficha del proyecto**
>
> | Campo | Valor |
> |---|---|
> | Estudiante | Adrián Moreno Méndez |
> | Matrícula | 22011747 |
> | Asesor | José Martín Oropeza Méndez |
> | Fecha del reporte | 18 de junio de 2026 (actualizado en agosto de 2026) |
>
> *Tabla 0. Datos generales del proyecto y de quien lo desarrolló.*

---

## Sobre este documento

Este documento explica, en español sencillo y sin dar por hecho conocimientos técnicos previos, cómo funciona el **Sistema de Control de Asistencia por RFID** que desarrollé durante mi Servicio Social en el ITSOEH. La intención es que cualquier persona —un profesor, un compañero, alguien del área administrativa o quien continúe el proyecto en el futuro— pueda entender qué hace el sistema, cómo está construido y por qué se tomaron ciertas decisiones, sin necesitar experiencia en programación. Todo lo que se describe aquí corresponde exactamente a lo que el sistema hace hoy: no se agregó nada especulativo ni se omitió información relevante.

## Tabla de contenido

1. [Introducción y objetivos](#1-introducción-y-objetivos)
2. [Cómo funciona el sistema, en general](#2-cómo-funciona-el-sistema-en-general)
3. [El hardware: la tarjeta y el lector](#3-el-hardware-la-tarjeta-y-el-lector)
4. [Qué hace el lector con cada tarjeta](#4-qué-hace-el-lector-con-cada-tarjeta)
5. [Cómo está organizado el software](#5-cómo-está-organizado-el-software)
6. [La base de datos](#6-la-base-de-datos)
7. [La API: cómo se administra el sistema](#7-la-api-cómo-se-administra-el-sistema)
8. [El recorrido completo de un dato: de la tarjeta a la pantalla](#8-el-recorrido-completo-de-un-dato-de-la-tarjeta-a-la-pantalla)
9. [El panel de control (dashboard)](#9-el-panel-de-control-dashboard)
10. [Exportación de datos y actualizaciones del sistema](#10-exportación-de-datos-y-actualizaciones-del-sistema)
11. [Registros y bitácoras](#11-registros-y-bitácoras)
12. [Seguridad](#12-seguridad)
13. [Qué pasa si algo falla](#13-qué-pasa-si-algo-falla)
14. [Conclusiones y recomendaciones](#14-conclusiones-y-recomendaciones)
15. [Glosario](#15-glosario)
16. [Referencias](#16-referencias)

---

## 1. Introducción y objetivos

Tomar asistencia a mano es lento, se presta a errores y a que alguien registre a un compañero que no está presente. Para resolver esto, como parte de mi Servicio Social, diseñé e instalé un sistema que registra la entrada de los estudiantes automáticamente cuando acercan una tarjeta a un lector, guarda esa información en una base de datos y la muestra en tiempo real en un panel de control.

El objetivo general fue construir un sistema de asistencia por RFID que funcionara de manera confiable, fuera razonablemente seguro y quedara bien documentado, de forma que sirviera tanto de evidencia del Servicio Social como de base para mejoras futuras. De manera más puntual, me propuse: hacer que un lector RFID conectado a una Raspberry Pi reconociera las tarjetas de los estudiantes; diseñar una base de datos que representara correctamente a los estudiantes, sus tarjetas y su historial de asistencia; construir un panel de administración para dar de alta y baja estudiantes y tarjetas; construir una pantalla con métricas del día en tiempo real; hacer que el sistema se recuperara solo ante fallas comunes (como una desconexión de red); y revisar la seguridad del sistema para identificar y documentar sus puntos débiles.

El sistema opera completamente dentro de la red de la institución, sin depender de internet ni de servicios externos, y está pensado para un solo punto de lectura (un lector).

---

## 2. Cómo funciona el sistema, en general

En términos simples, el sistema tiene cinco piezas que trabajan juntas: un lector conectado a una Raspberry Pi que detecta las tarjetas, un archivo de base de datos que guarda toda la información, un panel de administración donde se gestionan estudiantes y tarjetas, una pantalla con métricas en vivo, y un programa que vigila la conexión Wi-Fi y la reconecta si se cae.

Todas estas piezas comparten un mismo archivo de base de datos: el lector escribe en él cada vez que pasa una tarjeta, y tanto el panel de administración como la pantalla de métricas leen de él constantemente. Esto simplifica mucho el diseño, pero también significa que ese archivo es el corazón del sistema: si llegara a dañarse, todo lo demás deja de funcionar hasta restaurarlo. Este punto se explica con más detalle en la [sección 13](#13-qué-pasa-si-algo-falla).

| Pieza del sistema | Qué hace |
|---|---|
| Lector + Raspberry Pi | Detecta la tarjeta y decide si el acceso es válido |
| Base de datos | Guarda estudiantes, tarjetas y el historial de asistencia |
| Panel de administración | Permite dar de alta/baja estudiantes y tarjetas, exportar información y hacer respaldos |
| Pantalla de métricas | Muestra en tiempo real cuántos accesos ha habido y quién ha entrado |
| Vigilante de red | Reconecta el Wi-Fi automáticamente si se pierde la conexión |

*Tabla 1. Componentes principales del sistema y su función.*

---

## 3. El hardware: la tarjeta y el lector

El sistema usa una **Raspberry Pi 4** como cerebro, conectada a un módulo lector llamado **RC522**, que reconoce tarjetas RFID de tipo MIFARE (las mismas que se usan en muchos sistemas de control de acceso). El lector se conecta a la Raspberry Pi con siete cables, usando un tipo de conexión llamada SPI, que es simplemente la forma en que ambos dispositivos se comunican entre sí. Es importante que el lector se alimente con 3.3 voltios y nunca con 5 voltios, porque un voltaje más alto puede dañarlo de forma permanente.

Actualmente el sistema no cuenta con una pantalla física dedicada; la consulta de información se hace desde cualquier computadora en la red local a través del panel de administración y el panel de métricas. La arquitectura ya contempla, para una futura versión, una pantalla en modo "quiosco" conectada directamente al panel de métricas.

Vale la pena aclarar cómo identifica el sistema a cada tarjeta: cada tarjeta MIFARE trae de fábrica un número de serie único (llamado UID). El sistema únicamente lee ese número —no necesita ni intenta leer ni escribir información dentro de la memoria protegida de la tarjeta—, por lo que no se usa ningún tipo de llave criptográfica para autenticar la tarjeta. Esto es adecuado para un control de asistencia, donde el riesgo es bajo, pero implica que existen tarjetas regrabables capaces de imitar el número de serie de otra; la seguridad del acceso descansa, entonces, en mantener bien controlada la lista de números de serie autorizados dentro de la base de datos, no en una propiedad inviolable de la tarjeta física.

| Pin del lector | Función | Dónde se conecta en la Raspberry Pi |
|---|---|---|
| 3.3V | Alimentación | Pin 1 |
| RST | Reinicio del módulo | Pin 22 |
| GND | Tierra | Pin 6 |
| IRQ | No se usa | Sin conectar |
| MISO | Comunicación (recibe) | Pin 21 |
| MOSI | Comunicación (envía) | Pin 19 |
| SCK | Reloj de sincronización | Pin 23 |
| SDA | Selección del dispositivo | Pin 24 |

*Tabla 2. Cableado entre el lector RC522 y la Raspberry Pi 4.*

**Recomendaciones de montaje.** Al armar el sistema conviene tener presentes algunos detalles prácticos: el lector debe quedar alejado de superficies metálicas, porque el metal reduce mucho su alcance de lectura; la cara del lector con la antena debe orientarse hacia el punto donde el usuario acercará su tarjeta, dejando un pequeño espacio libre; los cables deben quedar bien sujetos para que no se desconecten con el uso diario; y conviene alimentar el sistema con la fuente oficial de la Raspberry Pi (5V, 3A), ya que una fuente más débil puede provocar caídas de voltaje que corrompan la base de datos a mitad de una escritura.

---

## 4. Qué hace el lector con cada tarjeta

Cada vez que se acerca una tarjeta, el programa que controla el lector (`rfid_reader.py`) sigue siempre la misma secuencia de decisiones, resumida en la tabla siguiente.

| Situación detectada | Qué hace el sistema |
|---|---|
| El sistema está en modo de alta de tarjetas nuevas | Captura el número de la tarjeta para que el administrador la asigne a un estudiante, pero no la registra como asistencia |
| El número de la tarjeta no existe en la base de datos | Registra el evento como "rebote" con el motivo "tarjeta no registrada" |
| La tarjeta o el estudiante están marcados como inactivos | Registra el evento como "rebote" con el motivo correspondiente |
| Es la primera vez que esa tarjeta se lee en el día | Registra el evento como "aceptado" — asistencia válida |
| Esa tarjeta ya se había registrado antes en el mismo día | Registra el evento como "ya escaneado", sin contarlo de nuevo como asistencia |

*Tabla 3. Lógica de decisión del lector ante cada tarjeta.*

El lector revisa si hay una tarjeta presente aproximadamente 6 o 7 veces por segundo, y una vez que lee una tarjeta, la ignora durante 2 segundos antes de volver a procesarla — esto evita que, al pasar la tarjeta y retirarla, quede registrada varias veces por accidente. Si el módulo deja de responder por más de 8 segundos (por ejemplo, por una falla momentánea de comunicación), el sistema lo reinicia automáticamente sin intervención humana.

Cuando un administrador está dando de alta una tarjeta nueva desde el panel de administración, el lector cambia temporalmente de comportamiento: en vez de registrar una asistencia, simplemente "escucha" la siguiente tarjeta que se acerque y comparte su número con el panel, para que se pueda asociar a un estudiante. Este mecanismo de comunicación entre el proceso del lector y el panel de administración se hace a través de un pequeño archivo compartido en la memoria de la Raspberry Pi, y no requiere tocar la base de datos directamente.

Cuando el programa se ejecuta en una computadora que no tiene el módulo lector conectado (por ejemplo, durante el desarrollo del sistema), simplemente se queda a la espera sin hacer nada, en vez de fallar — esto es útil para poder trabajar en el código sin tener el hardware físico a la mano, aunque no simula lecturas de tarjetas reales.

---

## 5. Cómo está organizado el software

El sistema se compone de cinco programas independientes, cada uno registrado como un **servicio** del sistema operativo (esto significa que Linux los mantiene corriendo en segundo plano y los reinicia automáticamente si llegan a fallar). Mantenerlos separados tiene una ventaja importante: si uno de ellos falla, los demás pueden seguir funcionando con normalidad.

| Servicio | Qué hace | Se reinicia solo si falla |
|---|---|---|
| Lector de tarjetas | Detecta tarjetas y registra la asistencia | Sí |
| Panel de administración | Permite gestionar estudiantes, tarjetas y respaldos | Sí |
| Panel de métricas | Calcula y muestra estadísticas en tiempo real | Sí |
| Pantalla en modo quiosco | Muestra el panel de métricas en una pantalla física | Sí |
| Vigilante de red | Reconecta el Wi-Fi si se pierde la señal | Sí |

*Tabla 4. Servicios que componen el sistema.*

El programa del lector es el único que corre con permisos completos del sistema (permisos de "administrador" de Linux), porque necesitarlos es requisito para poder comunicarse directamente con el hardware. Los demás programas corren con permisos normales, lo que limita el daño que podrían causar en caso de tener alguna falla de seguridad.

El panel de administración y el panel de métricas están construidos con **Flask**, un marco de trabajo muy usado para crear aplicaciones web en Python, servido a través de **Gunicorn**, que es el programa encargado de recibir y repartir las peticiones que llegan por internet o por la red local de forma eficiente. Una diferencia importante entre ambos: el panel de administración escucha en toda la red local (por lo que puede administrarse desde cualquier computadora dentro de esa red), mientras que el panel de métricas solo escucha en la propia Raspberry Pi — es decir, únicamente la pantalla física conectada directamente a ella puede verlo, lo cual reduce de forma deliberada su exposición.

Toda la información que produce el sistema —la base de datos, los programas y sus registros de actividad— vive ordenada dentro de una sola carpeta en la Raspberry Pi, dividida en tres partes: una carpeta compartida donde está la base de datos y el programa del lector; una carpeta para el panel de administración; y una carpeta para el panel de métricas. Las contraseñas y demás datos sensibles se guardan aparte, en un archivo que nunca se sube a ningún repositorio de código.

---

## 6. La base de datos

El sistema guarda toda su información en un solo archivo de base de datos, usando **SQLite**, un motor de base de datos ligero que no necesita instalación ni un servidor aparte —es, literalmente, un archivo. Este archivo se configura en un modo especial llamado **WAL** (registro de escritura anticipada), que permite que varios programas lean la base de datos al mismo tiempo sin bloquearse entre sí, mientras el lector sigue escribiendo. Esto es importante porque el lector escribe constantemente mientras el panel de métricas y el de administración leen en paralelo.

La base de datos se organiza en cuatro tablas, es decir, cuatro listas de información relacionadas entre sí:

**Estudiantes.** Guarda el nombre, la matrícula, la carrera, el semestre, el grupo, el correo y una foto opcional de cada alumno. Cada estudiante tiene un estado —activo o inactivo— que se usa para dar de baja a alguien sin borrar su historial.

**Tarjetas.** Guarda el número de serie de cada tarjeta física y a qué estudiante pertenece. Un mismo estudiante puede tener varias tarjetas a lo largo del tiempo (por ejemplo, si repone una que perdió), lo cual permite conservar su historial completo aunque cambie de tarjeta.

**Registros de asistencia.** Es la tabla más grande y la que más crece con el tiempo: guarda un renglón por cada vez que una tarjeta pasó por el lector, con la fecha, la hora y el tipo de evento (aceptado, rebote o ya escaneado).

**Bitácora de auditoría.** Guarda un historial de las acciones administrativas más delicadas realizadas desde el panel, como reinicios del sistema o purgas de información, junto con la dirección de red desde la que se hicieron.

| Tabla | Qué información guarda | Crece con el tiempo |
|---|---|---|
| Estudiantes | Datos personales y escolares de cada alumno | No, de forma significativa |
| Tarjetas | Número de serie de cada tarjeta y a quién pertenece | No, de forma significativa |
| Registros de asistencia | Cada evento de lectura de tarjeta | Sí, constantemente |
| Bitácora de auditoría | Acciones administrativas sensibles | Muy lentamente |

*Tabla 5. Tablas que componen la base de datos y su comportamiento de crecimiento.*

**Una decisión de diseño importante.** Cuando se elimina un estudiante de la base de datos, sus tarjetas y su historial de asistencia **no se borran junto con él**: en vez de eso, quedan "huérfanos" (sin estudiante asociado), pero siguen existiendo. Esto se hizo así a propósito: el historial de asistencia es evidencia de hechos que ya ocurrieron y podría necesitarse después para una auditoría o para corregir un error administrativo, así que preferí que el sistema nunca lo borre de forma automática e irreversible.

**¿Qué tan rápido crece la base de datos?** Con una población de entre 300 y 500 estudiantes activos y un promedio de 2 a 4 lecturas por estudiante al día, el sistema genera aproximadamente entre 900 y 1,800 registros nuevos por día de clases. Esto se traduce en un crecimiento aproximado de 30 a 60 megabytes por año —una cantidad muy pequeña comparada con la capacidad de cualquier tarjeta de memoria moderna. El verdadero riesgo a largo plazo no es quedarse sin espacio, sino que las consultas se vuelvan más lentas si la tabla de registros crece durante varios años sin depurarse nunca; por eso el sistema ya incluye índices (una especie de "índice de libro" que acelera las búsquedas) en las columnas que más se consultan, y se documenta más adelante una estrategia recomendada de archivado anual.

**Respaldo y recuperación.** El sistema permite crear respaldos de la base de datos en cualquier momento desde el panel de administración, y también restaurar uno anterior si algo sale mal. Antes de cualquier operación que pudiera borrar información (como una purga de registros antiguos), el sistema crea automáticamente un respaldo de seguridad; si ese respaldo no puede crearse por alguna razón, la operación se cancela por completo para evitar pérdidas accidentales de información.

---

## 7. La API: cómo se administra el sistema

Todo lo que se puede hacer desde el panel de administración —dar de alta un estudiante, asignar una tarjeta, exportar información, reiniciar un servicio, hacer un respaldo— en realidad se comunica con el sistema a través de una **API**, que es simplemente un conjunto de "puertas" a las que otros programas (incluido el propio panel web) pueden tocar para pedir o enviar información, siguiendo reglas claras y predecibles. El sistema expone más de 50 de estas puertas, agrupadas por función.

**Quién puede entrar.** Absolutamente todas las peticiones a la API, sin excepción, deben incluir un usuario y una contraseña (un esquema llamado autenticación básica). Esas credenciales se comparan usando una técnica resistente a ataques de "medición de tiempos", que evita que alguien pueda adivinar la contraseña poco a poco midiendo cuánto tarda el sistema en responder. Además, existen capas adicionales de protección: un límite de cuántas veces por minuto se puede intentar entrar con credenciales equivocadas (para frenar intentos de fuerza bruta), un mecanismo —hoy apagado— para restringir el acceso solo a direcciones de la red institucional, y un requisito adicional de confirmación explícita para las acciones más delicadas, como apagar la Raspberry Pi o borrar información en bloque.

**Qué se puede hacer.** A grandes rasgos, la API permite: consultar estadísticas generales y del día; monitorear el estado del hardware, la red y los servicios, y reiniciarlos si hace falta; administrar el flujo de alta de tarjetas nuevas (tanto de una en una como en sesiones masivas al inicio de semestre); dar de alta, editar, dar de baja o eliminar estudiantes y tarjetas, incluyendo operaciones en bloque como promover a todo un grupo de semestre; consultar y exportar el historial de asistencia y la bitácora de auditoría; y administrar los respaldos de la base de datos, incluyendo su restauración y la eliminación controlada de registros antiguos.

| Categoría | Ejemplos de lo que permite hacer |
|---|---|
| Estadísticas | Consultar totales del día y del sistema completo |
| Hardware y red | Ver temperatura, uso de memoria, estado del Wi-Fi; reiniciar servicios |
| Tarjetas | Dar de alta una tarjeta nueva, asignarla a un estudiante, activarla o desactivarla |
| Estudiantes | Alta, edición, baja y consulta, incluyendo operaciones por grupo completo |
| Base de datos | Crear y restaurar respaldos, eliminar registros antiguos de forma controlada |
| Exportación | Descargar el padrón de estudiantes o la asistencia de un día en formato CSV |

*Tabla 6. Categorías principales de funciones que ofrece la API.*

**Un detalle pensado para no exponer información de más.** Existe una función para actualizar la estructura de la base de datos (por ejemplo, cuando se agrega una columna nueva), pero está desactivada por defecto. Si alguien intenta usarla sin que esté activada, el sistema responde como si esa función ni siquiera existiera, en vez de decir "está bloqueada" — esto evita darle pistas a alguien no autorizado sobre qué funciones tiene el sistema disponibles.

Las respuestas de la API siempre llegan en un formato de datos llamado JSON, fácil de leer tanto por otros programas como, con algo de práctica, por una persona; cada respuesta indica si la operación tuvo éxito o no, además del código de estado HTTP correspondiente (por ejemplo, 401 cuando faltan credenciales, o 403 cuando algo está prohibido por política aunque las credenciales sean correctas).

---

## 8. El recorrido completo de un dato: de la tarjeta a la pantalla

Vale la pena describir, paso a paso, todo lo que ocurre entre el instante en que un estudiante acerca su tarjeta y el momento en que ese evento aparece reflejado en la pantalla de métricas.

Primero, el lector detecta la tarjeta durante su siguiente ciclo de revisión (que ocurre como máximo cada 150 milisegundos) y obtiene su número de serie. Después, consulta la base de datos para saber si esa tarjeta existe, está activa y a qué estudiante pertenece, y revisa si ese estudiante ya se registró como "aceptado" ese mismo día. Con esa información, decide el tipo de evento (aceptado, rebote o ya escaneado) y lo guarda en la base de datos — todo este primer tramo, desde que se acerca la tarjeta hasta que el evento queda guardado, toma normalmente entre 150 y 200 milisegundos.

Del otro lado, la pantalla de métricas no se entera al instante de que ocurrió un evento nuevo: en vez de eso, le pregunta al servidor cada 800 milisegundos si hay algo nuevo que mostrar, y cada 5 segundos vuelve a pedir las estadísticas generales (conteos del día, gráfica por hora, estado del lector). Esta forma de trabajar —donde es la pantalla la que pregunta repetidamente, en vez de que el servidor le avise apenas ocurre algo— es sencilla de construir y suficientemente rápida para este uso, aunque en el peor de los casos puede añadir hasta un segundo entre que la tarjeta se lee y que el modal aparece en pantalla. En promedio, el tiempo total desde que se acerca la tarjeta hasta que se ve reflejado en pantalla ronda entre un cuarto y un tercio de segundo.

Un detalle identificado durante la revisión del sistema: cada vez que la pantalla de métricas pregunta por las estadísticas generales, el servidor también verifica si el servicio del lector sigue activo, y esa verificación específica es, con diferencia, la parte más lenta de toda la operación (puede tardar hasta unas cuantas décimas de segundo). Una mejora sencilla, ya identificada para trabajo futuro, es revisar ese estado con menos frecuencia (por ejemplo, cada 30 o 60 segundos) en vez de en cada consulta.

---

## 9. El panel de control (dashboard)

La pantalla de métricas muestra, siempre referido al día en curso: cuántos accesos válidos ha habido, cuántos rebotes (tarjetas no reconocidas o inactivas), cuántas tarjetas están activas en el sistema, un historial de los eventos más recientes con el nombre del estudiante, y una gráfica de barras que muestra en qué horas del día ha habido más movimiento. Esta gráfica se dibuja con elementos simples de la página web (sin depender de ninguna librería externa de gráficas), lo que mantiene el sistema ligero y fácil de mantener.

El sistema ya calcula, aunque todavía no lo muestra en pantalla, cuántas veces se ha vuelto a pasar una tarjeta ya registrada en el día, y cuáles son las tarjetas con más repeticiones — esta información existe y viaja hasta el navegador en cada actualización, simplemente falta conectarla a un elemento visible; se deja documentado como un ejemplo concreto de cómo personalizar el panel en el futuro sin tener que tocar el código del servidor, solo el de la página web.

Todos los colores del panel están definidos en un solo lugar del código, de forma que cambiar, por ejemplo, el tono de azul usado para "acceso aceptado" actualiza automáticamente ese color en todos los elementos que lo usan (la gráfica, el aviso emergente, el contador), sin tener que buscarlo y cambiarlo manualmente en varios sitios.

Lo que el panel **no** incluye todavía, y que queda documentado como área de oportunidad, es analítica histórica por semana, mes o semestre completo, así como reportes agrupados por grupo o carrera.

---

## 10. Exportación de datos y actualizaciones del sistema

El sistema no cuenta con un proceso automático que mueva o transforme datos entre sistemas distintos; toda la información se escribe y se consulta directamente sobre el mismo archivo de base de datos. Las dos únicas formas de "exportar" información que existen son la descarga en formato CSV (compatible con Excel) y las actualizaciones puntuales de la estructura de la base de datos cuando el sistema evoluciona.

**Exportación a CSV.** Se puede descargar el padrón completo de estudiantes, o la asistencia de un día específico, en un archivo de texto separado por comas que Excel puede abrir directamente, con los acentos mostrándose correctamente. Como medida de seguridad, cualquier campo de texto capturado por una persona (como un nombre) que comience con un símbolo que Excel interpretaría como el inicio de una fórmula (por ejemplo, `=`) se neutraliza automáticamente, para evitar que un dato malicioso se ejecute como una fórmula al abrir el archivo.

**Actualizaciones de estructura.** Cuando el sistema necesita un cambio en la base de datos —por ejemplo, cuando se agregó la bitácora de auditoría—, existe una función que aplica esos cambios de forma segura, incluso si se ejecuta más de una vez por error: si una columna ya existe, simplemente lo reporta y continúa con lo siguiente, sin detener el proceso ni dañar nada. Esta función está desactivada por defecto y solo se activa de forma temporal, junto con un respaldo previo obligatorio, cuando realmente se necesita aplicar un cambio.

---

## 11. Registros y bitácoras

El sistema mantiene varios tipos de registro de lo que va ocurriendo, pensados para poder investigar cualquier problema después de que sucede.

El programa del lector y el vigilante de red escriben su actividad en archivos de texto que se van rotando automáticamente cada semana, conservando aproximadamente un mes de historial antes de descartar lo más antiguo. Los cinco servicios del sistema también generan su propio registro a través de la herramienta estándar de Linux para esto (`journalctl`), lo cual permite, por ejemplo, revisar exactamente qué pasó en una ventana de tiempo específica si se necesita reconstruir un incidente.

Aparte de esto, existe la bitácora de auditoría ya mencionada en la [sección 6](#6-la-base-de-datos), que registra específicamente las acciones administrativas más sensibles: reinicios o apagados de la Raspberry Pi, respaldos y restauraciones de la base de datos, eliminación de registros antiguos, y bajas o promociones masivas de estudiantes. Cada entrada guarda la fecha, la dirección de red desde donde se hizo, qué se hizo y si tuvo éxito o falló. Es importante aclarar qué **no** queda registrado ahí, para no dar una idea equivocada de qué tan completa es esta bitácora: no se registran las altas, ediciones o bajas individuales de un solo estudiante o tarjeta, ni el reinicio de un servicio en particular (solo el apagado o reinicio de la Raspberry Pi completa).

| Fuente de registro | Qué guarda | Se elimina automáticamente |
|---|---|---|
| Registro del lector | Cada tarjeta leída y su resultado | Sí, después de ~1 mes |
| Registro del vigilante de red | Intentos de reconexión Wi-Fi | Sí, después de ~1 mes |
| Bitácora de auditoría | Acciones administrativas sensibles | No, actualmente |
| Registro de servicios (journalctl) | Actividad general de cada servicio | Según configuración de Linux |

*Tabla 7. Fuentes de registro del sistema y su política de retención.*

La bitácora de auditoría, al ser parte de la base de datos y no un archivo de texto, no tiene todavía una limpieza automática — no es urgente porque su volumen es muy bajo (solo se generan entradas por acciones administrativas, no por cada tarjeta leída), pero queda documentado como algo a revisar más adelante, siguiendo el mismo criterio de archivado anual sugerido para los registros de asistencia.

---

## 12. Seguridad

Como parte del proyecto, hice una revisión enfocada en dos riesgos: que alguien pudiera ejecutar comandos no autorizados en la Raspberry Pi a través del panel de administración, y que alguien pudiera acceder al sistema sin autorización.

**Lo que se revisó y quedó descartado como riesgo.** La posibilidad de inyectar comandos maliciosos a través de las funciones que reinician servicios está cerrada, porque el sistema solo acepta nombres de servicio de una lista predefinida y limpia cualquier entrada antes de usarla. También se confirmó que no existe ninguna puerta de la API sin exigir autenticación: absolutamente todas las peticiones pasan primero por la verificación de usuario y contraseña.

**Lo que quedó pendiente, en orden de importancia.** El hallazgo más relevante es que las credenciales viajan por la red sin cifrar (el esquema de autenticación usado codifica, pero no cifra, la contraseña), lo cual significa que alguien conectado a la misma red Wi-Fi podría, en teoría, capturarlas. La solución recomendada es colocar un "intermediario" con cifrado (TLS) delante del panel, y en este documento se deja el procedimiento completo para instalarlo con dos alternativas (Caddy o nginx). El segundo hallazgo es que la contraseña de administrador configurada actualmente es débil; se documenta cómo generar una contraseña robusta de forma segura. El tercero es que ya existe en el código un mecanismo para restringir el acceso solo a direcciones de la red institucional, pero está apagado por configuración — activarlo es tan sencillo como definir esa red en el archivo de configuración. Por último, se identificó una función menor (reiniciar la conexión de red) que no exige una confirmación explícita antes de ejecutarse, a diferencia de otras funciones igual de delicadas, y se documenta el cambio de código necesario para corregirlo.

| Hallazgo | Qué tan urgente es | Situación actual |
|---|---|---|
| Comunicación sin cifrar (sin TLS) | Alta | Pendiente de implementar |
| Contraseña de administrador débil | Alta | Pendiente de rotar |
| Restricción por red institucional apagada | Media | Mecanismo ya construido, falta activarlo |
| Reinicio de red sin confirmación | Baja | Pendiente de un pequeño cambio de código |

*Tabla 8. Hallazgos de la revisión de seguridad, ordenados por urgencia.*

**Buenas prácticas que ya están implementadas.** Vale la pena dejar constancia de lo que el sistema ya hace bien: compara las contraseñas de forma resistente a ataques por medición de tiempo; limita cuántos intentos fallidos de acceso se permiten por minuto; registra en la bitácora cuando una dirección de red es bloqueada por exceder ese límite; incluye cabeceras de seguridad estándar que dificultan ciertos tipos de ataque desde el navegador; usa siempre consultas preparadas hacia la base de datos, lo que evita por completo los ataques de inyección SQL; y valida estrictamente el nombre de cualquier archivo de respaldo antes de restaurarlo, para evitar que alguien intente acceder a archivos fuera de la carpeta permitida.

---

## 13. Qué pasa si algo falla

Como se mencionó en la [sección 2](#2-cómo-funciona-el-sistema-en-general), todos los componentes del sistema dependen del mismo archivo de base de datos, lo cual lo convierte en el **punto único de falla** más importante del sistema: si ese archivo se dañara, ningún componente podría leer ni escribir información hasta restaurarlo. Los demás componentes, en cambio, están diseñados para fallar de forma más contenida.

| Si falla… | Qué se pierde | Qué sigue funcionando |
|---|---|---|
| La base de datos | Todo — nada puede leer ni escribir | Nada, hasta restaurarla |
| El lector de tarjetas | Se detiene el registro de asistencia nueva | El panel de administración y de métricas, con los datos ya existentes |
| El panel de administración | Se pierde la administración y las exportaciones | El registro de asistencia sigue funcionando con normalidad |
| El panel de métricas | Se pierde la visualización en vivo | El registro de asistencia sigue funcionando con normalidad |
| La pantalla física | Solo se apaga la pantalla | Todo lo demás sigue accesible desde cualquier navegador en la red |
| El vigilante de red | El Wi-Fi no se reconecta solo si se cae | El lector sigue funcionando localmente, sin necesitar red |

*Tabla 9. Efecto de la falla de cada componente y qué se mantiene funcionando.*

Cada uno de los cinco servicios se reinicia automáticamente si llega a fallar por un error momentáneo, sin necesitar que alguien intervenga — esto cubre la mayoría de las fallas comunes. Para el caso más delicado, la corrupción del archivo de base de datos, el sistema actualmente solo cuenta con respaldos que se generan bajo demanda desde el panel de administración; como recomendación de bajo costo, documento en este mismo proyecto cómo automatizar esos respaldos con una tarea programada cada cierto número de horas, para reducir al mínimo la cantidad de información que se podría llegar a perder en el peor escenario.

En caso de que sí ocurra una pérdida de información, existen dos caminos documentados: restaurar el respaldo más reciente disponible (el camino normal, que recupera casi todo salvo lo registrado después del último respaldo), o, si no existe ningún respaldo utilizable, reconstruir la base de datos desde cero con la misma herramienta usada en la instalación inicial — este segundo camino sí implica perder por completo el historial de asistencia acumulado, ya que ese historial solo existe dentro de ese archivo.

---

## 14. Conclusiones y recomendaciones

El sistema cumple con el objetivo que se planteó desde el inicio: automatizar el registro de asistencia de forma confiable, con una arquitectura sencilla de entender y mantener, y con buenas prácticas de seguridad ya presentes desde el diseño (como el control estricto de qué comandos se pueden ejecutar, la autenticación obligatoria en toda la API y el uso de consultas preparadas hacia la base de datos). El hecho de dividir el sistema en servicios independientes permite que una falla parcial —por ejemplo, que se caiga el panel de administración— no derribe todo el sistema, salvo por la dependencia compartida de un único archivo de base de datos, que queda identificada con claridad como el principal punto a reforzar.

| Prioridad | Recomendación |
|---|---|
| Alta | Cifrar la comunicación con el panel de administración antes de dejarlo funcionando sin supervisión constante |
| Alta | Cambiar la contraseña de administrador por una robusta y única para este sistema |
| Media | Activar la restricción de acceso por red institucional, que ya está construida en el código |
| Media | Automatizar los respaldos de la base de datos con una tarea programada |
| Baja | Ampliar el panel de métricas con analítica histórica por semana, mes o semestre |
| Baja | Evaluar, si el sistema llegara a proteger algo más sensible que asistencia escolar, migrar a un esquema de tarjetas con autenticación cifrada |

*Tabla 10. Recomendaciones de trabajo futuro, ordenadas por prioridad.*

---

## 15. Glosario

| Término | Qué significa |
|---|---|
| RFID | Tecnología de identificación por radiofrecuencia; permite leer una tarjeta sin contacto físico |
| UID | El número de serie único de una tarjeta |
| SPI | El tipo de conexión por la que el lector y la Raspberry Pi se comunican |
| WAL | Modo de la base de datos que permite leer y escribir al mismo tiempo sin bloquearse |
| Servicio (systemd) | Programa que Linux mantiene corriendo en segundo plano y reinicia si falla |
| API | Conjunto de "puertas" por las que otros programas piden o envían información al sistema |
| SPOF | Punto único de falla: un componente cuya caída detiene todo el sistema |
| Bitácora de auditoría | Historial de acciones administrativas sensibles, con fecha, origen y resultado |

*Tabla 11. Términos técnicos usados en este documento y su significado.*

---

## 16. Referencias

- Documentación oficial de SQLite sobre el modo WAL: https://www.sqlite.org/wal.html
- Documentación oficial de Flask: https://flask.palletsprojects.com/
- Documentación oficial de Gunicorn: https://gunicorn.org/
- Hoja de datos del módulo lector MFRC522 (fabricante NXP)
- Documentación oficial de systemd (gestión de servicios de Linux): https://www.freedesktop.org/software/systemd/man/systemd.service.html

---

<div align="center">

**ITSOEH — Ingeniería en Tecnologías de la Información y Comunicación**
*Servicio Social · Sistema de Control de Asistencia RFID*

</div>
