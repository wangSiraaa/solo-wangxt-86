#!/usr/bin/env bash
# 一键启动：PostgreSQL(用户空间) + Django(托管前端构建产物)
set -e
PG=/workspace/.pg

if ! "$PG/bin/pg_ctl" -D "$PG/data" status > /dev/null 2>&1; then
  "$PG/bin/pg_ctl" -D "$PG/data" -l "$PG/logfile" -o "-p 54329 -k /tmp" start
fi

cd /workspace/backend
exec python3 manage.py runserver 0.0.0.0:8000
