#!/bin/sh
# 每次容器启动都跑一次迁移再执行传进来的命令（uvicorn 或 arq worker）。
# alembic upgrade head 是幂等的：没有待应用的迁移时直接返回，backend 和
# worker 两个服务同时启动、并发跑这一步，正常情况下不会冲突——真的撞上
# 也只是 alembic 自己的迁移锁短暂等一下，不会破坏数据。
set -e

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> starting: $*"
exec "$@"
