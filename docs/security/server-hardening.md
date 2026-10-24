# Endurecimiento del servidor de TrackFlow

Script: [`infra/server/harden.sh`](../../infra/server/harden.sh). Informe OWASP asociado:
[`owasp-top10-audit.md`](owasp-top10-audit.md).

## Qué tiene que ser público

| Puerto | Servicio | Exposición |
| --- | --- | --- |
| 22/tcp | SSH de operaciones | Público con `ufw limit` (máx. 6 conexiones en 30 s por IP), solo clave, solo el usuario de operaciones |
| 80/tcp | Proxy HTTPS | Público, solo para redirigir a 443 y renovar el certificado |
| 443/tcp | Proxy HTTPS → backoffice, web y API | Público, TLS |
| 8000, 8001, 3000, 3001 | API, servidor MCP, Next (web y backoffice) | Solo `127.0.0.1` (`docker-compose.yml`); los publica el proxy |
| 6379, 6333, 8080, 5555 | Redis, Qdrant, Keycloak, Flower | Solo `127.0.0.1` |

Las credenciales de los carriers, el `LLM_API_KEY` y el `JWT_SECRET_KEY` viven solo en `/srv/trackflow/config/.env`
(700/600). Ninguna ruta del chat del cliente las lee: el agente solo tiene el secreto de cliente OAuth
`support-agent` (scope `incidents:read`).

## Línea base (antes)

Lo que se sabe sin entrar al servidor:

- Se accede como `root` con clave (`User root` en el `~/.ssh/config` de la máquina de desarrollo). No hay un
  usuario de operaciones.
- `docker-compose.yml` publicaba la API (8000), el servidor MCP (8001) y los dos `next dev` (3000 y 3001) en todas
  las interfaces. Docker añade sus propias reglas de iptables antes que las de UFW, así que esos puertos quedaban
  abiertos a internet aunque el firewall los bloqueara. Corregido en este cambio (hallazgo C3 del informe).
- El estado real de `sshd`, del firewall y de las carpetas se captura con:

```bash
sudo bash infra/server/harden.sh --check > baseline-antes.txt
```

## Qué aplica el script

`sudo bash infra/server/harden.sh trackflow`

1. **Usuario de operaciones `trackflow`**: sin contraseña de login (solo clave SSH), en el grupo `sudo` con
   contraseña. Copia las claves de `/root/.ssh/authorized_keys` y **aborta si se queda sin ninguna**, para que
   cerrar el acceso de root no deje el servidor inaccesible. No entra en el grupo `docker` (equivale a root):
   los contenedores se gestionan con `sudo docker compose`.
2. **Carpetas con permisos explícitos** (dueño `trackflow:trackflow`):

   | Ruta | Modo | Contenido |
   | --- | --- | --- |
   | `/srv/trackflow` | 750 | raíz de la aplicación |
   | `/srv/trackflow/app` | 750 | clon del monorepo (código) |
   | `/srv/trackflow/logs` | 750 | logs de la API y los workers |
   | `/srv/trackflow/config` | 700 | `.env` y secretos; cada archivo 600 |

3. **SSH** (`/etc/ssh/sshd_config.d/00-trackflow-hardening.conf`): `PermitRootLogin no`,
   `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `MaxAuthTries 3`, `LoginGraceTime 30`,
   `AllowUsers trackflow`. El prefijo `00-` gana a `50-cloud-init.conf` de DigitalOcean, que activa contraseñas.
   Valida con `sshd -t` antes de recargar.
4. **UFW**: entrada denegada por defecto; `limit OpenSSH`, `allow 80/tcp`, `allow 443/tcp`.

Orden seguro: ejecutar con la sesión de root abierta, comprobar en otra terminal `ssh trackflow@<servidor>` y
`sudo -v`, y solo después cerrar la sesión de root.

## Verificación (después)

```bash
sudo bash infra/server/harden.sh --check > baseline-despues.txt
ssh root@<servidor>                      # esperado: Permission denied (publickey)
ssh -o PubkeyAuthentication=no trackflow@<servidor>   # esperado: Permission denied (publickey)
nmap -Pn -p 1-10000 <servidor>           # desde fuera: solo 22, 80 y 443 abiertos
```

Valores esperados en `--check`: `permitrootlogin no`, `passwordauthentication no`, `allowusers trackflow`;
`Status: active` con `Default: deny (incoming)` y solo `22/tcp LIMIT IN`, `80/tcp ALLOW IN`, `443/tcp ALLOW IN`;
en escucha fuera de `127.0.0.1` solo 22, 80 y 443.

## Evidencia en el servidor del curso (Ubuntu 22.04.5 LTS)

Aplicado por fases para no perder el acceso: primero se creó `trackflow` con una clave ed25519 y se comprobó que
entraba y que `sudo whoami` devolvía `root`; después `trackflow` ejecutó `sudo bash harden.sh trackflow`.

**Antes** (`harden.sh --check`):

```text
== SSH (valores efectivos)
maxauthtries 6
permitrootlogin yes
pubkeyauthentication yes
passwordauthentication yes
kbdinteractiveauthentication no
== Firewall
Status: inactive
== Puertos TCP en escucha
0.0.0.0:22
127.0.0.1:18789
127.0.0.1:39393
127.0.0.53%lo:53
[::1]:18789
[::]:22
== Usuarios con shell y sudo
root
sudo:x:27:
== Permisos de /srv/trackflow
/srv/trackflow no existe
```

**Después** (`harden.sh --check`):

```text
== SSH (valores efectivos)
maxauthtries 3
permitrootlogin no
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
allowusers trackflow
== Firewall
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)
22/tcp (OpenSSH)           LIMIT IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
(y las mismas tres reglas en v6)
== Usuarios con shell y sudo
root
trackflow
sudo:x:27:trackflow
== Permisos de /srv/trackflow
drwxr-x--- trackflow:trackflow /srv/trackflow
drwxr-x--- trackflow:trackflow /srv/trackflow/app
drwx------ trackflow:trackflow /srv/trackflow/config
drwxr-x--- trackflow:trackflow /srv/trackflow/logs
```

**Pruebas desde fuera del servidor:**

```text
$ ssh root@<servidor>
root@<servidor>: Permission denied (publickey).
$ ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password trackflow@<servidor>
trackflow@<servidor>: Permission denied (publickey).
$ ssh trackflow@<servidor> whoami           # con la clave
trackflow
puertos TCP: 22, 80 y 443 aceptan conexión; 8000, 3000 y 18789 cerrados o filtrados
```

Los servicios en `127.0.0.1:18789` y `:39393` ya estaban antes y siguen solo en loopback; root conserva su cuenta
(cron, servicios), pero no entra por SSH.
