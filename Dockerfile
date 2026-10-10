# syntax=docker/dockerfile:1.7

# 说明：
# 1) 早期版本用 ghcr.io/astral-sh/uv 的 Python 组合标签做多阶段构建，但该组合标签在 ghcr 上
#    已不存在（拉取报 manifest unknown），国内网络下 ghcr 也不稳定。因此改为官方 Python 镜像 +
#    从 PyPI 镜像源安装 uv，构建可复现。
# 2) uv.lock 里每个包都锁定了 https://pypi.org/simple 与 https://files.pythonhosted.org/packages/
#    的具体地址。pypi.org / files.pythonhosted.org 在国内实测只有 17~23 KB/s，直接构建会卡死。
#    因此构建时把锁文件里的这两个地址整体重写到镜像源（文件路径结构与官方一致，哈希不变），
#    实测镜像源可达 10 MB/s 以上。海外环境可用 --build-arg 覆盖为官方源。
FROM python:3.13-slim-bookworm

ARG PYPI_INDEX=https://mirrors.aliyun.com/pypi/simple/
ARG PYPI_FILES=https://mirrors.aliyun.com/pypi/packages/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_DEFAULT_INDEX=${PYPI_INDEX}

WORKDIR /app

# 先复制依赖清单，利用镜像层缓存
COPY pyproject.toml uv.lock ./
COPY .python-version ./
COPY src ./src

RUN pip install --no-cache-dir -i "$PYPI_INDEX" "uv==0.12.9" \
    && sed -i "s|https://pypi.org/simple|$PYPI_INDEX|g; s|https://files.pythonhosted.org/packages/|$PYPI_FILES|g" uv.lock \
    && uv sync --frozen --no-dev --no-install-project \
    && rm -rf /root/.cache/uv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# -------- 使用 gunicorn 时替换下面的命令 --------
# CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
