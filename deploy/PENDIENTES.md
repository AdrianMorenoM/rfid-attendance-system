Lo que falta, además de esos cuatro puntos

Guardar las reglas de ufw en el repo. Aún no hiciste el commit de deploy/ufw-reglas.txt. Revisa el archivo antes: deben verse las tres reglas 443 sin on wlan0.
Perfil Wi-Fi de respaldo (hotspot del celular con nmcli) o un cable a mano, para poder entrar si la Pi no se conecta a la red real. Es lo que más te puede dejar sin acceso.
Probar rfid-fijar-hora de verdad, simulando red sin internet. Sin eso no sabes si las asistencias quedarán con hora válida.
Cert-renew: mañana, journalctl -u rfid-cert-renew.service --since today. Sigue sin registros y no sabemos si renueva. Vence el 20 de diciembre, y en la red real, con internet lento, la renovación puede fallar.
Lector: vigilar journalctl -u rfid-reader.service --since today | grep -i antena. Si vuelve a quedarse sordo sin ese aviso, el parche de la antena no era la causa.
Corte de luz real: una vez, tras un respaldo fresco, desconectar la corriente y confirmar que arranca sola, que el journal conserva el arranque previo y que PRAGMA integrity_check da ok. Más importante aún con el subvoltaje.
Respaldo offsite en otra red: además de revisar la IP en el script, haz una copia a mano en la red real (sudo systemctl start rfid-offsite.service) y confirma OK windows en el journal.
Windows: borrar prueba.txt y el .bak de la llave privada.
Limpieza del kiosk.sh: corre como root con --no-sandbox. Funciona, pero conviene saberlo si el kiosco llegara a abrir páginas externas. Hoy solo abre localhost:5000, así que el riesgo es bajo.
