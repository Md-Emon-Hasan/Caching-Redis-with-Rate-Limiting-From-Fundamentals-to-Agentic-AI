#!/usr/bin/env bash
# scripts/demo.sh
# Exercises the running service with curl so you can see the raw HTTP.
# Start first:  uvicorn app.main:app --reload
set -u
BASE=${BASE:-http://localhost:8000}
EMAIL="demo$RANDOM@example.com"
PASS="supersecret123"

hr() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

hr "health"
curl -s $BASE/health; echo

hr "register (queues a welcome email job)"
curl -s -X POST $BASE/auth/register \
  -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}"; echo

hr "login -> session id"
SID=$(curl -s -X POST $BASE/auth/login \
  -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["session_id"])')
echo "SID=${SID:0:12}..."

hr "inspect the session in Redis"
redis-cli hgetall "sess:$SID"
echo "TTL: $(redis-cli ttl "sess:$SID")s"

hr "protected route with Bearer"
curl -s $BASE/auth/me -H "Authorization: Bearer $SID"; echo

hr "my devices"
curl -s $BASE/auth/sessions -H "Authorization: Bearer $SID"; echo

hr "login rate limit: 7 wrong passwords (expect 401 x5 then 429)"
for i in $(seq 1 7); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/auth/login \
    -H 'content-type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"wrongpassword\"}")
  echo "  attempt $i -> $code"
done

hr "token bucket on /api/expensive (cost 5, capacity 20)"
for i in $(seq 1 6); do
  echo -n "  call $i -> "
  curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/expensive -H "Authorization: Bearer $SID"
done

hr "queue depth"
curl -s $BASE/admin/queue; echo

hr "logout everywhere"
curl -s -X POST $BASE/auth/logout-all -H "Authorization: Bearer $SID"; echo
echo -n "session after revocation -> "
curl -s -o /dev/null -w '%{http_code}\n' $BASE/auth/me -H "Authorization: Bearer $SID"
