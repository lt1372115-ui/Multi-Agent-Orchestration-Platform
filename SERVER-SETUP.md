# 新 ECS 实例初始化手册（Alibaba Cloud Linux 3）

> 适用场景：全新阿里云 ECS（Alibaba Cloud Linux 3，x86_64），以 `root` 登录。
> 目标：装好 Docker、uv、Postgres + pgvector、Redis、Milvus 全家桶、Nginx 等基础设施，
> 让本地开发机上的项目能通过公网连上服务器上的数据库与缓存。
>
> 本文档中所有命令除特别说明外都在服务器上执行，按顺序做即可。

## 0. 关键参数（先确认，后面全程要用）

| 项 | 值 |
| --- | --- |
| 服务器公网 IP | `<你的服务器公网 IP>` |
| 本地开发机出口 IP | 见 `/etc/fail2ban/jail.local` 的 `ignoreip`，安全组也要填它 |
| Postgres 端口 | `5432`（对公网开放） |
| Redis 端口 | `6379`（对公网开放） |
| Postgres 用户 / 密码 | `postgres` / `<你的强密码>` |
| Redis 密码 | `<你的强密码>` |
| 业务库名 | `langchain_rag_demo` |
| Milvus 端口 | `19530`（仅本机，暂不对外） |

> 本文档中所有密码 / IP 均为占位符，请替换为你自己的值；真实凭据只放本地 `src/.env`（已在 `.gitignore` 中忽略）。
> 若使用弱口令，**安全完全依赖阿里云安全组的来源 IP 限制**，见第 15 章。

---

## 1. 系统初始化

```bash
sudo dnf update -y

# 时区与时间同步（和风天气 JWT 的过期校验依赖准确时钟）
sudo timedatectl set-timezone Asia/Shanghai
sudo systemctl enable --now chronyd
timedatectl status
```

## 2. 启用 EPEL

fail2ban 和 certbot 都来自 EPEL。

```bash
sudo dnf install -y epel-release || \
sudo dnf install -y https://mirrors.aliyun.com/epel/epel-release-latest-8.noarch.rpm

sudo dnf makecache
sudo dnf repolist | grep -i epel
```

## 3. 基础工具

```bash
sudo dnf install -y \
  git curl wget unzip zip tar rsync \
  vim tmux htop iotop nethogs ncdu tree lsof \
  jq sqlite \
  net-tools bind-utils telnet traceroute mtr \
  ca-certificates openssl \
  postgresql redis
```

其中 `postgresql` 提供 `psql`、`redis` 提供 `redis-cli`，后面调试不用进容器。

> 注意：这两个包只当客户端用，**不要** `systemctl start postgresql` 或 `systemctl start redis`，
> 否则会和容器抢 5432 / 6379 端口。

## 4. 编译工具链

```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y gcc gcc-c++ make python3-devel \
  openssl-devel libffi-devel bzip2-devel zlib-devel \
  readline-devel sqlite-devel xz-devel libaio-devel
```

正常用不到，留着是为了某个 Python 包没有 cp313 预编译轮子时能回退到源码编译。

## 5. Docker 与 Docker Compose

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
sudo sed -i 's|download.docker.com|mirrors.aliyun.com/docker-ce|g' /etc/yum.repos.d/docker-ce.repo

sudo dnf install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker
```

如果报 `$releasever` 找不到包，把仓库文件里的 `$releasever` 手动替换成 `8` 再装。

### 5.1 配置镜像加速与日志轮转

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live",
    "https://uzgc99bt.mirror.aliyuncs.com"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" },
  "live-restore": true
}
EOF

sudo systemctl daemon-reload && sudo systemctl restart docker
```

顺序很重要：**daocloud 放第一位**。实测阿里云个人加速器对 `pgvector/pgvector` 这类非官方库镜像不命中缓存，
会导致回源 Docker Hub 超时；换成 daocloud 打头后原命令 `docker pull pgvector/pgvector:pg16` 直接成功。

`log-opts` 两行防止容器日志写满系统盘。

验证：

```bash
docker --version                              # 24+
docker compose version                        # v2.x
docker info | grep -A4 "Registry Mirrors"     # 三个源都要列出来
docker run --rm hello-world
```

