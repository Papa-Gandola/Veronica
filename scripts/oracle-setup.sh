#!/usr/bin/env bash
# Первичная настройка свежей VM Ubuntu 22.04/24.04 (Oracle Cloud Always Free или любой VPS).
# Запускать от обычного пользователя (ubuntu): bash scripts/oracle-setup.sh
set -euo pipefail

echo "==> Обновление системы"
sudo apt-get update -y && sudo apt-get upgrade -y

echo "==> Docker + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

echo "==> Своп 2 ГБ (на Always Free VM 1 ГБ RAM без свопа freqtrade может упасть по памяти)"
if ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "==> Время по UTC и автообновления безопасности"
sudo timedatectl set-timezone UTC
sudo apt-get install -y unattended-upgrades

echo "==> Фаервол: наружу открыт только SSH"
sudo apt-get install -y ufw
sudo ufw allow OpenSSH
sudo ufw --force enable

echo
echo "Готово. Перелогинься (exit и снова ssh), чтобы docker работал без sudo, затем:"
echo "  cd Veronica && cp .env.example .env && nano .env && docker compose up -d"
