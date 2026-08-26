病例流水线中枢 — 离线部署包
================================

这个包是为"部署机器不能访问公共互联网"这个场景准备的——里面已经带了
预先构建好的 Docker 镜像（case-pipeline-hub-backend/frontend，以及
postgres/redis/minio 三个官方镜像），不需要在目标机器上 `docker build`、
不需要 `git clone`、不需要访问 PyPI/npm 镜像源。

目录结构
--------
images/     预先 docker save 好并压缩的镜像（backend/frontend/postgres/
            redis/minio），load-images.sh 会自动导入
infra/      docker-compose.prod.yml + .env.prod.example（部署配置模板）
doc/        完整文档，包括这次要看的《内部部署指南.md》和业务方场景库
            xlsx（首次部署种子数据要用）
backend/    后端完整源码（供参考、以后需要重新 build 或改动时用；这次
            部署不需要重新 build，用 images/ 里已经打包好的镜像就够）
frontend/   前端完整源码，同上

目标机器上唯一需要有的是 Docker（含 Compose v2）——这个本身也需要提前
装好，装 Docker 这一步如果目标机器也没有外网权限，得另外单独准备
Docker 的离线安装包，不在这个包的范围内。

快速开始
--------
1. 把整个包传到目标机器（U盘/内网文件传输都行），解压
2. 在这个目录下执行：
     ./load-images.sh
3. 按提示配置 infra/.env.prod、启动、做首次部署的种子数据——完整步骤、
   每一步会看到什么输出、常见问题排查，全部写在 doc/内部部署指南.md
   里，不在这个 README 里重复。

这份包在打包前，backend/frontend 镜像和整套 docker-compose 编排都在一台
能联网的机器上真实构建、真实启动、真实跑通过一次完整流程（起容器→建表
→种子数据→真实登录→真实取数据），不是照着配置文件推测出来的。

重新生成这个包
--------------
代码有更新、需要重新打一份离线包时，在能联网的机器上、仓库根目录下跑：
    ./infra/build-offline-package.sh
产出在 dist/case-pipeline-hub-offline-deploy.tar.gz。
