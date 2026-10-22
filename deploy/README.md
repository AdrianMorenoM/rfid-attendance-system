# Deploy — pasos de instalación en una Pi nueva

## Archivos de systemd
Copiar a `/etc/systemd/system/` y recargar:
```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rfid-backup.timer rfid-incremental-vacuum.timer
```

## Wrapper de systemctl
```bash
sudo cp scripts/rfid-systemctl-wrapper.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/rfid-systemctl-wrapper.sh
```

## Sudoers
```bash
echo 'rfid-svc ALL=(ALL) NOPASSWD: /usr/local/bin/rfid-systemctl-wrapper.sh' | sudo tee /etc/sudoers.d/rfid-svc
sudo chmod 0440 /etc/sudoers.d/rfid-svc
echo 'admin ALL=(ALL) NOPASSWD: /bin/systemctl restart rfid-reader.service' | sudo tee /etc/sudoers.d/rfid-health
sudo chmod 0440 /etc/sudoers.d/rfid-health
```
- El watchdog de red se instala en /usr/local/sbin con: sudo install -o root -g root -m 755 scripts/rfid-network-watchdog.sh /usr/local/sbin/

## Archivos de sistema (instalar en un equipo nuevo)
sudo install -o root -g root -m 644 deploy/system/rfid-shared.conf /etc/tmpfiles.d/
sudo install -o root -g root -m 755 deploy/system/rfid-drop-caches.sh /usr/local/bin/
sudo install -o root -g root -m 644 deploy/systemd/rfid-drop-caches.service /etc/systemd/system/
sudo install -o root -g root -m 644 deploy/polkit/*.rules /etc/polkit-1/rules.d/
sudo install -o root -g root -m 440 deploy/system/rfid-health /etc/sudoers.d/
# deploy/system/rfid-svc es heredado (el CRUD usa polkit); no hace falta instalarlo.
# nginx: deploy/nginx/rfid.conf va en /etc/nginx/sites-enabled/ y los snippets en /etc/nginx/snippets/.
