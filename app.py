from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import requests
from flask import Flask, jsonify, request, send_from_directory
import threading
import time
import json
import os
import sys
import re

# إضافة المسارات
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Proto', 'compiled'))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Utilities'))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Configuration'))

app = Flask(__name__)

# ==================== استيراد Protobuf ====================
import data_pb2
import uid_generator_pb2
import GetWishListItems_pb2
from google.protobuf.json_format import MessageToDict

from Utilities.until import encode_protobuf, decode_protobuf
from Configuration.APIConfiguration import RELEASEVERSION, DEBUG
from Account import get_garena_token, get_major_login
from InGame import get_player_personal_show, get_player_stats, search_account_by_keyword

# ==================== تكوين الصور ====================
ITEM_DATA_URL = "https://raw.githubusercontent.com/0xMe/ItemID2/main/assets/itemData.json"
IMAGE_BASE_URL = "https://raw.githubusercontent.com/0xMe/ff-resources/main/pngs/300x300/"

item_map = {}  # itemID -> icon filename

def load_item_data():
    """تحميل ملف itemData.json وبناء خريطة itemID -> icon"""
    global item_map
    try:
        resp = requests.get(ITEM_DATA_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for entry in data:
            item_id = str(entry.get("itemID"))
            icon = entry.get("icon")
            if item_id and icon:
                item_map[item_id] = icon
        print(f"✅ Loaded {len(item_map)} item mappings")
    except Exception as e:
        print(f"❌ Failed to load item data: {e}")

def get_image_url(item_id):
    """إرجاع رابط الصورة لعنصر معين"""
    if not item_id or item_id == 0:
        return None
    id_str = str(item_id)
    icon = item_map.get(id_str)
    if icon:
        return IMAGE_BASE_URL + icon + ".png"
    # Fallback: استخدم المعرف مباشرة مع .png
    return IMAGE_BASE_URL + id_str + ".png"

# تحميل بيانات العناصر عند بدء التشغيل
load_item_data()

# ==================== دالة فك تشفير الأسماء ====================
def decode_unicode_name(encoded_name):
    """فك تشفير الأسماء التي تحتوي على رموز Unicode"""
    if not encoded_name:
        return "Unknown"
    
    symbols = {
        '\uff33': 'S', '\uff28': 'H', '\u4e48': 'M', '\u2002': ' ',
        '\uff27': 'G', '\u3164': '', '\u2602': '', '\u2588': '█',
        '\u2580': '▀', '\u2591': '░', '\u2584': '▄', '\uff2f': 'O',
        '\uff34': 'T', '\u2004': ' ', '\uff21': 'A', '\uff24': 'D',
        '\u4e00': '', '\u3000': '',
    }
    
    result = encoded_name
    for old, new in symbols.items():
        result = result.replace(old, new)
    
    result = re.sub(r'[^\w\s\u0600-\u06FF\u4e00-\u9fff]', '', result)
    
    if result.strip():
        return result.strip()
    return "Unknown"

# ==================== تحميل بيانات الحسابات ====================
def load_accounts():
    config_path = os.path.join(os.path.dirname(__file__), 'AccountConfiguration.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Failed to load accounts: {e}")
        return {}

accounts = load_accounts()

# ==================== تخزين JWT ====================
jwt_cache = {}
jwt_lock = threading.Lock()

def get_jwt_token(region):
    with jwt_lock:
        if region in jwt_cache and jwt_cache[region].get('expiry', 0) > time.time():
            return jwt_cache[region]['token'], jwt_cache[region].get('serverUrl')
        
        if region not in accounts:
            print(f"❌ No credentials for {region}")
            return None, None
        
        creds = accounts[region]
        uid = creds.get('uid')
        password = creds.get('password')
        
        try:
            token_resp = get_garena_token(uid, password)
            if not token_resp or 'access_token' not in token_resp:
                return None, None
            
            major_resp = get_major_login(token_resp['access_token'], token_resp['open_id'])
            if not major_resp or 'token' not in major_resp:
                return None, None
            
            jwt_token = major_resp['token']
            server_url = major_resp.get('serverUrl', 'https://clientbp.ggblueshark.com')
            jwt_cache[region] = {
                'token': jwt_token, 
                'serverUrl': server_url,
                'expiry': time.time() + 300
            }
            print(f"✅ JWT for {region} obtained, serverUrl: {server_url}")
            return jwt_token, server_url
        except Exception as e:
            print(f"❌ Login error for {region}: {e}")
            return None, None

# ==================== دوال الطلبات الأساسية ====================
def encrypt_aes(hex_data):
    key = b"Yg&tc%DEuh6%Zc^8"
    iv = b"6oyZDr22E3ychjM%"
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(bytes.fromhex(hex_data), AES.block_size)
    return binascii.hexlify(cipher.encrypt(padded)).decode()

def send_request(endpoint, payload_hex, region, max_retries=3):
    """إرسال طلب مع إعادة المحاولة عند 429 (rate limit)"""
    for attempt in range(max_retries):
        try:
            token, server_url = get_jwt_token(region)
            if not token:
                raise Exception(f"No token for {region}")
            
            base_url = server_url.rstrip('/')
            url = f"{base_url}/{endpoint}"
            
            headers = {
                'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
                'Connection': 'Keep-Alive',
                'Expect': '100-continue',
                'Authorization': f'Bearer {token}',
                'X-Unity-Version': '2018.4.11f1',
                'X-GA': 'v1 1',
                'ReleaseVersion': 'OB52',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            data = bytes.fromhex(payload_hex)
            response = requests.post(url, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            return response.content.hex()
        except Exception as e:
            if '429' in str(e) and attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"⚠️ Rate limited for {region} on {endpoint}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise

def create_player_request(uid):
    message = uid_generator_pb2.uid_generator()
    message.saturn_ = int(uid)
    message.garena = 1
    return binascii.hexlify(message.SerializeToString()).decode()

def create_wishlist_request(uid):
    req = GetWishListItems_pb2.CSGetWishListItemsReq()
    req.account_id = int(uid)
    return binascii.hexlify(req.SerializeToString()).decode()

# ==================== نقاط النهاية الأساسية ====================

@app.route('/')
def dashboard():
    """خدمة لوحة التحكم (dashboard.html)"""
    return send_from_directory('.', 'dashboard.html')

@app.route('/api/health', methods=['GET'])
def health():
    """فحص صحة السيرفر"""
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.route('/accinfo', methods=['GET'])
def get_player_info():
    """معلومات اللاعب الأساسية (نقطة قديمة)"""
    try:
        uid = request.args.get('uid')
        region = request.args.get('region', 'default').upper()
        if not uid or not uid.isdigit():
            return jsonify({"error": "Invalid UID"}), 400
        
        hex_data = create_player_request(uid)
        encrypted = encrypt_aes(hex_data)
        response_hex = send_request("GetPlayerPersonalShow", encrypted, region)
        
        message = data_pb2.AccountPersonalShowInfo()
        message.ParseFromString(bytes.fromhex(response_hex))
        return jsonify(MessageToDict(message))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/account', methods=['GET'])
def api_v1_account():
    """معلومات الحساب (API v1) مع صور الأفاتار والراية"""
    try:
        region = request.args.get('region', '').upper()
        uid = request.args.get('uid')
        if not region or not uid or not uid.isdigit():
            return jsonify({"error": "Missing region or uid"}), 400
        
        hex_data = create_player_request(uid)
        encrypted = encrypt_aes(hex_data)
        response_hex = send_request("GetPlayerPersonalShow", encrypted, region)
        
        message = data_pb2.AccountPersonalShowInfo()
        message.ParseFromString(bytes.fromhex(response_hex))
        result = MessageToDict(message)
        
        basic = result.get('basicInfo', {})
        # إضافة روابط الصور
        avatar_id = basic.get('headPic', 0)
        banner_id = basic.get('bannerId', 0)
        basic['avatarImageUrl'] = get_image_url(avatar_id)
        basic['bannerImageUrl'] = get_image_url(banner_id)
        
        return jsonify({
            "basicInfo": basic,
            "profileInfo": result.get('profileInfo', {}),
            "clanBasicInfo": result.get('clanBasicInfo', {}),
            "petInfo": result.get('petInfo', {}),
            "socialInfo": result.get('socialInfo', {})
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/wishlistitems', methods=['GET'])
def api_v1_wishlist():
    """قائمة الرغبات مع صور العناصر"""
    try:
        region = request.args.get('region', '').upper()
        uid = request.args.get('uid')
        if not region or not uid or not uid.isdigit():
            return jsonify({"error": "Missing region or uid"}), 400
        
        hex_data = create_wishlist_request(uid)
        encrypted = encrypt_aes(hex_data)
        response_hex = send_request("GetWishListItems", encrypted, region)
        
        res = GetWishListItems_pb2.CSGetWishListItemsRes()
        res.ParseFromString(bytes.fromhex(response_hex))
        items = []
        for item in res.items:
            items.append({
                "itemId": item.item_id,
                "releaseTime": str(item.release_time),
                "imageUrl": get_image_url(item.item_id)
            })
        return jsonify({"items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/craftlandProfile', methods=['GET'])
def api_v1_craftland_profile():
    """معلومات Craftland للاعب (البروفايل، الخرائط، الإحصائيات)"""
    try:
        region = request.args.get('region', '').upper()
        uid = request.args.get('uid')
        if not region or not uid or not uid.isdigit():
            return jsonify({"error": "Missing region or uid"}), 400
        
        # 1. جلب اسم اللاعب من الحساب الأساسي (مع إعادة محاولة عند 429)
        player_name = "Unknown"
        player_level = 0
        player_rank_br = 0
        player_likes = 0
        try:
            hex_data = create_player_request(uid)
            encrypted = encrypt_aes(hex_data)
            response_hex = send_request("GetPlayerPersonalShow", encrypted, region)
            message = data_pb2.AccountPersonalShowInfo()
            message.ParseFromString(bytes.fromhex(response_hex))
            result = MessageToDict(message)
            basic = result.get('basicInfo', {})
            player_name = decode_unicode_name(basic.get('nickname', 'Unknown'))
            player_level = basic.get('level', 0)
            player_rank_br = basic.get('rank', 0)
            player_likes = basic.get('liked', 0)
        except Exception as e:
            print(f"Failed to get player info: {e}")
        
        # 2. جلب بيانات Craftland
        hex_data = create_player_request(uid)
        encrypted = encrypt_aes(hex_data)
        response_hex = send_request("GetWorkshopAuthorInfo", encrypted, region)
        raw_bytes = bytes.fromhex(response_hex)
        
        # استخراج الخرائط والإحصائيات
        maps = []
        basic_info_raw = None
        
        i = 0
        while i < len(raw_bytes):
            tag = raw_bytes[i]
            field_num = tag >> 3
            wire_type = tag & 0x07
            i += 1
            
            if wire_type == 2:  # length-delimited
                length = 0
                shift = 0
                while i < len(raw_bytes):
                    b = raw_bytes[i]
                    length |= (b & 0x7F) << shift
                    i += 1
                    shift += 7
                    if not (b & 0x80):
                        break
                value = raw_bytes[i:i+length]
                i += length
                if field_num == 1:
                    try:
                        map_str = value.decode('utf-8', errors='ignore')
                        map_str = map_str.replace('\x00', '').replace('\x01', '').replace('\x07', '')
                        # استخراج اسم الخريطة
                        match = re.search(r'[A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\s\_\-]+', map_str)
                        if match:
                            map_name = match.group().strip()
                            if len(map_name) > 2 and map_name not in maps:
                                maps.append(map_name)
                        elif len(map_str) > 3 and map_str not in maps:
                            maps.append(map_str[:50])
                    except:
                        pass
                elif field_num == 3:
                    basic_info_raw = value
        
        # استخراج الإحصائيات
        rank = 0
        total_plays = 0
        subscriptions_count = 0
        
        if basic_info_raw and len(basic_info_raw) > 0:
            j = 0
            while j < len(basic_info_raw):
                tag = basic_info_raw[j]
                sub_field = tag >> 3
                sub_wire = tag & 0x07
                j += 1
                
                if sub_wire == 0:
                    value = 0
                    shift = 0
                    while j < len(basic_info_raw):
                        b = basic_info_raw[j]
                        value |= (b & 0x7F) << shift
                        j += 1
                        shift += 7
                        if not (b & 0x80):
                            break
                    if sub_field == 1:
                        rank = value
                    elif sub_field == 3:
                        total_plays = value
                    elif sub_field == 7:
                        subscriptions_count = value
        
        return jsonify({
            "status": "success",
            "uid": uid,
            "region": region,
            "profile": {
                "author_name": player_name,
                "level": player_level,
                "rank_br": player_rank_br,
                "likes": player_likes,
                "craftland_rank": rank,
                "total_plays": total_plays,
                "subscriptions_count": subscriptions_count,
                "maps_count": len(maps),
                "maps": maps[:20]
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Free Fire API Server Starting...")
    print("=" * 60)
    print("📡 Available endpoints:")
    print("   🔹 /                            (Dashboard)")
    print("   🔹 /accinfo?uid=123&region=ME")
    print("   🔹 /api/v1/account?region=ME&uid=123 (includes avatar/banner images)")
    print("   🔹 /api/v1/wishlistitems?region=ME&uid=123 (includes item images)")
    print("   🔹 /api/v1/craftlandProfile?region=ME&uid=123")
    print("   🔹 /api/health")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5552, debug=True)