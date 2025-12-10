import requests
import base64

#DIGIKEY_CLIENT_ID = "AVdLiM9h03go6htYpkR1cMGZlQrQGPK3j95NLSYGA5oGNMdG"       # Canlı ortam Client ID'nizi buraya girin
#DIGIKEY_CLIENT_SECRET = "CH7BYGgt5qxmaFLLtfHKX9Cn4tQ9ZYxxI7z0FJKhyXOgq6HW0upFrxai2djT7gAZ"  # Canlı ortam Client Secret'ınızı buraya girin

DIGIKEY_CLIENT_ID     = "b2xazAjxKzJw0YaZsEvqPXqpj3Jse2k0XvTXkuoKDZBdMS2k"
DIGIKEY_CLIENT_SECRET = "URE2JoJbGkinq6qc38wQei4ZhNmFVB4IjHwcVeHTdcCy4E6PuYX5d08X17KlbMn5"

# 1) OAuth2 Token Alma
def get_access_token():
    url = "https://api.digikey.com/v1/oauth2/token"

    raw = f"{DIGIKEY_CLIENT_ID}:{DIGIKEY_CLIENT_SECRET}"
    encoded = base64.b64encode(raw.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {"grant_type": "client_credentials"}

    r = requests.post(url, headers=headers, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


# 2) Basit bir ürün araması yapıp limitleri çekiyoruz
def check_limits():
    token = get_access_token()

    url = "https://api.digikey.com/products/v4/search/keyword"

    headers = {
        "Content-Type": "application/json",
        "X-DIGIKEY-Client-Id": DIGIKEY_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    body = {
        "Keywords": "resistor",
        "RecordCount": 1
    }

    r = requests.post(url, json=body, headers=headers)

    # Limit bilgilerini HEADER’dan alıyoruz
    limit_daily        = r.headers.get("X-RateLimit-Limit")
    remaining_daily    = r.headers.get("X-RateLimit-Remaining")
    burst_limit        = r.headers.get("X-BurstLimit-Limit")
    burst_remaining    = r.headers.get("X-BurstLimit-Remaining")
    retry_after        = r.headers.get("Retry-After")

    print("📌 DigiKey API Limit Bilgisi")
    print("----------------------------")
    print("Günlük Limit        :", limit_daily)
    print("Günlük Kalan        :", remaining_daily)

    if retry_after:
        print("⚠ Retry-After:", retry_after, "saniye beklemen gerek")


check_limits()
