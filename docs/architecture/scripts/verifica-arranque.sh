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
#   5. sentry_cpu_profiler.node NO debe aparecer en ningun proceso
#   6. HTTP 200 en /api/auth/can-register y 307 en /
#
# NOTA: todos los recorridos de /proc filtran por `readlink exe` = node. Sin
# eso, el propio comando de busqueda aparece en los resultados -- contiene la
# cadena que busca- y da falsos positivos en el 4 y un falso NEGATIVO en el 5,
# que es el peor de los dos.
#
# Uso: bash /opt/homeserver/postiz/verifica-arranque.sh

C="docker exec postiz"
CI="docker exec -i postiz"      # el -i hace falta para lo que recibe por pipe

echo "===== $(date -Is) ====="

echo "-- 1. Contenedor --"
docker inspect postiz --format 'StartedAt={{.State.StartedAt}} Health={{.State.Health.Status}} RestartCount={{.RestartCount}}'

echo "-- 2. pm2 --"
$C pm2 jlist 2>/dev/null | $CI node -e \
  'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{for(const p of JSON.parse(s))console.log("   "+p.name.padEnd(13)+" pid="+String(p.pid).padEnd(7)+" restarts="+p.pm2_env.restart_time+" "+p.pm2_env.status)})'

echo "-- 3. El pid de pm2 ES el proceso real? (no debe verse pnpm/dotenv/sh) --"
for n in backend frontend orchestrator; do
  pid=$($C pm2 pid $n 2>/dev/null | tr -d '\r\n ')
  echo "   $n (pid $pid): $($C sh -c "tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null")"
done

echo "-- 4. Procesos node vivos (uno por app, sin duplicados) --"
$C sh -c 'for p in /proc/[0-9]*; do
  case "$(readlink $p/exe 2>/dev/null)" in *node)
    echo "   ${p#/proc/} | $(tr "\0" " " < $p/cmdline 2>/dev/null | cut -c1-70)";;
  esac
done'

echo "-- 5. sentry_cpu_profiler cargado en algun proceso node? --"
$C sh -c 'hay=0
for p in /proc/[0-9]*; do
  case "$(readlink $p/exe 2>/dev/null)" in *node)
    grep -qF sentry_cpu_profiler $p/maps 2>/dev/null && { echo "   SI, en ${p#/proc/}  <-- MAL"; hay=1; };;
  esac
done
[ $hay -eq 0 ] && echo "   no, en ninguno  <-- bien"'

echo "-- 6. API y frontend a traves de nginx --"
$C sh -c 'for u in /api/auth/can-register /; do
  printf "   %-28s " "$u"
  node -e "require(\"http\").get({host:\"localhost\",port:5000,path:\"$u\",timeout:8000},r=>{console.log(\"HTTP \"+r.statusCode);process.exit(0)}).on(\"error\",e=>{console.log(\"ERROR \"+e.message);process.exit(0)})"
done'

echo "-- 7. Datos (baseline 2026-08-05: Media 83, Post 67, 58 ficheros) --"
docker exec postiz-postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -Atc "select count(*) from \"Media\""' | sed 's|^|   Media: |'
docker exec postiz-postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -Atc "select count(*) from \"Post\""'  | sed 's|^|   Post:  |'
echo "   $(find /mnt/seagate/postiz-media -type f | wc -l) ficheros en disco"

echo "-- 8. Workflows vivos --"
docker exec temporal temporal workflow list --address 172.22.0.4:7233 --namespace default --limit 40 2>/dev/null \
  | grep Running | sed 's|^|   |'