## 6. uv 与 Python 3.13

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
uv python install 3.13
```

### 6.1 配置 PyPI 镜像

```bash
mkdir -p ~/.config/uv
cat > ~/.config/uv/uv.toml <<'EOF'
[[index]]
url = "https://mirrors.aliyun.com/pypi/simple/"
default = true
EOF

mkdir -p ~/.pip
cat > ~/.pip/pip.conf <<'EOF'
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
EOF
```

## 7. 交换分区（2~4 GB 内存的实例必做）

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

## 8. 内核参数

Milvus 需要较大的 `max_map_count`：

```bash
sudo tee /etc/sysctl.d/99-milvus.conf > /dev/null <<'EOF'
vm.max_map_count = 262144
fs.file-max = 1048576
EOF

sudo sysctl --system
sysctl vm.max_map_count
```

阿里云默认把 `vm.swappiness` 设为 0，意思是内存不足时宁可 OOM 也不换页。
内存吃紧时建议改成 10：

```bash
grep -n swappiness /etc/sysctl.conf
sudo sed -i 's/^[[:space:]]*vm\.swappiness[[:space:]]*=.*/vm.swappiness = 10/' /etc/sysctl.conf
sudo sysctl -p
sysctl vm.swappiness
```

注意 `/etc/sysctl.conf` 是最后被应用的，所以在 `/etc/sysctl.d/` 里新建文件是覆盖不掉它的，
必须直接改这个文件。

## 9. 拉取镜像

```bash
docker pull redis:alpine
docker pull pgvector/pgvector:pg16
docker pull minio/minio:RELEASE.2024-05-28T17-19-04Z
docker pull milvusdb/milvus:v2.5.4
docker pull zilliz/attu:latest
docker pull quay.io/coreos/etcd:v3.5.14
```

如果某个镜像拉不动，用其他源带前缀拉取再改回标签：

```bash
docker pull docker.m.daocloud.io/library/redis:alpine
docker tag docker.m.daocloud.io/library/redis:alpine redis:alpine
```

标签名必须和后面 `docker run` 里写的完全一致。

## 10. Postgres + pgvector

```bash
docker run -d --name pgvector \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=<你的强密码> \
  -e POSTGRES_DB=fastapi_template \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  --restart unless-stopped \
  pgvector/pgvector:pg16
```

`-p 5432:5432` 是对公网绑定，安全性由安全组保证。

等 10 秒左右，创建业务库并激活扩展（扩展按库生效，每个库都要单独建）：

```bash
docker exec pgvector psql -U postgres -c "CREATE DATABASE langchain_rag_demo;"

docker exec pgvector psql -U postgres -d langchain_rag_demo \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

docker exec pgvector psql -U postgres -d langchain_rag_demo -c "\dx"
```

验证：

```bash
docker exec pgvector pg_isready -U postgres
PGPASSWORD=<你的强密码> psql -h 127.0.0.1 -U postgres -d langchain_rag_demo -c "select 1;"
```

> `POSTGRES_PASSWORD` 只在数据目录**第一次**初始化时生效。卷已存在时改这个环境变量不会改变实际密码，
> 要换密码必须走 SQL：`ALTER USER postgres WITH PASSWORD '新密码';`

## 11. Redis

```bash
docker run -d --name redis \
  -p 6379:6379 \
  -v redisdata:/data \
  --restart unless-stopped \
  redis:alpine \
  redis-server --appendonly yes --requirepass <你的强密码>
```

两个要点：

- `--requirepass` 必须设。Redis 7 默认开启 `protected-mode`，没有密码时会直接拒绝非本机连接，
  报 `DENIED Redis is running in protected mode`。
- 项目的 `config.py` 原本不支持 Redis 密码（连接串写死成 `redis://host:port`），
  本仓库已经改好：三处 Redis 配置都新增了 `REDIS_PASSWORD`，有值时拼成 `redis://:密码@主机:端口`。
  如果在新环境里用的是未修改的旧代码，需要同步这个改动。

验证：

```bash
docker exec redis redis-cli --no-auth-warning -a <你的强密码> ping    # 期望 PONG
```

## 12. Milvus 全家桶（可选）

项目 `.env` 里 `ENABLE_MILVUS=false`，不装也不影响其它功能。3.5 GB 内存的实例跑起来会比较紧。

一键脚本（单行命令 + heredoc，避免多行粘贴卡在续行提示符）：

