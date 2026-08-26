#!/bin/sh
# 把分片重新拼回完整的 tar.gz，校验完整性，可以选择顺手解压。
# 用法：把这个目录下所有文件（.part-* 和 .sha256）传到目标机器后，
# 在这个目录下执行：
#   ./reassemble.sh
set -e

cd "$(dirname "$0")"

OUT=case-pipeline-hub-offline-deploy.tar.gz
PARTS=$(ls case-pipeline-hub-offline-deploy.tar.gz.part-* 2>/dev/null | sort)

if [ -z "$PARTS" ]; then
  echo "!!! 当前目录下没有找到 .part-* 分片文件" >&2
  exit 1
fi

echo "==> 拼接分片："
echo "$PARTS"
cat $PARTS > "$OUT"

if [ -f "$OUT.sha256" ]; then
  echo "==> 校验完整性（sha256）"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c "$OUT.sha256"
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$OUT.sha256"
  else
    echo "警告：找不到 shasum/sha256sum，跳过校验（分片传输过程中如果有文件损坏不会被发现）" >&2
  fi
else
  echo "警告：没找到 .sha256 校验文件，跳过完整性校验" >&2
fi

echo
echo "==> 拼接完成：$OUT"
echo "接下来：tar xzf $OUT，进入解压出来的目录跑 ./load-images.sh"
