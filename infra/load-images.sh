#!/bin/sh
# 离线导入这个包里预先构建好的镜像——不需要访问公共互联网，也不需要
# `docker build`（backend/frontend 已经在能联网的机器上构建好，
# postgres/redis/minio 三个官方镜像也已经拉好一起打包进来了）。
#
# 用法：在这个目录下执行
#   ./load-images.sh
set -e

cd "$(dirname "$0")"

echo "==> 导入镜像（case-pipeline-hub-backend / frontend / postgres / redis / minio）"
gunzip -c images/case-pipeline-hub-images.tar.gz | docker load

echo
echo "==> 导入完成，本机镜像列表："
docker images | grep -E "case-pipeline-hub|postgres|redis|minio/minio" || true

echo
echo "接下来："
echo "  1. cp infra/.env.prod.example infra/.env.prod，改成真实密码/密钥"
echo "  2. cd infra && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d"
echo "     （不用加 --build——镜像已经导入了，compose 会直接用本地镜像启动）"
echo "  3. 首次部署还需要建管理员账号 + 种子数据，完整步骤见 doc/内部部署指南.md 第 4 节"
