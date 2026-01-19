#!/usr/bin/env bash
# Deploy vinelink Flask app behind gunicorn + nginx with a systemd unit.
# Defaults can be overridden via environment variables before running.

set -euo pipefail

DOMAIN="${DOMAIN:-vinelink.lavroovich.fun}"
SERVICE_NAME="${SERVICE_NAME:-vinelink}"
APP_USER="${APP_USER:-vinelink}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
APP_PORT="${APP_PORT:-8000}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-60}"
GUNICORN_APP_MODULE="${GUNICORN_APP_MODULE:-app:app}"
APP_ROOT="${APP_ROOT:-$(pwd)}"

APP_ROOT="$(cd "$APP_ROOT" && pwd)"

require_root() {
    if [ "${EUID:-$(id -u)}" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then
            exec sudo -E "$0" "$@"
        else
            echo "This script must run as root (sudo not found)." >&2
            exit 1
        fi
    fi
}

detect_pkg_manager() {
    if command -v apt-get >/dev/null 2>&1; then
        PKG_MGR="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MGR="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PKG_MGR="yum"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MGR="pacman"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MGR="zypper"
    else
        echo "Supported package manager not found (apt, dnf, yum, pacman, zypper)." >&2
        exit 1
    fi
}

install_packages() {
    case "$PKG_MGR" in
        apt)
            apt-get update
            DEBIAN_FRONTEND=noninteractive apt-get install -y \
                python3 python3-venv python3-pip nginx git build-essential
            ;;
        dnf)
            dnf install -y python3 python3-pip python3-virtualenv nginx git gcc
            ;;
        yum)
            yum install -y python3 python3-pip python3-virtualenv nginx git gcc
            ;;
        pacman)
            pacman -Sy --noconfirm python python-pip python-virtualenv nginx git base-devel
            ;;
        zypper)
            zypper refresh
            zypper install -y python3 python3-pip python3-virtualenv nginx git gcc
            ;;
    esac
}

ensure_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "systemctl is required. This host does not appear to use systemd." >&2
        exit 1
    fi
}

ensure_app_user() {
    if ! id "$APP_USER" >/dev/null 2>&1; then
        if command -v useradd >/dev/null 2>&1; then
            useradd --system --create-home --shell /bin/bash --user-group "$APP_USER"
        else
            echo "useradd not available; cannot create $APP_USER user." >&2
            exit 1
        fi
    fi

    if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
        groupadd "$APP_GROUP"
    fi

    usermod -a -G "$APP_GROUP" "$APP_USER" 2>/dev/null || true
}

run_as_app() {
    local cmd="$1"
    if command -v sudo >/dev/null 2>&1; then
        sudo -u "$APP_USER" bash -c "$cmd"
    else
        su - "$APP_USER" -s /bin/bash -c "$cmd"
    fi
}

setup_virtualenv() {
    if [ ! -d "$APP_ROOT/venv" ]; then
        run_as_app "python3 -m venv '$APP_ROOT/venv'"
    fi

    run_as_app "'$APP_ROOT/venv/bin/pip' install --upgrade pip"

    if [ -f "$APP_ROOT/requirements.txt" ]; then
        run_as_app "'$APP_ROOT/venv/bin/pip' install -r '$APP_ROOT/requirements.txt'"
    fi

    run_as_app "'$APP_ROOT/venv/bin/pip' install gunicorn"
}

create_systemd_service() {
    cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Gunicorn for ${SERVICE_NAME}
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_ROOT}
Environment="PATH=${APP_ROOT}/venv/bin"
ExecStart=${APP_ROOT}/venv/bin/gunicorn --bind 127.0.0.1:${APP_PORT} --workers ${GUNICORN_WORKERS} --timeout ${GUNICORN_TIMEOUT} ${GUNICORN_APP_MODULE}
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now "${SERVICE_NAME}.service"
}

create_nginx_config() {
    local nginx_conf_path
    local nginx_avail="/etc/nginx/sites-available"
    local nginx_enabled="/etc/nginx/sites-enabled"
    local nginx_conf_d="/etc/nginx/conf.d"

    if [ -d "$nginx_avail" ]; then
        nginx_conf_path="${nginx_avail}/${SERVICE_NAME}.conf"
        mkdir -p "$nginx_avail"
    else
        nginx_conf_path="${nginx_conf_d}/${SERVICE_NAME}.conf"
        mkdir -p "$nginx_conf_d"
    fi

    cat >"$nginx_conf_path" <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    access_log /var/log/nginx/${SERVICE_NAME}.access.log;
    error_log /var/log/nginx/${SERVICE_NAME}.error.log;

    location /static/ {
        alias ${APP_ROOT}/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

    if [ -d "$nginx_enabled" ]; then
        mkdir -p "$nginx_enabled"
        ln -sf "$nginx_conf_path" "$nginx_enabled/${SERVICE_NAME}.conf"
        if [ -f "$nginx_enabled/default" ]; then
            rm -f "$nginx_enabled/default"
        fi
    fi

    if nginx -t; then
        systemctl reload nginx
    else
        echo "Nginx configuration test failed. Check ${nginx_conf_path}." >&2
        exit 1
    fi
}

main() {
    require_root "$@"
    detect_pkg_manager
    ensure_systemd
    install_packages
    ensure_app_user
    mkdir -p "$APP_ROOT"
    chown -R "$APP_USER":"$APP_GROUP" "$APP_ROOT"
    setup_virtualenv
    create_systemd_service
    create_nginx_config
    echo "Deployment completed. Service: ${SERVICE_NAME}. Domain: ${DOMAIN} -> 127.0.0.1:${APP_PORT}"
}

main "$@"
