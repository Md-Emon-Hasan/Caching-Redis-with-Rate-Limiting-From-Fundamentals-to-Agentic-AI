# Phase 7 — Production Redis (End-to-End)

Take everything from Phases 1–6 and make it **reliable at scale**: persistence,
replication, automatic failover, sharding, monitoring, and disaster recovery.

Unlike earlier phases, these demos **spin up real Redis topologies on your
machine** — real masters, replicas, sentinels, and a live cluster — so you can
watch failover and sharding happen for yourself.

> 📘 **Start with `Phase7_Handbook.pdf`.** It explains every concept from
> scratch. Read it top to bottom and you'll understand all of Phase 7.

---

## 📂 What's in this package

```
phase7-production-redis/
├── README.md                 ← you are here
├── Phase7_Handbook.pdf       ← the illustrated handbook (READ THIS FIRST)
│
├── concepts/                 ← 6 runnable demos (each starts REAL Redis nodes)
│   ├── 01_persistence.py         RDB + AOF: data survives a restart
│   ├── 02_replication.py         master → replica: read scaling + redundancy
│   ├── 03_sentinel.py            kill the master, watch AUTOMATIC failover
│   ├── 04_cluster.py             build a real 3-master cluster, shard keys
│   ├── 05_monitoring.py          health report + alerts from INFO/SLOWLOG
│   └── 06_disaster_recovery.py   backup off-site, destroy, restore, verify
│
├── configs/                  ← commented production config files
│   ├── redis-production.conf     sane prod baseline (security, memory, persistence)
│   ├── redis-replica.conf        a replica node
│   └── sentinel.conf             one Sentinel (run 3+)
│
├── docker/                   ← one-command topologies
│   ├── docker-compose.replication.yml   master + 2 replicas
│   ├── docker-compose.sentinel.yml      master + replica + 3 sentinels (HA)
│   ├── docker-compose.cluster.yml       6-node cluster (3 masters + 3 replicas)
│   ├── docker-compose.monitoring.yml    Redis + exporter + Prometheus + Grafana
│   └── prometheus.yml
│
└── scripts/                  ← cron-ready ops scripts
    ├── backup.sh                 BGSAVE + copy off-site + retention
    ├── restore.sh                restore from a backup RDB
    └── healthcheck.sh            quick health snapshot (exit code aware)
```

Every file is heavily commented in English so you can learn by reading it.

---

## 🚀 Quick start — run the demos

Each demo is self-contained: it launches its own Redis instances on high ports,
runs the scenario, prints the result, and cleans up after itself.

```bash
pip install "redis>=5"        # the client (cluster support included)
cd concepts

python 01_persistence.py         # kills & restarts Redis; data survives
python 02_replication.py         # writes on master, reads from replica
python 03_sentinel.py            # KILLS the master -> auto failover in ~4s
python 04_cluster.py             # real 3-master cluster; keys shard across it
python 05_monitoring.py          # health report + alerts + slowlog
python 06_disaster_recovery.py   # off-site backup -> total loss -> restore
```

> The demos need the `redis-server` and `redis-cli` binaries available locally
> (e.g. `apt install redis-server` or `brew install redis`).

---

## 🐳 Run the topologies with Docker

```bash
cd docker

# Master + 2 read replicas
docker compose -f docker-compose.replication.yml up -d
docker exec -it redis-master redis-cli INFO replication

# High availability with Sentinel — then test failover:
docker compose -f docker-compose.sentinel.yml up -d
docker stop redis-master
docker exec -it sentinel-1 redis-cli -p 26379 \
    SENTINEL get-master-addr-by-name mymaster   # returns the NEW master

# 6-node cluster (form it once after 'up'):
docker compose -f docker-compose.cluster.yml up -d
docker exec -it redis-node-1 redis-cli --cluster create \
  127.0.0.1:7001 127.0.0.1:7002 127.0.0.1:7003 \
  127.0.0.1:7004 127.0.0.1:7005 127.0.0.1:7006 \
  --cluster-replicas 1 --cluster-yes

# Full monitoring stack (Grafana on :3000, admin/admin):
docker compose -f docker-compose.monitoring.yml up -d
```

---

## 🛠️ Ops scripts

```bash
cd scripts
./healthcheck.sh 127.0.0.1 6379          # quick status snapshot
./backup.sh 127.0.0.1 6379 /var/backups/redis   # snapshot + copy + prune
./restore.sh /var/backups/redis/dump-XXXX.rdb    # restore from a backup
```

`backup.sh` is cron-friendly: `0 * * * * /path/to/backup.sh` for hourly backups.

---

## 🧭 Which topology do I need?

| Situation | Use |
|-----------|-----|
| Small app, data fits in RAM, some downtime OK | Single node + persistence + backups |
| Read-heavy, want redundancy | Replication (+ Sentinel) |
| Need zero-touch failover (HA) | Sentinel — 3 sentinels, quorum 2 |
| Data or writes exceed one machine | Cluster — shard across masters |

---

## ✅ Production checklist

- Persistence on (AOF `everysec` + RDB) and **backups copied off-site** on a schedule.
- Set `maxmemory` + an eviction policy so Redis never eats the whole box.
- Require a password (or ACLs); disable dangerous commands (`FLUSHALL`, `KEYS`).
- Never run `KEYS` in production — use `SCAN`; watch the slow log.
- Run 3+ Sentinels on separate hosts with a quorum for HA.
- Export metrics to Prometheus/Grafana; alert on memory %, hit rate, evictions.
- **Practice the restore** regularly — an untested backup is a hope.

---

## ✅ Requirements
- Python 3.10+ and `redis>=5`
- `redis-server` + `redis-cli` binaries (for the concept demos)
- Docker (optional, for the `docker/` topologies)

---

## 🎉 Roadmap complete → the capstone

You've gone from caching fundamentals all the way to running Redis reliably at
scale. The final capstone — an **AI Research Assistant** — combines every phase:
LLM cache, embedding cache, session store, rate limiter, agent memory,
checkpointing, pub/sub, and queues, deployed behind a load balancer with the HA
and monitoring from this phase. You now have every building block it needs.
