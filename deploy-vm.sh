#!/usr/bin/env bash
# Korbuino auf dem Server aktualisieren: ./deploy-vm.sh 0.1.44   (als general17 auf dev-device ausführen; früher die VM)
# Baut das Image aus dem GitHub-Tag, hält das alte als Rollback bereit und startet neu.
# Rollback: ./deploy-vm.sh --rollback <alte-version>
# Bei einem Fehler bricht das Skript ab, ohne die Shell zu beenden.
DIR="${KORBUINO_DIR:-/srv/docker/korbunio}"
IMAGE="ghcr.io/lesecuritae/korbunio:latest"
COMPOSE=(docker compose -f compose.yml -f ../korbunio-tailscale.override.yml)

restart() { (cd "$DIR" && "${COMPOSE[@]}" up -d --no-build --pull never); }

main() {
  set -euo pipefail
  if [[ "${1:-}" == "--rollback" ]]; then
    v="${2:?Version angeben, zum Beispiel 0.1.43}"
    docker image inspect "korbunio-rollback:$v" >/dev/null
    docker tag "korbunio-rollback:$v" "$IMAGE"
    restart; echo "Zurückgesetzt auf $v."; return
  fi
  v="${1:?Version angeben, zum Beispiel 0.1.44}"; v="${v#v}"
  old="$(docker run --rm --entrypoint python "$IMAGE" -c 'from supermarkt.version import __version__ as v; print(v)')"
  docker tag "$IMAGE" "korbunio-rollback:$old"
  build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
  git clone -q --depth 1 --branch "v$v" https://github.com/lesecuritae/Korbunio.git "$build"
  docker build -q -t "$IMAGE" "$build" >/dev/null
  restart
  sleep 5
  docker inspect -f '{{.State.Health.Status}}' korbunio
  echo "Läuft jetzt mit $v (vorher $old, Rollback: $0 --rollback $old)."
}
( main "$@" ) || { echo "Fehlgeschlagen; die Shell bleibt offen. Bei Bedarf: $0 --rollback <alte-version>" >&2; false; }
