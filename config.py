from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./chartflow.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    moex_base_url: str = "https://iss.moex.com/iss"
    moex_board: str = "TQBR"
    binance_base_url: str = "https://api.binance.com"

    default_history_days: int = 730
    min_history_points: int = 60

    verify_hour_msk: int = 19
    verify_minute_msk: int = 15

    admin_user: str = "admin"
    admin_password: str = "admin"
    admin_secret_key: str = "change-admin-session-key"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()