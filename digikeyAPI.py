from flask import Flask, redirect, request, jsonify, render_template
import requests
import time
import pandas as pd  # <-- YENİ EKLENDİ

app = Flask(__name__)

# 🔑 DigiKey Bilgileri
DIGIKEY_CLIENT_ID = "b2xazAjxKzJw0YaZsEvqPXqpj3Jse2k0XvTXkuoKDZBdMS2k"
DIGIKEY_CLIENT_SECRET = "URE2JoJbGkinq6qc38wQei4ZhNmFVB4IjHwcVeHTdcCy4E6PuYX5d08X17KlbMn5"

DIGIKEY_AUTH_URL_V4 = "https://api.digikey.com/v1/oauth2/authorize"
DIGIKEY_TOKEN_URL_V4 = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_PRODUCT_SEARCH_URL_V4 = "https://api.digikey.com/products/v4/search/keyword"
CALLBACK_URL = "https://127.0.0.1:5500/callback"

# 🔒 Token saklama
tokens = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": None
}

# 📊 Limit Bilgisi (Global)
API_LIMITS = {
    "daily_limit": "---",
    "remaining": "---"
}

# 🧩 HTML Template
HTML_TEMPLATE = "base.html"

# --- OAUTH FONKSİYONLARI (Aynı) ---
@app.route('/')
def home():
    auth_url = (
        f"{DIGIKEY_AUTH_URL_V4}?response_type=code&client_id={DIGIKEY_CLIENT_ID}&redirect_uri={CALLBACK_URL}"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get("code")
    if not code: return "Kod yok!", 400
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK_URL,
        "client_id": DIGIKEY_CLIENT_ID, "client_secret": DIGIKEY_CLIENT_SECRET
    }
    r = requests.post(DIGIKEY_TOKEN_URL_V4, headers=headers, data=data)
    if r.status_code != 200: return f"Hata: {r.text}", r.status_code
    t = r.json()
    tokens["access_token"], tokens["refresh_token"] = t["access_token"], t.get("refresh_token")
    tokens["expires_at"] = time.time() + t.get("expires_in", 3600)
    return redirect("/search")

def ensure_valid_token():
    if tokens["access_token"] and time.time() < tokens["expires_at"]: return tokens["access_token"]
    if not tokens["refresh_token"]: raise Exception("Token yok, tekrar giriş yapın.")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": DIGIKEY_CLIENT_ID, "client_secret": DIGIKEY_CLIENT_SECRET}
    r = requests.post(DIGIKEY_TOKEN_URL_V4, headers=headers, data=data)
    if r.status_code != 200: raise Exception("Yenileme hatası")
    t = r.json()
    tokens["access_token"], tokens["refresh_token"] = t["access_token"], t.get("refresh_token", tokens["refresh_token"])
    tokens["expires_at"] = time.time() + t.get("expires_in", 3600)
    return tokens["access_token"]

