from enum import Enum
from pathlib import Path

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_project_root() -> Path:
    """定位项目根目录。

    以当前文件为起点向上查找最近一个包含 ``pyproject.toml`` 的目录，
    这样即便 ``config.py`` 在包内被移动层级，也不会再把 ``.env`` 定位错。
    若始终找不到，则按 ``src/app/logs/core`` 的层级回退到第 4 层父目录。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parents[4]


# 项目根目录（仓库根）与 src 目录，.env 固定放在 src/.env
PROJECT_ROOT = _resolve_project_root()
SRC_DIR = PROJECT_ROOT / "src"
ENV_FILE = SRC_DIR / ".env"


class BaseAppSettings(BaseSettings):
    """所有配置类的公共基类，统一指定 .env 路径与 UTF-8 编码。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


class AppSettings(BaseAppSettings):
    APP_NAME: str = "FastAPI Template"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = "0.1.0"
    LICENSE_NAME: str | None = "MIT"
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class LoggingSettings(BaseAppSettings):
    LOG_LEVEL: str = "INFO"
    DB_ECHO: bool = False


class CryptSettings(BaseAppSettings):
    SECRET_KEY: str = "change-me-please-generate-a-random-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


class DatabaseSettings(BaseAppSettings):
    """数据库配置的标记基类，具体实现见各数据库子类。"""


class SQLiteSettings(DatabaseSettings):
    SQLITE_URI: str = "./sql_app.db"
    SQLITE_SYNC_PREFIX: str = "sqlite:///"
    SQLITE_ASYNC_PREFIX: str = "sqlite+aiosqlite:///"


class MySQLSettings(DatabaseSettings):
    MYSQL_USER: str = "username"
    MYSQL_PASSWORD: str = "password"
    MYSQL_SERVER: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DB: str = "dbname"
    MYSQL_SYNC_PREFIX: str = "mysql://"
    MYSQL_ASYNC_PREFIX: str = "mysql+aiomysql://"
    MYSQL_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MYSQL_URI(self) -> str:  # noqa: N802
        return f"{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_SERVER}:{self.MYSQL_PORT}/{self.MYSQL_DB}"


class PostgresSettings(DatabaseSettings):
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_SYNC_PREFIX: str = "postgresql://"
    POSTGRES_ASYNC_PREFIX: str = "postgresql+asyncpg://"
    POSTGRES_URL: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_URI(self) -> str:  # noqa: N802
        return (
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


class FirstUserSettings(BaseAppSettings):
    ADMIN_NAME: str = "admin"
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-this-password"


class TestSettings(BaseAppSettings):
    """测试环境预留配置。"""


class RedisCacheSettings(BaseAppSettings):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379
    # 三个 Redis 配置共用同一个密码；留空表示服务端未开启 requirepass
    REDIS_PASSWORD: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_CACHE_URL(self) -> str:  # noqa: N802
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"


class ClientSideCacheSettings(BaseAppSettings):
    CLIENT_CACHE_MAX_AGE: int = 60


class RedisQueueSettings(BaseAppSettings):
    REDIS_QUEUE_HOST: str = "localhost"
    REDIS_QUEUE_PORT: int = 6379
    REDIS_PASSWORD: str | None = None


class RedisRateLimiterSettings(BaseAppSettings):
    REDIS_RATE_LIMIT_HOST: str = "localhost"
    REDIS_RATE_LIMIT_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_RATE_LIMIT_URL(self) -> str:  # noqa: N802
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_RATE_LIMIT_HOST}:{self.REDIS_RATE_LIMIT_PORT}"


class DefaultRateLimitSettings(BaseAppSettings):
    DEFAULT_RATE_LIMIT_LIMIT: int = 10
    DEFAULT_RATE_LIMIT_PERIOD: int = 3600


class SkipInfraSettings(BaseAppSettings):
    SKIP_INFRA_ON_START: bool = False


