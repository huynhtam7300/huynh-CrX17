#!/usr/bin/env bash
set -euo pipefail

CRX_DIR=/opt/crx
CRX_USER=crx

sudo useradd -m -s /bin/bash -U $CRX_USER || true
sudo mkdir -p $CRX_DIR
sudo chown -R $CRX_USER:$CRX_USER $CRX_DIR

# copy mã nguồn trước rồi chạy phần dưới bằng user crx
sudo -u $CRX_USER bash -lc "
  cd $CRX_DIR
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
"
sudo cp deploy/crx-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crx-runner
echo '✅ Đã bật service crx-runner. Xem log: journalctl -u crx-runner -f'