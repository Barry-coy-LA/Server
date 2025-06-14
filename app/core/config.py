from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "TianMu智能服务器"
    VERSION: str = "1.0.0"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    class Config:
        env_file = ".env"

settings = Settings()
