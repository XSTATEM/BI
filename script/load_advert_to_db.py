import requests
import json

# Вставь ключи от одного из тестовых кабинетов
CLIENT_ID = "4394450"
API_KEY = "6d7c8a86-bb27-4ca9-b256-0135f11a88db"

def check_transactions():
    url = "https://api-seller.ozon.ru/v3/finance/transaction/list"
    
    headers = {
        "Client-Id": CLIENT_ID,
        "Api-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # Фильтры: указываем даты и тип транзакции (all = все)
    payload = {
        "filter": {
            "date": {
                "from": "2026-06-01T00:00:00.000Z",
                "to": "2026-06-04T23:59:59.000Z"
            },
            "transaction_type": "all"
        },
        "page": 1,
        "page_size": 50 # Для теста достаточно вытянуть 50 записей
    }

    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        data = response.json()
        # Выводим красивый JSON в консоль, чтобы изучить поля
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"Ошибка {response.status_code}: {response.text}")

if __name__ == "__main__":
    check_transactions()