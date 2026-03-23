import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
import requests
import time
import json

BOT_TOKEN = "توكن_البوت_هنا"  # ضع توكن البوت هنا
API_BASE = "http://localhost:5552"  # تأكد من صحة العنوان

bot = telebot.TeleBot(BOT_TOKEN)
user_server = {}

def get_api(endpoint, params):
    url = f"{API_BASE}{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def format_number(n):
    return f"{n:,}"

def format_date(ts):
    if not ts:
        return "غير معروف"
    return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))

@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🇮🇳 IND", callback_data="IND"),
        InlineKeyboardButton("🇧🇷 BR", callback_data="BR"),
        InlineKeyboardButton("🇲🇾 ME", callback_data="ME")
    )
    bot.send_message(message.chat.id, "مرحباً! اختر السيرفر:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["IND", "BR", "ME"])
def server_selected(call):
    user_server[call.from_user.id] = call.data
    bot.edit_message_text(f"✅ تم اختيار السيرفر: {call.data}\nالرجاء إرسال UID الآن:",
                          call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: message.text and message.text.isdigit())
def handle_uid(message):
    uid = message.text.strip()
    user_id = message.from_user.id
    server = user_server.get(user_id)
    if not server:
        bot.reply_to(message, "❌ يرجى اختيار السيرفر أولاً عبر /start")
        return

    bot.reply_to(message, "⏳ جاري جلب المعلومات...")

    # جلب معلومات الحساب
    account = get_api("/api/v1/account", {"region": server, "uid": uid})
    if "error" in account:
        bot.send_message(message.chat.id, f"⚠️ خطأ: {account['error']}")
        return

    basic = account.get("basicInfo", {})
    clan = account.get("clanBasicInfo", {})
    pet = account.get("petInfo", {})
    social = account.get("socialInfo", {})

    profile_text = (
        f"👤 **{basic.get('nickname', 'غير معروف')}**\n"
        f"🆔 **UID:** `{uid}`\n"
        f"🌍 **السيرفر:** {server}\n"
        f"⭐ **المستوى:** {basic.get('level', 0)}\n"
        f"🏆 **رتبة BR:** {basic.get('rank', 0)}\n"
        f"🎯 **رتبة CS:** {basic.get('csRank', 0)}\n"
        f"❤️ **الإعجابات:** {format_number(basic.get('liked', 0))}\n"
        f"📅 **تاريخ الإنشاء:** {format_date(basic.get('createAt'))}\n"
        f"🕒 **آخر دخول:** {format_date(basic.get('lastLoginAt'))}\n"
    )
    if clan.get("clanName"):
        profile_text += f"🏅 **الجيلد:** {clan['clanName']} (المستوى {clan.get('clanLevel', 0)})\n"
    if pet.get("petName"):
        profile_text += f"🐾 **الحيوان الأليف:** {pet['petName']} (مستوى {pet.get('level', 0)})\n"
    if social.get("socialHighlight"):
        profile_text += f"📢 **الحالة:** {social['socialHighlight'][:100]}"

    # إرسال صورة الأفاتار والراية إذا وجدتا
    media_group = []
    avatar_url = basic.get('avatarImageUrl')
    banner_url = basic.get('bannerImageUrl')
    if avatar_url:
        media_group.append(InputMediaPhoto(avatar_url, caption=profile_text, parse_mode="Markdown"))
    if banner_url:
        media_group.append(InputMediaPhoto(banner_url))
    if media_group:
        try:
            bot.send_media_group(message.chat.id, media_group)
        except:
            bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")

    # قائمة الرغبات مع الصور
    wish = get_api("/api/v1/wishlistitems", {"region": server, "uid": uid})
    items = wish.get("items", [])
    if items:
        wish_text = f"🎁 **قائمة الرغبات ({len(items)}):**"
        bot.send_message(message.chat.id, wish_text, parse_mode="Markdown")
        # إرسال أول 10 عناصر كصور (يمكن تعديل العدد)
        for item in items[:10]:
            if item.get('imageUrl'):
                try:
                    bot.send_photo(message.chat.id, item['imageUrl'], caption=f"🔹 `{item['itemId']}`", parse_mode="Markdown")
                except:
                    bot.send_message(message.chat.id, f"🔹 `{item['itemId']}`", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, f"🔹 `{item['itemId']}`", parse_mode="Markdown")
        if len(items) > 10:
            bot.send_message(message.chat.id, f"... و {len(items)-10} عنصر آخر", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "🎁 لا توجد عناصر في قائمة الرغبات", parse_mode="Markdown")

    # Craftland
    craft = get_api("/api/v1/craftlandProfile", {"region": server, "uid": uid})
    craft_profile = craft.get("profile", {})
    craft_text = (
        f"🎨 **Craftland**\n"
        f"✍️ **الصانع:** {craft_profile.get('author_name', 'غير معروف')}\n"
        f"🏆 **الترتيب:** {format_number(craft_profile.get('craftland_rank', 0))}\n"
        f"🎮 **إجمالي اللعب:** {format_number(craft_profile.get('total_plays', 0))}\n"
        f"👥 **المشتركين:** {format_number(craft_profile.get('subscriptions_count', 0))}\n"
        f"🗺️ **الخرائط المنشورة:** {craft_profile.get('maps_count', 0)}"
    )
    bot.send_message(message.chat.id, craft_text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def unknown(message):
    bot.reply_to(message, "⚠️ الرجاء إرسال UID رقمي صحيح، أو استخدم /start لاختيار السيرفر.")

if __name__ == "__main__":
    print("🤖 Bot is running...")
    bot.polling(none_stop=True)