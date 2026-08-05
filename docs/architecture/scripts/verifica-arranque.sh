#!/bin/bash
# Verificacion post-despliegue del contenedor postiz. SOLO LEE, no muta nada.
#
# Copia viva: /opt/homeserver/postiz/verifica-arranque.sh   (si tocas una,
# actualiza la otra; se comparan con md5sum).
#
# Que buscar en la salida -- el detalle esta en ARRANQUE_Y_SUPERVISION.md:
#   2. tres apps online con restarts=0
#   3. el pid de pm2 debe ser `node .../main.js` o `next-server`,
#      NUNCA pnpm, sh ni dotenv
#   4. un proceso por app, sin duplicados
#   5. cinco modulos nativos, y sentry_cpu_profiler.node NO debe aparecer
#   6. HTTP 200 en /api/auth/can-register y 307 en /
#
# Uso: bash /opt/homeserver/postiz/verifica-arranque.sh
echo "===== $(date -Is) ====="

echo "-- 1. Contenedor --"
docker inspect postiz --format 'StartedAt={{.State.StartedAt}} Health={{.State.Health.Status}} RestartCount={{.RestartCount}}'

echo "-- 2. pm2 --"
docker exec postiz pm2 jlist 2>/dev/null | docker exec -i postiz node -e   'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{for(const p of JSON.parse(s))console.log("   "+p.name.padEnd(13)+" pid="+String(p.pid).padEnd(7)+" restarts="+p.pm2_env.restart_time+" "+p.pm2_env.status)})'

echo "-- 3. El pid de pm2 ES el proceso real? (no debe verse pnpm/dotenv/sh) --"
for n in backend frontend orchestrator; do
  pid=$(docker exec postiz pm2 pid $n 2>/dev/null | tr -d '\r\n ')
  cmd=$(docker exec postiz sh -c "tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null")
  echo "   $n (pid $pid): $cmd"
done

echo "-- 4. Procesos node vivos (no debe haber duplicados) --"
docker exec postiz sh -c 'for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null); case "$c" in *main.js*|*next*|*pnpm*|*dotenv*) echo "   ${p#/proc/} | $c";; esac; done'

echo "-- 5. Modulos nativos del backend (NO debe aparecer sentry_cpu_profiler) --"
bpid=$(docker exec postiz sh -c 'for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null); case "$c" in *backend/src/main.js*) echo ${p#/proc/};; esac; done' | head -1)
docker exec postiz sh -c "grep -F .node /proc/$bpid/maps 2>/dev/null | rev | cut -d' ' -f1 | rev | sort -u | sed 's|^|   |'"

echo "-- 6. API y frontend a traves de nginx --"
docker exec postiz sh -c 'for u in /api/auth/can-register /; do printf "   %-28s " "$u"; node -e "require(\"http\").get({host:\"localhost\",port:5000,path:\"$u\",timeout:8000},r=>{console.log(\"HTTP \"+r.statusCode);process.exit(0)}).on(\"error\",e=>{console.log(\"ERROR \"+e.message);process.exit(0)})"; done'

echo "-- 7. Datos (baseline 2026-08-05: Media 83, Post 67, 58 ficheros) --"
docker exec postiz-postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -Atc "select count(*) from \"Media\""' | sed 's|^|   Media: |'
docker exec postiz-postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -Atc "select count(*) from \"Post\""' | sed 's|^|   Post:  |'
echo "   $(find /mnt/seagate/postiz-media -type f | wc -l) ficheros en disco"

echo "-- 8. Workflows vivos --"
docker exec temporal temporal workflow list --address 172.22.0.4:7233 --namespace default --limit 40 2>/dev/null | grep Running | sed 's|^|   |'
