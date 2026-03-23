import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from Account import get_garena_token, get_major_login
import json

# تحميل بيانات الحساب
with open('AccountConfiguration.json', 'r') as f:
    accounts = json.load(f)

# اختبار ME region
me_account = accounts.get('ME', {})
uid = me_account.get('uid')
password = me_account.get('password')

print(f"Testing login for ME region...")
print(f"UID: {uid}")
print(f"Password: {password[:20]}...")

if uid and password:
    token_resp = get_garena_token(uid, password)
    print(f"Token response: {token_resp}")
    
    if token_resp and 'access_token' in token_resp:
        major_resp = get_major_login(token_resp['access_token'], token_resp['open_id'])
        print(f"Major login response: {major_resp}")
    else:
        print("Failed to get access token")
else:
    print("No credentials for ME region")