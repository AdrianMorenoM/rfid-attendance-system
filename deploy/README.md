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
