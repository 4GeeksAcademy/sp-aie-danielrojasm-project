#!/usr/bin/env bash
# Endurecimiento básico del servidor de TrackFlow (Ubuntu/Debian). Idempotente: se puede repetir.
#
#   sudo bash infra/server/harden.sh --check            # solo muestra el estado (evidencia antes/después)
#   sudo bash infra/server/harden.sh trackflow          # aplica: usuario de operaciones, carpetas, SSH y UFW
#
# Antes de aplicar, deja abierta la sesión de root actual y prueba en otra terminal
# `ssh <usuario>@<servidor>` + `sudo -v`. El script aborta si el usuario no tiene clave SSH, para no dejarte fuera.
set -euo pipefail

APP_ROOT=/srv/trackflow
SSH_DROPIN=/etc/ssh/sshd_config.d/00-trackflow-hardening.conf
# Público: SSH (operaciones, con rate limit) y HTTP/HTTPS del proxy. API, MCP, Next, Redis, Qdrant,
# Keycloak y Flower escuchan solo en 127.0.0.1 (docker-compose.yml).
PUBLIC_TCP_PORTS=(80 443)

check() {
  echo "== SSH (valores efectivos)"
  sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|maxauthtries|allowusers) ' || true
  echo "== Firewall"
  if command -v ufw >/dev/null; then ufw status verbose; else echo "ufw no instalado"; fi
  echo "== Puertos TCP en escucha"
  ss -tlnH | awk '{print $4}' | sort -u
  echo "== Usuarios con shell y sudo"
  awk -F: '$7 ~ /(bash|sh)$/ {print $1}' /etc/passwd
  getent group sudo || true
  echo "== Permisos de ${APP_ROOT}"
  if [[ -d $APP_ROOT ]]; then
    find "$APP_ROOT" -maxdepth 2 -printf '%M %u:%g %p\n' | sort -k3
  else
    echo "${APP_ROOT} no existe"
  fi
}

if [[ ${1:-} == "--check" ]]; then
  check
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "Ejecuta el script como root (sudo)." >&2; exit 1; }
OPS_USER=${1:?Uso: harden.sh <usuario_de_operaciones> | --check}

# 1. Usuario de operaciones, sin contraseña de login (solo clave SSH) y con sudo.
if ! id "$OPS_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$OPS_USER"
fi
usermod -aG sudo "$OPS_USER"
OPS_HOME=$(getent passwd "$OPS_USER" | cut -d: -f6)
install -d -m 700 -o "$OPS_USER" -g "$OPS_USER" "$OPS_HOME/.ssh"
if [[ ! -s $OPS_HOME/.ssh/authorized_keys && -s /root/.ssh/authorized_keys ]]; then
  # Las mismas claves con las que hoy se entra como root.
  install -m 600 -o "$OPS_USER" -g "$OPS_USER" /root/.ssh/authorized_keys "$OPS_HOME/.ssh/authorized_keys"
fi
if [[ ! -s $OPS_HOME/.ssh/authorized_keys ]]; then
  echo "ABORTADO: ${OPS_USER} no tiene ninguna clave en ${OPS_HOME}/.ssh/authorized_keys; sin ella perderías el acceso." >&2
  exit 1
fi
chmod 600 "$OPS_HOME/.ssh/authorized_keys"
# sudo pide contraseña: si la cuenta no tiene, se pide ahora (interactivo).
if passwd -S "$OPS_USER" | awk '{exit !($2 == "L" || $2 == "NP")}'; then
  echo "Define la contraseña de sudo para ${OPS_USER}:"
  passwd "$OPS_USER"
fi

# 2. Carpetas: código, logs y configuración sensible separados. Nadie fuera del usuario de operaciones entra.
install -d -m 750 -o "$OPS_USER" -g "$OPS_USER" "$APP_ROOT"
install -d -m 750 -o "$OPS_USER" -g "$OPS_USER" "$APP_ROOT/app"     # clon del monorepo
install -d -m 750 -o "$OPS_USER" -g "$OPS_USER" "$APP_ROOT/logs"    # logs de la API y los workers
install -d -m 700 -o "$OPS_USER" -g "$OPS_USER" "$APP_ROOT/config"  # .env con JWT_SECRET_KEY, LLM_API_KEY, etc.
find "$APP_ROOT/config" -type f -exec chmod 600 {} +
find "$APP_ROOT/config" -type f -exec chown "$OPS_USER:$OPS_USER" {} +

# 3. SSH: sin root, sin contraseñas, solo el usuario de operaciones. El drop-in `00-` gana a `50-cloud-init.conf`
# (sshd se queda con el primer valor que lee).
cat > "$SSH_DROPIN" <<EOF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers ${OPS_USER}
EOF
chmod 644 "$SSH_DROPIN"
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd

# 4. Firewall: todo lo entrante cerrado salvo SSH (con rate limit) y HTTP/HTTPS.
if ! command -v ufw >/dev/null; then
  apt-get update -qq && apt-get install -y -qq ufw
fi
ufw default deny incoming
ufw default allow outgoing
ufw limit OpenSSH
for port in "${PUBLIC_TCP_PORTS[@]}"; do
  ufw allow "${port}/tcp"
done
ufw --force enable

echo
echo "Hecho. Estado final:"
check