```bash
cat > /root/milvus-up.sh <<'SCRIPT'
set -e
MINIO_PASS=<你的 MinIO 密码，至少 8 位>

docker network create milvus 2>/dev/null || true
docker rm -f milvus-etcd milvus-minio milvus-standalone milvus-attu 2>/dev/null || true

docker run -d --name milvus-etcd --network milvus -e ETCD_AUTO_COMPACTION_MODE=revision -e ETCD_AUTO_COMPACTION_RETENTION=1000 -e ETCD_QUOTA_BACKEND_BYTES=4294967296 -e ETCD_SNAPSHOT_COUNT=50000 -v etcd-data:/etcd --restart unless-stopped quay.io/coreos/etcd:v3.5.14 etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls=http://0.0.0.0:2379 --data-dir /etcd

docker run -d --name milvus-minio --network milvus -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=$MINIO_PASS -v minio-data:/minio_data --restart unless-stopped minio/minio:RELEASE.2024-05-28T17-19-04Z server /minio_data --console-address ":9001"

sleep 20

docker run -d --name milvus-standalone --network milvus -e ETCD_ENDPOINTS=milvus-etcd:2379 -e MINIO_ADDRESS=milvus-minio:9000 -e MINIO_ACCESS_KEY_ID=minioadmin -e MINIO_SECRET_ACCESS_KEY=$MINIO_PASS -v milvus-data:/var/lib/milvus -p 127.0.0.1:19530:19530 -p 127.0.0.1:9091:9091 --restart unless-stopped milvusdb/milvus:v2.5.4 milvus run standalone

docker run -d --name milvus-attu --network milvus -p 127.0.0.1:3000:3000 -e MILVUS_URL=milvus-standalone:19530 --restart unless-stopped zilliz/attu:latest

docker ps --format "table {{.Names}}\t{{.Status}}"
SCRIPT

bash -n /root/milvus-up.sh && bash /root/milvus-up.sh
```

等一两分钟后验证：

```bash
curl -s http://127.0.0.1:9091/healthz; echo     # 期望 OK
```

踩坑记录：

- **MinIO 密码必须 ≥ 8 位**。用过短的弱口令时容器会 `Restarting (1)` 反复重启，
  表现为 Milvus 报 `lookup milvus-minio: no such host`、`Not all components are healthy, 3/8`。
  DNS 报错是症状，根因是 MinIO 没起来。
- Milvus 启动慢，`healthz` 返回 `x/8` 时先等，超过 3 分钟再看 `docker logs milvus-standalone`。
- Attu 绑在 `127.0.0.1:3000`，本地要看界面就开隧道：
  `ssh -L 3000:127.0.0.1:3000 root@<你的服务器公网 IP>`，然后浏览器访问 `http://127.0.0.1:3000`。

## 13. Nginx 与 certbot

```bash
sudo dnf install -y nginx certbot python3-certbot-nginx
sudo systemctl enable --now nginx
curl -sI http://127.0.0.1/ | head -1     # 期望 HTTP/1.1 200 OK
```

只装工具，暂不配置站点。这个项目的接口是 SSE 流式响应，将来配置时必须补三项：

```nginx
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_buffering off;
proxy_read_timeout 300s;
```

## 14. fail2ban

```bash
sudo dnf install -y fail2ban

sudo tee /etc/fail2ban/jail.local > /dev/null <<'EOF'
[DEFAULT]
backend  = systemd
bantime  = 1h
findtime = 10m
maxretry = 5
ignoreip = 127.0.0.1/8 ::1 <你的本机出口 IP>

[sshd]
enabled = true
EOF

sudo systemctl enable --now fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status sshd
```

`ignoreip` 里填你自己的出口 IP，否则反复输错密码会把自己挡在 SSH 外面，只能走控制台 VNC 救援。
出口 IP 变了记得同步这里和安全组。

## 15. 阿里云安全组

控制台 → 安全组 → 入方向，添加两条规则，**授权对象填你自己的公网 IP/32**：

| 端口 | 协议 | 授权对象 |
| --- | --- | --- |
| 5432 | TCP | 你的出口 IP/32 |
| 6379 | TCP | 你的出口 IP/32 |

出方向保持默认全放行即可，应用要访问 `api.deepseek.com`、`*.re.qweatherapi.com`、
`dashscope.aliyuncs.com` 等外部服务。

