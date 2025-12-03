from flask import Flask, redirect, request, jsonify, render_template
import requests
import time

app = Flask(__name__)

# 🔑 DigiKey Bilgileri
DIGIKEY_CLIENT_ID = "b2xazAjxKzJw0YaZsEvqPXqpj3Jse2k0XvTXkuoKDZBdMS2k"       # Canlı ortam Client ID'nizi buraya girin
DIGIKEY_CLIENT_SECRET = "URE2JoJbGkinq6qc38wQei4ZhNmFVB4IjHwcVeHTdcCy4E6PuYX5d08X17KlbMn5"  # Canlı ortam Client Secret'ınızı buraya girin

DIGIKEY_AUTH_URL_V4 = "https://api.digikey.com/v1/oauth2/authorize"
DIGIKEY_TOKEN_URL_V4 = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_PRODUCT_SEARCH_URL_V4 = "https://api.digikey.com/products/v4/search/keyword"
CALLBACK_URL = "https://127.0.0.1:8080/callback"  # Canlı ortam için geçerli callback URL'inizi buraya girin

# 🔒 Token saklama
tokens = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": None
}

# 🧩 HTML Template
HTML_TEMPLATE = """
base.html
"""

# 🧭 OAuth başlatma
@app.route('/')
def home():
    auth_url = (
        f"{DIGIKEY_AUTH_URL_V4}"
        f"?response_type=code"
        f"&client_id={DIGIKEY_CLIENT_ID}"
        f"&redirect_uri={CALLBACK_URL}"
    )
    return redirect(auth_url)

# 🎟️ Callback
@app.route('/callback')
def callback():
    code = request.args.get("code")
    if not code:
        return "Yetkilendirme kodu alınamadı!", 400

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CALLBACK_URL,
        "client_id": DIGIKEY_CLIENT_ID,
        "client_secret": DIGIKEY_CLIENT_SECRET
    }

    response = requests.post(DIGIKEY_TOKEN_URL_V4, headers=headers, data=data)
    if response.status_code != 200:
        return f"Token alınamadı: {response.text}", response.status_code

    token_data = response.json()
    tokens["access_token"] = token_data["access_token"]
    tokens["refresh_token"] = token_data.get("refresh_token")
    tokens["expires_at"] = time.time() + token_data.get("expires_in", 3600)

    return redirect("/search")


# 🔁 Token yenileme
def ensure_valid_token():
    if tokens["access_token"] and time.time() < tokens["expires_at"]:
        return tokens["access_token"]

    if not tokens["refresh_token"]:
        raise Exception("Token süresi doldu, yeniden giriş yapın (/).")

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": DIGIKEY_CLIENT_ID,
        "client_secret": DIGIKEY_CLIENT_SECRET
    }

    response = requests.post(DIGIKEY_TOKEN_URL_V4, headers=headers, data=data)
    if response.status_code != 200:
        raise Exception(f"Token yenileme başarısız: {response.text}")

    token_json = response.json()
    tokens["access_token"] = token_json["access_token"]
    tokens["refresh_token"] = token_json.get("refresh_token", tokens["refresh_token"])
    tokens["expires_at"] = time.time() + token_json.get("expires_in", 3600)
    return tokens["access_token"]