# --- 🛠 YARDIMCI FONKSİYON: TEK ÜRÜN ÇEKME ---
# Bu fonksiyonu hem normal aramada hem de BOM listesinde kullanacağız
def api_search_single_product(keyword, quantity=None):
    try:
        token = ensure_valid_token()
    except Exception as e:
        return {"error": str(e)}

    headers = {
        "Authorization": f"Bearer {token}",
        "X-DIGIKEY-Client-Id": DIGIKEY_CLIENT_ID,
        "X-DIGIKEY-Locale-Language": "en", "X-DIGIKEY-Locale-Currency": "USD", "X-DIGIKEY-Locale-Site": "US",
        "Content-Type": "application/json"
    }
    payload = {"Keywords": keyword, "RecordCount": 10} # BOM için ilk 10 sonuç yeterli
    
    try:
        response = requests.post(DIGIKEY_PRODUCT_SEARCH_URL_V4, headers=headers, json=payload)
    except Exception as e:
        return {"error": "Request Failed"}

    # Limitleri Güncelle
    if response.status_code == 200:
        API_LIMITS["daily_limit"] = response.headers.get("X-RateLimit-Limit", "---")
        API_LIMITS["remaining"] = response.headers.get("X-RateLimit-Remaining", "---")
    else:
        return {"error": f"API Hatası: {response.status_code}"}

    data = response.json()
    products = data.get("Products", []) or []
    
    if not products:
        return {"products": []}

    # Ürünleri işle (DisplayPricing mantığı)
    for prod in products:
        variations = prod.get("ProductVariations", []) or []
        
        # 1. En Uygun Kırılımı Bulma (Quantity'ye göre)
        best = None
        matched_breaks = []
        
        # Varyasyonları gez
        for var in variations:
            pricing = var.get("StandardPricing") or []
            if not pricing: continue
            
            # Adet kontrolü
            matched_for_var = None
            if quantity is not None:
                # Küçükten büyüğe sıralı varsayıyoruz veya sıralıyoruz
                pricing.sort(key=lambda x: int(x.get("BreakQuantity", 0)))
                for pr in pricing:
                    if int(pr.get("BreakQuantity", 0)) <= quantity:
                        matched_for_var = pr
                    else:
                        break
            
            if matched_for_var:
                pkg = (var.get("PackageType") or {}).get("Name", "")
                matched_breaks.append({
                    "BreakQuantity": matched_for_var.get("BreakQuantity"),
                    "UnitPrice": matched_for_var.get("UnitPrice"),
                    "PackageType": pkg,
                    "VariationDigiKeyPN": var.get("DigiKeyProductNumber")
                })

        # En iyi fiyatı seç (Quantity girildiyse)
        if matched_breaks:
            matched_breaks.sort(key=lambda x: (float(x["UnitPrice"]), -int(x["BreakQuantity"])))
            best = matched_breaks[0]
            prod["BestMatchedPriceBreak"] = best

        # 2. DisplayPricing (HTML Tablo için tam liste) Hazırlama
        display_pricing = []
        target_variation = None
        
        # A) Best match varsa onun listesini al
        if best:
            tgt_pn = best.get("VariationDigiKeyPN")
            for var in variations:
                if var.get("DigiKeyProductNumber") == tgt_pn:
                    target_variation = var
                    break
        # B) Yoksa MOQ en düşük olanı al (Cut Tape)
        else:
             sorted_vars = sorted(variations, key=lambda v: int(v.get("MinimumOrderQuantity", 999999)))
             if sorted_vars: target_variation = sorted_vars[0]

        if target_variation:
            display_pricing = target_variation.get("StandardPricing", [])
        
        prod["DisplayPricing"] = display_pricing

    return {"products": products}


# 🔍 NORMAL ARAMA
@app.route('/search')
def search():
    keyword = request.args.get("keyword", "")
    qty_raw = request.args.get("quantity", "").strip()
    quantity = int(qty_raw) if qty_raw.isdigit() and int(qty_raw) >= 1 else None

    if not keyword:
        return render_template("base.html", quantity=quantity, limits=API_LIMITS)

    result = api_search_single_product(keyword, quantity)
    
    if "error" in result:
        return render_template("base.html", error=result["error"], quantity=quantity, limits=API_LIMITS)

    products = result.get("products", [])
    return render_template("base.html", products=products, quantity=quantity, limits=API_LIMITS)


# 📂 BOM YÜKLEME (YENİ)
@app.route('/upload_bom', methods=['POST'])
def upload_bom():
    if 'bom_file' not in request.files:
        return "Dosya seçilmedi", 400
    
    file = request.files['bom_file']
    if file.filename == '': return "Dosya ismi boş", 400

    try:
        # Excel'i pandas ile oku
        df = pd.read_excel(file)
        
        # İlk sütunu "Parça Numarası" olarak varsayıyoruz. 
        # (İleride başlığa göre 'Part Number' sütununu arayan mantık eklenebilir)
        part_numbers = df.iloc[:, 0].dropna().astype(str).tolist()
        
        # Eğer 2. sütun varsa ve sayıysa onu "Quantity" (Adet) olarak alabiliriz
        quantities = []
        if df.shape[1] > 1:
            quantities = df.iloc[:, 1].fillna(0).tolist()
        
        bom_results = []
        
        # Döngü ile her parça için API'ye sor
        for i, keyword in enumerate(part_numbers):
            qty = None
            if i < len(quantities):
                try:
                    q_val = int(quantities[i])
                    if q_val > 0: qty = q_val
                except:
                    pass
            
            # API Sorgusu
            # Not: Çok hızlı sorgu atıp ban yememek için minik bir uyku eklenebilir
            # time.sleep(0.1) 
            
            res = api_search_single_product(keyword, qty)
            products = res.get("products", [])
            
            # BOM mantığında, aranan kelimeye en uygun İLK ürünü listeye eklemek mantıklıdır.
            if products:
                # Bulunan ilk ürünü al, ama kullanıcıya hangi kelimeyi arattığımızı da hatırlatalım
                top_product = products[0]
                top_product["SearchedKeyword"] = keyword # HTML'de göstermek istersek diye
                bom_results.append(top_product)
            else:
                # Bulunamadıysa boş bir placeholder ekle veya pas geç
                pass

        return render_template("base.html", products=bom_results, quantity=None, limits=API_LIMITS)

    except Exception as e:
        return f"Excel işleme hatası: {str(e)}", 500


if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5500, debug=True, ssl_context=('localhost+1.pem', 'localhost+1-key.pem'))