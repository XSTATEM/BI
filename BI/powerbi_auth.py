"""
Аутентификация в Power BI REST API через device code flow (MSAL).

Пароль пользователя нигде не запрашивается и не хранится: при первом запуске
скрипт выведет ссылку и одноразовый код, которые нужно ввести в браузере
под своим Power BI Pro аккаунтом. После входа MSAL кэширует токен в файле
token_cache.bin (в этой же папке), и повторные запуски не потребуют
повторного входа, пока токен валиден / кэш не удалён.

ДИАГНОСТИЧЕСКИЙ РЕЖИМ: сейчас используется client_id Azure CLI
(04b07795-8ddb-461a-bbee-02f9e1bf7b46) вместо "Power BI PowerShell"
(1aea3f97-...), чтобы проверить, блокирует ли тенант echips.ru вообще
любые не-consented multi-tenant приложения, или проблема была именно
в "Power BI PowerShell". См. комментарий у CLIENT_ID ниже с трактовкой
возможных исходов запуска.
"""

import atexit
import os

import msal

# ДИАГНОСТИЧЕСКИЙ ЗАПУСК: временно используем client_id Azure CLI
# (04b07795-8ddb-461a-bbee-02f9e1bf7b46) — это первоклассное multi-tenant
# приложение Microsoft, service principal которого уже существует практически
# в любом тенанте, где кто-либо хоть раз пользовался az login / Az PowerShell.
# Цель — понять природу прошлой ошибки AADSTS700016 на "Power BI PowerShell"
# (1aea3f97-2a73-45f9-b425-a1f0bffe4b70):
#   - если СНОВА AADSTS700016 -> тенант echips.ru политикой блокирует любые
#     не-consented multi-tenant приложения целиком, дело не в конкретном id;
#   - если другая ошибка (например AADSTS65001 "consent required" или
#     AADSTS500011 "resource не найден для этого приложения", т.к. Power BI
#     Service API обычно не входит в pre-authorized scopes у Azure CLI) —
#     значит проблема была именно в id "Power BI PowerShell", а не в тенанте.
# ВАЖНО: это временный диагностический client_id, не для постоянного
# использования — Azure CLI не имеет официальных прав на Power BI Service API.
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

# Ссылка для администратора тенанта echips.ru на случай, если понадобится
# admin consent для финального (не диагностического) client_id.
ADMIN_CONSENT_URL = (
    "https://login.microsoftonline.com/ff1ab603-f598-49df-a87b-8c59814dd423"
    f"/adminconsent?client_id={CLIENT_ID}"
)

# Tenant id организации echips.ru (получен через /.well-known/openid-configuration).
# ВАЖНО: "common"/"organizations" ломали device code flow для этого клиента
# с ошибкой AADSTS50059 "No tenant-identifying information found" —
# нужен конкретный tenant id.
AUTHORITY = "https://login.microsoftonline.com/ff1ab603-f598-49df-a87b-8c59814dd423"

SCOPES = ["https://analysis.windows.net/powerbi/api/.default"]

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_cache.bin")


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache.deserialize(f.read())

    def _save():
        if cache.has_state_changed:
            with open(CACHE_FILE, "w", encoding="utf-8") as fh:
                fh.write(cache.serialize())

    atexit.register(_save)
    return cache


def get_access_token() -> str:
    """Возвращает валидный access token, запрашивая вход через device code при необходимости."""
    cache = _load_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Не удалось начать device code flow: {flow}")
        print(flow["message"])  # содержит ссылку + код для входа
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(f"Ошибка аутентификации: {result.get('error_description', result)}")

    return result["access_token"]


if __name__ == "__main__":
    token = get_access_token()
    print("Токен получен, длина:", len(token))