class EnvironmentOption(Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EnvironmentSettings(BaseAppSettings):
    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL


class EmbeddingModelSettings(BaseAppSettings):
    DASHSCOPE_API_KEY: str | None = None
    DASHSCOPE_MODEL: str | None = None


class RerankModelSettings(BaseAppSettings):
    """qwen3-rerank 重排序模型配置。"""

    DASHSCOPE_RERANK_MODEL: str = "qwen3-rerank"


class DeepSeekSettings(BaseAppSettings):
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_MODEL: str | None = None
    DEEPSEEK_BASE_URL: str | None = None


class UploadSettings(BaseAppSettings):
    """文件上传配置，用于后续 LangChain RAG 离线阶段的文档加载与处理。"""

    UPLOAD_DIR: Path = PROJECT_ROOT / "storage" / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 100


class DocumentSettings(BaseAppSettings):
    """本地文档目录配置，供 LangChain RAG 离线阶段按路径加载文档。"""

    DOCUMENT_DIR: Path = PROJECT_ROOT / "storage" / "documents"
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150


class MilvusSettings(BaseAppSettings):
    """Milvus 向量数据库连接配置。

    ``ENABLE_MILVUS`` 默认关闭，未部署 Milvus 时不会发起连接，避免启动或调用报错。
    """

    ENABLE_MILVUS: bool = False
    # 连接成功后是否自动创建 RAG 所需的集合与索引；关闭后需手动调用
    # ``rag_collections.ensure_collections`` 完成初始化。
    AUTO_CREATE_RAG_COLLECTIONS: bool = False
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_URI: str | None = None
    MILVUS_TOKEN: str | None = None
    MILVUS_USER: str | None = None
    MILVUS_PASSWORD: str | None = None
    MILVUS_DB_NAME: str = "default"


class QWeatherJwtSettings(BaseAppSettings):
    """和风天气（QWeather）JWT 认证配置。"""

    QWEATHER_JWT_ALGORITHM: str = "EdDSA"
    QWEATHER_JWT_PRIVATE_KEY: str | None = None
    QWEATHER_JWT_KEY_ID: str | None = None
    QWEATHER_JWT_SUBJECT: str | None = None
    QWEATHER_JWT_ISSUER: str | None = None
    QWEATHER_API_HOST: str | None = None  # API Host 订阅域名，如 xxx.re.qweatherapi.com
    QWEATHER_JWT_TTL_SECONDS: int = 86400  # 86400 秒 = 24 小时，和风天气要求 exp - iat 不超过 24 小时
    QWEATHER_JWT_LEEWAY_SECONDS: int = 30


class DingTalkSettings(BaseAppSettings):
    """钉钉 DWS CLI 配置（钉协助手智能体）。"""

    DINGTALK_DWS_BIN: str = "dws"  # dws 可执行文件，可在 .env 中用绝对路径覆盖
    DINGTALK_ENABLE_WRITE: bool = False  # 写操作总开关：发消息/DING/创建日程等，默认关闭
    DINGTALK_TIMEOUT_SECONDS: int = 30  # dws 子命令执行超时（秒）
    DINGTALK_OUTPUT_MAX_CHARS: int = 4000  # CLI 输出截断长度
    DINGTALK_ROBOT_WEBHOOK_TOKEN: str | None = None  # 群自定义机器人 Webhook token（用于机器人消息）


class ECommerceSettings(BaseAppSettings):
    """电商导购智能体（带三层记忆）配置。

    记忆与商品源均通过后端字符串解耦，切换时只需修改配置，无需改动业务代码：

    - 短期记忆（Checkpointer）：``memory`` 进程内，``postgres`` 持久化。
    - 短期记忆窗口管理：``truncate`` 截断最近 N 条、``token`` 按 token 预算裁剪、
      ``summary`` 旧消息总结压缩进长期画像，三种策略可配置切换。
    - 长期记忆（MemoryStore）：``inmemory`` 进程内零依赖，``postgres`` 走 pgvector。
    """

    """
     - 商品源（ProductSource）：``builtin`` 内置目录、``pgvector`` 向量 RAG、
      ``milvus`` 向量 RAG、``hybrid`` RAG + 目录兜底。
    """
    ECOMMERCE_PRODUCT_SOURCE: str = "builtin"  # builtin | pgvector | milvus | hybrid
    ECOMMERCE_PRODUCT_TOP_K: int = 5  # 商品检索返回条数
    ECOMMERCE_PRODUCT_MIN_SIMILARITY: float = 0.3  # 商品向量检索相似度阈值

    """
    - 短期记忆（Checkpointer）：``memory`` 进程内，``postgres`` 持久化。
    - 短期记忆窗口管理：``truncate`` 截断最近 N 条、``token`` 按 token 预算裁剪、
      ``summary`` 旧消息总结压缩进长期画像，三种策略可配置切换。
    """
    ECOMMERCE_CHECKPOINT_BACKEND: str = "memory"  # memory | postgres
    ECOMMERCE_WINDOW_STRATEGY: str = "truncate"  # 短期记忆窗口策略：truncate | token | summary | hybrid
    ECOMMERCE_WINDOW_MAX_MESSAGES: int = 20  # truncate 策略保留的最近消息条数
    ECOMMERCE_WINDOW_MAX_TOKENS: int = 4000  # token 策略的上下文预算

    ECOMMERCE_WINDOW_SUMMARY_KEEP: int = 10  # summary 策略保留的最近消息条数
    ECOMMERCE_WINDOW_SUMMARY_HARD_LIMIT: int = 50  # summary 策略硬上限：超过且总结失败时强制丢弃，防止无界增长
    ECOMMERCE_WINDOW_HYBRID_KEEP: int = 12  # hybrid 策略保留的最近消息条数（原文）
    ECOMMERCE_WINDOW_HYBRID_MAX_TOKENS: int = 3000  # hybrid 策略喂给大模型的 token 预算兜底
    ECOMMERCE_WINDOW_HYBRID_HARD_LIMIT: int = 60  # hybrid 策略硬上限：超过且总结失败时强制丢弃
    ECOMMERCE_WINDOW_TOOL_MAX_CHARS: int = 800  # 工具输出截断字符数，避免大段工具结果撑爆上下文

    ECOMMERCE_MEMORY_BACKEND: str = "inmemory"  # inmemory | postgres
    ECOMMERCE_MEMORY_TOP_K: int = 3  # 长期记忆召回条数
    ECOMMERCE_MEMORY_DECAY_DAYS: int = 30  # 记忆时间衰减半衰期（天）
    ECOMMERCE_MEMORY_MIN_RELEVANCE: float = 0.2  # 召回语义相关度阈值，低于该值视为无关记忆
    ECOMMERCE_MEMORY_MAX_PER_USER: int = 100  # 单用户长期记忆条数上限，超过后淘汰低分记忆（0 表示不限）
    ECOMMERCE_PROFILE_MAX_PREFS: int = 6  # 注入提示词的画像偏好键数上限，超过后按 query 相关性裁剪（0 表示不裁剪）
    ECOMMERCE_PROFILE_SUMMARY_MAX_CHARS: int = 400  # 画像历史摘要注入的最大字符数，超出截断（0 表示不截断）


class OrchestratorSettings(BaseAppSettings):
    """多智能体编排器配置。"""

    ORCHESTRATOR_SUBAGENT_TRANSPORT: str = "inprocess"  # inprocess | a2a（子智能体传输方式）


class A2ASettings(BaseAppSettings):
    """A2A 协议层配置：Agent Card 基础地址、任务持久化后端与客户端连接/重试。"""

    A2A_PUBLIC_BASE_URL: str = "http://localhost:8888"  # Agent Card 对外暴露的基础 URL（生产须填真实公网地址）
    A2A_TASK_STORE: str = "memory"  # memory | sqlite | postgres（任务持久化后端）
    A2A_POSTGRES_URL: str | None = None  # A2A_TASK_STORE=postgres 时的异步连接串（postgresql+asyncpg://...）

    # A2A 客户端：连接池 / 超时 / 重试
    A2A_CLIENT_TIMEOUT_SECONDS: float = 30.0  # 单次请求整体超时（连接/读/写/池）
    A2A_CLIENT_MAX_CONNECTIONS: int = 100  # 每个子智能体连接池最大连接数
    A2A_CLIENT_MAX_KEEPALIVE_CONNECTIONS: int = 20  # 连接池最大空闲保活连接数
    A2A_CLIENT_MAX_RETRIES: int = 2  # 连接建立/首个响应前的瞬态网络错误重试次数
    A2A_CLIENT_RETRY_BACKOFF_SECONDS: float = 0.5  # 重试指数退避的基数（秒）

    @field_validator("A2A_PUBLIC_BASE_URL", mode="after")
    @classmethod
    def _normalize_public_base_url(cls, value: str) -> str:
        """去掉末尾斜杠，并确保是绝对 http(s) 地址。"""
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("A2A_PUBLIC_BASE_URL 必须是绝对 http(s) 地址")
        return value


class CustomerServiceSettings(BaseAppSettings):
    """客服智能体配置。"""

    CUSTOMER_SERVICE_ORDER_SOURCE: str = "builtin"  # 订单数据源：builtin（内置演示）；后续接 http/postgres 真实订单系统
    CUSTOMER_SERVICE_RETURN_SOURCE: str = "builtin"  # 退换货申请源：builtin（内置演示）；后续接真实售后系统


class AnalystSettings(BaseAppSettings):
    """分析智能体配置。"""

    ANALYST_REPORT_SOURCE: str = "builtin"  # 运营日报数据源：builtin（内置演示）；后续接真实数据仓库


class AnnouncementSettings(BaseAppSettings):
    """对外公告发布审批智能体（Human-in-the-loop）配置。"""

    # 目标群名：审批通过后发布群公告；也可用 conversation_id 直接指定跳过群名解析
    ANNOUNCEMENT_NOTICE_GROUP: str = "刘夏的师生群"
    ANNOUNCEMENT_NOTICE_CONVERSATION_ID: str | None = None
    # 进入人工审批时是否推送机器人通知
    ANNOUNCEMENT_NOTIFY_ENABLED: bool = True
    # 机器人安全关键词：钉钉机器人设置了关键词时，通知文本必须包含其一才能送达
    ANNOUNCEMENT_NOTIFY_KEYWORD: str | None = None
    # 命中这些关键词的公告强制升级为人工审批（逗号分隔）
    ANNOUNCEMENT_RISK_KEYWORDS: str = "全体,紧急,重要,官方,正式,通知"


class Settings(
    AppSettings,
    LoggingSettings,
    PostgresSettings,
    CryptSettings,
    FirstUserSettings,
    TestSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    RedisQueueSettings,
    RedisRateLimiterSettings,
    DefaultRateLimitSettings,
    SkipInfraSettings,
    EnvironmentSettings,
    EmbeddingModelSettings,
    RerankModelSettings,
    DeepSeekSettings,
    UploadSettings,
    DocumentSettings,
    MilvusSettings,
    QWeatherJwtSettings,
    DingTalkSettings,
    ECommerceSettings,
    OrchestratorSettings,
    A2ASettings,
    CustomerServiceSettings,
    AnalystSettings,
    AnnouncementSettings,
):
    """聚合所有配置的顶层配置对象。"""


settings = Settings()
