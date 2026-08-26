#!/bin/sh
# 在一台能访问公共互联网的机器上跑这个脚本，产出一个完整的离线部署包
# （tar.gz + 分片），传到隔离网络里的目标机器上解压、跑 load-images.sh
# 就能用，不需要目标机器有任何外网权限。每次代码有更新、要重新打包给
# 内网部署时都跑这一个脚本，不是手工重复一遍构建步骤——这个脚本本身
# 就是把这次打包时手工做过、并且真实验证过整个链路（build → save →
# load → 起容器 → 真实登录，以及分片拆完再拼回去、校验和、真的能重新
# 解出同一个 tar.gz）的那些步骤固化下来。
#
# 用法（在仓库根目录下）：
#   ./infra/build-offline-package.sh
# 分片大小默认 90m（很多内网传输/邮件系统卡在 100MB，90m 留了安全余量），
# 需要改的话：
#   SPLIT_SIZE=45m ./infra/build-offline-package.sh
set -e

cd "$(dirname "$0")/.."   # 回到仓库根目录
STAGE=dist/case-pipeline-hub-offline-deploy
IMAGE_TAG=latest
SPLIT_SIZE=${SPLIT_SIZE:-90m}

echo "==> 清理旧的打包目录"
rm -rf "$STAGE"
mkdir -p "$STAGE/images" "$STAGE/infra" "$STAGE/doc"

echo "==> 构建 backend/frontend 生产镜像"
docker build -f backend/Dockerfile.prod -t case-pipeline-hub-backend:$IMAGE_TAG backend/
docker build -f frontend/Dockerfile.prod -t case-pipeline-hub-frontend:$IMAGE_TAG frontend/

echo "==> 确保 postgres/redis/minio 官方镜像也在本地（compose 用到的具体版本以 docker-compose.prod.yml 为准）"
docker pull postgres:16-alpine
docker pull redis:7-alpine
docker pull minio/minio:latest

echo "==> 导出并压缩全部镜像（体积较大，可能要几分钟）"
docker save \
  case-pipeline-hub-backend:$IMAGE_TAG case-pipeline-hub-frontend:$IMAGE_TAG \
  postgres:16-alpine redis:7-alpine minio/minio:latest \
  | gzip -1 > "$STAGE/images/case-pipeline-hub-images.tar.gz"

echo "==> 拷贝部署配置、文档、源码"
cp infra/docker-compose.prod.yml "$STAGE/infra/"
cp infra/.env.prod.example "$STAGE/infra/"
cp -R doc/. "$STAGE/doc/"
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='.env' --exclude='.env.prod' \
  backend/ "$STAGE/backend/"
rsync -a --exclude='node_modules' --exclude='dist' --exclude='.env' \
  frontend/ "$STAGE/frontend/"
cp infra/load-images.sh "$STAGE/" 2>/dev/null || true
cp infra/offline-package-README.txt "$STAGE/README.txt" 2>/dev/null || true

echo "==> 安全检查：确认没有真实密钥文件被打包进去"
if find "$STAGE" \( -iname ".env" -o -iname ".env.prod" \) | grep -q .; then
  echo "!!! 发现真实 .env 文件混进了打包目录，已中止，不生成 tar" >&2
  find "$STAGE" \( -iname ".env" -o -iname ".env.prod" \)
  exit 1
fi

echo "==> 打包成 tar.gz"
TARBALL=dist/case-pipeline-hub-offline-deploy.tar.gz
tar czf "$TARBALL" -C dist case-pipeline-hub-offline-deploy
rm -rf "$STAGE"

echo "==> 分片（每片 $SPLIT_SIZE，很多内网传输渠道单文件有大小限制）"
PARTS_DIR=dist/parts
rm -rf "$PARTS_DIR"
mkdir -p "$PARTS_DIR"
split -b "$SPLIT_SIZE" "$TARBALL" "$PARTS_DIR/case-pipeline-hub-offline-deploy.tar.gz.part-"
shasum -a 256 "$TARBALL" | sed "s#$TARBALL#case-pipeline-hub-offline-deploy.tar.gz#" > "$PARTS_DIR/case-pipeline-hub-offline-deploy.tar.gz.sha256"
cp infra/reassemble.sh "$PARTS_DIR/"

echo "==> 验证分片能拼回原文件（不是只生成，真的拼一遍校验和）"
( cd "$PARTS_DIR" && ./reassemble.sh && rm -f case-pipeline-hub-offline-deploy.tar.gz )

echo
echo "完成，两种交付形态都在 dist/ 下："
echo "  单文件（不需要分片传输时用）：$TARBALL"
ls -lh "$TARBALL"
echo "  分片（每片 < 100MB，传完在目标机器上跑 dist/parts/reassemble.sh 拼回去）：dist/parts/"
ls -lh "$PARTS_DIR"
