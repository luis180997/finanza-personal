"""Configuracion central. Todo se lee de variables de entorno / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]      # .../backend
PROJECT_DIR = BASE_DIR.parent                        # raiz del proyecto

# En Docker la carpeta de datos es un volumen montado en otra ruta, por eso es
# parametrizable. Fuera de Docker sigue siendo <raiz>/data.
DATA_DIR = Path(os.getenv("DATA_DIR") or (PROJECT_DIR / "data"))
SECRETS_DIR = Path(os.getenv("SECRETS_DIR") or (PROJECT_DIR / "secrets"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    database_url: str = f"sqlite:///{(DATA_DIR / 'finanzas.db').as_posix()}"
    timezone: str = "America/Lima"
    base_currency: str = "PEN"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Como se lee el correo: "imap" (contrasena de aplicacion) o "gmail" (OAuth).
    # Por defecto IMAP: es lo unico que se configura en dos minutos y no caduca.
    # Con OAuth, mientras la app este en "Testing" en Google Cloud Console, el
    # refresh token de gmail.readonly caduca a los 7 dias.
    email_backend: str = "imap"

    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""      # contrasena de APLICACION, no la de la cuenta
    imap_verificar_certificado: bool = True

    # Gmail API (alternativa a IMAP)
    gmail_credentials_file: str = str(SECRETS_DIR / "credentials.json")
    gmail_token_file: str = str(DATA_DIR / "token.json")
    gmail_lookback_days: int = 30
    sync_interval_minutes: int = 0
    # Dias que se conserva el TEXTO de los correos procesados. Pasado ese plazo
    # se vacia el cuerpo pero se conserva la ficha (remitente, asunto, fecha,
    # gmail_id): asi no se pierde la proteccion contra reprocesar el mismo
    # correo, y deja de haber un archivo de notificaciones bancarias en disco.
    # 0 = no borrar nunca.
    email_retention_days: int = 90

    # OAuth: debe coincidir EXACTAMENTE con un URI registrado en Google Console.
    oauth_redirect_uri: str = "http://localhost:5173/api/gmail/callback"
    # A donde vuelve el navegador despues de aceptar el consentimiento.
    app_base_url: str = "http://localhost:5173"

    # LLM opcional
    llm_fallback_enabled: bool = False
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"

    # Importar Excel: apagado por defecto. Hasta el 31/08/2026 la fuente de verdad
    # es el Excel y ya esta importado; desde el 01/09/2026 lo son los correos y los
    # registros manuales. Importar otro Excel con filas de agosto en adelante
    # duplicaria esos gastos, asi que la seccion solo se enciende a proposito.
    importar_excel_habilitado: bool = False

    # Copias de seguridad de la base. Cada cuantos dias como minimo (0 = nunca),
    # cuantas se conservan (0 = todas) y en que carpeta (vacio = <DATA_DIR>/respaldos).
    respaldo_cada_dias: int = Field(default=7, ge=0)
    respaldo_conservar: int = Field(default=8, ge=0)
    respaldo_dir: str = ""

    @field_validator("database_url")
    @classmethod
    def _sqlite_relativa_a_la_raiz(cls, valor: str) -> str:
        """Una ruta SQLite relativa se toma desde la raiz del proyecto, no desde la
        carpeta en la que se lanza el proceso.

        Con `sqlite:///./data/finanzas.db`, ejecutar un script desde backend/ abria
        (o creaba vacia) otra base en backend/data/, y sus respaldos iban alli.
        """
        prefijo = "sqlite:///"
        ruta = valor.removeprefix(prefijo) if valor.startswith(prefijo) else ""
        if ruta and not ruta.startswith((":memory:", "/", "\\")) and not Path(ruta).is_absolute():
            return prefijo + (PROJECT_DIR / ruta).resolve().as_posix()
        return valor

    @property
    def carpeta_respaldos(self) -> Path:
        return Path(self.respaldo_dir) if self.respaldo_dir else DATA_DIR / "respaldos"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def usa_imap(self) -> bool:
        return self.email_backend.lower() == "imap"

    @property
    def es_desarrollo(self) -> bool:
        """Con APP_ENV=prod se apaga la documentacion interactiva de la API.

        Es lo unico que cambia hoy. No es un interruptor de "modo seguro": la
        aplicacion sigue sin login en ambos casos.
        """
        return self.app_env.lower() not in {"prod", "produccion", "production"}


@lru_cache
def get_settings() -> Settings:
    # En el contenedor la carpeta ya existe y viene de un volumen; si no se puede
    # crear no es motivo para no arrancar.
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return Settings()


settings = get_settings()