# 🔍 Ürün arama
@app.route('/search')
def search():
    keyword = request.args.get("keyword", None)
    qty_raw = request.args.get("quantity", "").strip() # quantity parse (search fonksiyonunun başında)
    quantity = None
    if qty_raw:
        try:
            qtmp = int(qty_raw)
            if qtmp >= 1:
                quantity = qtmp
        except ValueError:
            quantity = None

    if not keyword:
        return render_template("base.html", quantity=quantity)

    try:
        access_token = ensure_valid_token()
    except Exception as e:
        return render_template("base.html", error=str(e), quantity=quantity)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-DIGIKEY-Client-Id": DIGIKEY_CLIENT_ID,
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": "USD",
        "X-DIGIKEY-Locale-Site": "US",
        "Content-Type": "application/json"
    }

    payload = {"Keywords": keyword, "RecordCount": 50}  # daha fazla sonuç isterseniz RecordCount'u artırın
    response = requests.post(DIGIKEY_PRODUCT_SEARCH_URL_V4, headers=headers, json=payload)

    if response.status_code != 200:
        return render_template(
            "base.html", error=f"API Hatası: {response.text}", quantity=quantity
        )

    index = 0
    data = response.json()
    products = data.get("Products", []) or []
    #print(f"Arama Sonuçları: {products[0]}")  # Konsola ilk ürünü yazdır
    for prod in products:
        matched_breaks = []  # will hold dicts: { "BreakQuantity":..., "UnitPrice":..., "TotalPrice":..., "PackageType":... } # tüm varyasyonlardan girilen adete uyan kırılımlar
        variations = prod.get("ProductVariations", []) or []
        for var in variations:
            pricing = var.get("StandardPricing") or []
            if not pricing:
                continue
            # sort by BreakQuantity ascending (safeguard if API returns unsorted)
            # güvenli sıralama (BreakQuantity int'e çevrilebiliyorsa)
            def _bq_key(x):
                try:
                    return int(x.get("BreakQuantity", 0))
                except Exception:
                    return 0
            pricing_sorted = sorted(pricing, key=_bq_key)

            try:
                pricing_sorted = sorted(pricing, key=lambda x: int(x.get("BreakQuantity", 0)))
            except Exception:
                pricing_sorted = pricing[:]

            # find the last break whose BreakQuantity <= quantity
            # quantity verilmişse en son <= quantity olan kırılımı al
            matched_for_var = None
            if quantity is not None:
                for pr in pricing_sorted:
                    try:
                        bq = int(pr.get("BreakQuantity", 0))
                    except Exception:
                        bq = 0
                    if bq <= quantity:
                        matched_for_var = pr
                    else:
                        break

            # if quantity is None we do not mark anything (user requested normal search)
            if matched_for_var  :
                pkg_name = (var.get("PackageType") or {}).get("Name", "Bilinmiyor")
                # replace Digi-Reel® -> Re-Reel®
                # Digi-Reel dönüşümü (çeşitli varyantları kapsar)

                if isinstance(pkg_name, str) and "Digi-Reel" in pkg_name:
                    pkg_name = pkg_name.replace("Digi-Reel", "Re-Reel")
                matched_breaks.append({
                    "BreakQuantity": matched_for_var.get("BreakQuantity"),
                    "UnitPrice": matched_for_var.get("UnitPrice"),
                    "TotalPrice": matched_for_var.get("TotalPrice"),
                    "PackageType": pkg_name,
                    "VariationDigiKeyPN": var.get("DigiKeyProductNumber")
                })

        # attach matched list to product for template use
        # Ürün seviyesinde en uygun kırılımı seç
        best = None
    if matched_breaks:
        # Öncelik: en düşük UnitPrice; eşit UnitPrice ise en yüksek BreakQuantity
        def _unit_price_key(x):
            try:
                return float(x.get("UnitPrice", float('inf')))
            except Exception:
                return float('inf')
        # sort by UnitPrice asc, BreakQuantity desc
        matched_sorted = sorted(
            matched_breaks,
            key=lambda x: (_unit_price_key(x), -int(x.get("BreakQuantity") or 0))
        )
        best = matched_sorted[0]
        prod["BestMatchedPriceBreak"] = best
        prod["MatchedPriceBreaks"] = matched_breaks

    if not products:
        print("Products listesi boş veya bulunamadı.")
        return

    if index < 0 or index >= len(products):
        print(f"Geçersiz index: {index}. Toplam ürün sayısı: {len(products)}")
        return
    
    product = products[index]
    desc = product.get("Description", {})
    mfg  = product.get("Manufacturer", {})
    status = product.get("ProductStatus", {})
    series = product.get("Series", {})

    print("=== ÜRÜN ÖZETİ ===")
    print(f"Ürün Adı               : {desc.get('ProductDescription', 'Bilgi yok')}")
    print(f"Detaylı Açıklama       : {desc.get('DetailedDescription', 'Bilgi yok')}")
    print(f"Üretici                : {mfg.get('Name', 'Bilgi yok')}")
    print(f"Üretici Parça No       : {product.get('ManufacturerProductNumber', 'Bilgi yok')}")
    print(f"Birim Fiyat            : {product.get('UnitPrice', 'Bilgi yok')} USD")
    print(f"Seri                   : {series.get('Name', '-')}")
    print(f"Stok (genel)           : {product.get('QuantityAvailable', 'Bilgi yok')}")
    print(f"Durum                  : {status.get('Status', 'Bilgi yok')}")
    print(f"Ürün URL               : {product.get('ProductUrl', 'Bilgi yok')}")
    print(f"Datasheet URL          : {product.get('DatasheetUrl', 'Bilgi yok')}")
    print(f"Fotoğraf URL           : {product.get('PhotoUrl', 'Bilgi yok')}")
    print(f"Teslim Süresi          : {product.get('ManufacturerLeadWeeks', 'Bilgi yok')} Hafta")
    print()

    # Sınıflandırmalar
    cls = product.get("Classifications", {})
    if cls:
        print("=== UYUMLULUK / SINIFLANDIRMALAR ===")
        print(f"RoHS                   : {cls.get('RohsStatus', 'Bilgi yok')}")
        print(f"REACH                  : {cls.get('ReachStatus', 'Bilgi yok')}")
        print(f"MSL                    : {cls.get('MoistureSensitivityLevel', 'Bilgi yok')}")
        print(f"ECCN                   : {cls.get('ExportControlClassNumber', 'Bilgi yok')}")
        print(f"HTS Code               : {cls.get('HtsusCode', 'Bilgi yok')}")
        print()

    # Temel parametreler (örnek: Interface, Standards, Supply Voltage, Temperature, vb.)
    params = product.get("Parameters", [])
    if params:
        print("=== TEKNİK PARAMETRELER ===")
        # Sık kullanılan bazı parametreleri filtreleyelim
        whitelist = {
            "Protocol",
            "Function",
            "Interface",
            "Standards",
            "Voltage - Supply",
            "Current - Supply",
            "Operating Temperature",
            "Package / Case",
            "Supplier Device Package",
        }
        for p in params:
            name = p.get("ParameterText")
            value = p.get("ValueText")
            if name in whitelist:
                print(f"{name:23}: {value}")
        print()

    # Varyasyonlar ve fiyat kırılımları
    variations = product.get("ProductVariations", [])
    if variations:
        print("=== PAKET TİPİNE GÖRE FİYAT KIRILIMLARI ===")
        for var in variations:
            pkg_name = (var.get("PackageType", {}) or {}).get("Name", "Bilinmiyor")
            dk_pn = var.get("DigiKeyProductNumber", "Bilinmiyor")
            min_qty = var.get("MinimumOrderQuantity", "Bilgi yok")
            qty_avail = var.get("QuantityAvailableforPackageType", "Bilgi yok")
            supplier_name = (var.get("Supplier", {}) or {}).get("Name", "Bilinmiyor")
            digi_reel_fee = var.get("DigiReelFee", 0.0)

            print(f"- Paket Tipi           : {pkg_name}")
            print(f"  DigiKey PN           : {dk_pn}")
            print(f"  Tedarikçi            : {supplier_name}")
            print(f"  Min Sipariş          : {min_qty}")
            print(f"  Stok (paket tipi)    : {qty_avail}")
            if digi_reel_fee:
                print(f"  Digi-Reel Ücreti     : {digi_reel_fee} USD")

            pricing = var.get("StandardPricing", [])
            if pricing:
                print("  Fiyatlar (BreakQuantity -> UnitPrice USD | TotalPrice USD):")
                for price in pricing:
                    bq = price.get("BreakQuantity", "N/A")
                    up = price.get("UnitPrice", "N/A")
                    tp = price.get("TotalPrice", "N/A")
                    print(f"    {bq:>6} -> {up} | {tp}")
            print()

    # Diğer isimler ve serbest metin alanlar
    other_names = product.get("OtherNames", [])
    if other_names:
        print("=== DİĞER İSİMLER ===")
        for n in other_names:
            print(f"- {n}")
        print()

    print("=== ÖZET BİTTİ ===")


    return render_template("base.html" , products=products, product=(products[0] if products else None), quantity=quantity)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, ssl_context="adhoc")