**不要填 `0.0.0.0/0`**。若密码是弱口令，安全组来源限制是唯一有效的防线。

## 16. 本地项目配置

本地 `src/.env` 中与服务器相关的项：

```ini
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<你的强密码>
POSTGRES_SERVER=<你的服务器公网 IP>
POSTGRES_PORT=5432
POSTGRES_DB=langchain_rag_demo

REDIS_CACHE_HOST=<你的服务器公网 IP>
REDIS_CACHE_PORT=6379
REDIS_QUEUE_HOST=<你的服务器公网 IP>
REDIS_QUEUE_PORT=6379
REDIS_RATE_LIMIT_HOST=<你的服务器公网 IP>
REDIS_RATE_LIMIT_PORT=6379
REDIS_PASSWORD=<你的强密码>

ENABLE_MILVUS=false
```

启动（不加 `--skip-infra`，让它在启动时建表并连 Redis）：

```powershell
cd D:\project\智能体学习\weather_agent
$env:UV_CACHE_DIR="D:\project\智能体学习\weather_agent\.uv-cache"
uv run --cache-dir .uv-cache python src/run.py --no-reload
```

启动日志里应出现：

```
正在创建/校验数据库表结构（Base.metadata.create_all）
数据库表结构创建/校验完成
Redis 缓存连接成功: redis://:***@<你的服务器公网 IP>:6379
```

## 17. 最终验证清单

```bash
# 服务器侧
curl -s ifconfig.me; echo                                    # 必须与你的服务器公网 IP 一致
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker exec redis redis-cli --no-auth-warning -a <你的强密码> ping  # PONG
PGPASSWORD=<你的强密码> psql -h 127.0.0.1 -U postgres -d langchain_rag_demo -c "select 1;"
sudo ss -lntp | grep -E ':(5432|6379)\b'
free -h

# 本地
curl.exe -s http://127.0.0.1:8888/api/v1/health
curl.exe -s http://127.0.0.1:8888/api/v1/products
```

`ss` 的输出里 5432 和 6379 应该挂在 `0.0.0.0` 或 `::` 上（因为要对外提供），
而 19530、3000 应该只在 `127.0.0.1` 上。

## 附：依赖的代码改动（本仓库已包含）

如果在新环境用的是未修改的旧代码，需要补上这两处，否则 Redis 密码会导致连接失败。

`src/app/logs/core/config.py`：

```python
class RedisCacheSettings(BaseAppSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    @computed_field
    @property
    def REDIS_CACHE_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"
```

`RedisQueueSettings`、`RedisRateLimiterSettings` 同样各加一个 `REDIS_PASSWORD` 字段，
限流那处的 `REDIS_RATE_LIMIT_URL` 用相同的拼装方式。

`src/app/logs/core/setup.py` 中队列连接需带上密码：

```python
queue.pool = await create_pool(
    RedisSettings(
        host=settings.REDIS_QUEUE_HOST,
        port=settings.REDIS_QUEUE_PORT,
        password=settings.REDIS_PASSWORD or None,
    )
)
```

## 附：常见问题速查

| 现象 | 原因与处理 |
| --- | --- |
| `docker pull` 报 `registry-1.docker.io` 超时 | 镜像源顺序问题，把 `docker.m.daocloud.io` 放到 `registry-mirrors` 第一位并重启 Docker |
| `docker info` 看不到 Registry Mirrors | `daemon.json` 路径写错，必须是 `/etc/docker/daemon.json` |
| 多行命令卡在 `>` 提示符 | 引号或反斜杠没闭合，`Ctrl+C` 退出，改成单行命令或用 heredoc 写脚本 |
| `Restarting (1)` 反复重启 | `docker logs <容器>` 看具体报错；MinIO 常见原因是密码短于 8 位 |
| `protected mode` 拒绝连接 | Redis 没设密码，加 `--requirepass` |
| `database "xxx" does not exist` | 业务库没建，`docker exec pgvector psql -U postgres -c "CREATE DATABASE xxx;"` |
| `extension "vector" is not available` | 该库未激活扩展，`CREATE EXTENSION IF NOT EXISTS vector;` |
| 改了 `.env` 密码却连不上 | Postgres 的 `POSTGRES_PASSWORD` 对已初始化的卷无效，需 `ALTER USER` |
