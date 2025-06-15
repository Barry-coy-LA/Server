from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "TianMu智能服务器"
    VERSION: str = "1.0.0"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # 审批系统配置
    APPROVAL_TOKEN_EXPIRE_MINUTES: int = 30
    APPROVAL_PDF_DIR: str = "Data/approval/reports"
    APPROVAL_DB_PATH: str = "Data/approval/approval.db"

    # 邮件配置（可选默认值）
    DEFAULT_SMTP_SERVER: str = "smtp.company.com"
    DEFAULT_SMTP_PORT: int = 587
    DEFAULT_FROM_EMAIL: str = "tianmu@company.com"

    class Config:
        env_file = ".env"

settings = Settings()
