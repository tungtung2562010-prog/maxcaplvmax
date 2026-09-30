import os, html, requests, re, asyncio, io
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
ADMIN_ID=int(os.getenv("TELEGRAM_ADMIN_ID","0") or 0)
BACKEND=os.getenv("BACKEND_URL","http://127.0.0.1:8080").rstrip("/")
ADMIN_SECRET=os.getenv("ADMIN_SECRET","")
TZ=ZoneInfo("Asia/Ho_Chi_Minh")
DAILY_REPORT_HOUR=int(os.getenv("DAILY_REPORT_HOUR","0") or 0)
DAILY_REPORT_MINUTE=int(os.getenv("DAILY_REPORT_MINUTE","5") or 5)

def allowed(update):
    u=update.effective_user
    return bool(u and ADMIN_ID and u.id==ADMIN_ID)

def req(method,path,**kw):
    h=kw.pop("headers",{})
    h["X-Admin-Secret"]=ADMIN_SECRET
    r=requests.request(method,BACKEND+path,headers=h,timeout=15,**kw)
    try:d=r.json()
    except Exception:d={"detail":r.text[:500]}
    if not r.ok:raise RuntimeError(d.get("detail",f"HTTP {r.status_code}"))
    return d

def fmt_money(v):
    try:return f"{int(v):,}".replace(",",".")+"đ"
    except Exception:return str(v)

def fmt_time(v):
    if not v:return "-"
    try:return datetime.fromisoformat(v).astimezone(TZ).strftime("%H:%M:%S %d/%m/%Y")
    except Exception:return str(v)

def plan_buttons():
    try: plans=[p for p in req("GET","/api/admin/plans")["plans"] if p["enabled"]]
    except Exception: plans=[]
    rows=[]
    for i in range(0,len(plans),2):
        row=[]
        for p in plans[i:i+2]:
            row.append(InlineKeyboardButton(f"🔑 {p['days']}D · {fmt_money(p['price_vnd'])}",callback_data=f"newp:{p['id']}"))
        rows.append(row)
    return rows

def menu():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("🏠 Tổng quan",callback_data="home"),InlineKeyboardButton("👤 Tài khoản",callback_data="accounts")],
      [InlineKeyboardButton("💳 Nạp tiền",callback_data="deposits"),InlineKeyboardButton("🔔 LIVE",callback_data="live")],
      [InlineKeyboardButton("🔑 Key",callback_data="list"),InlineKeyboardButton("💰 Gói key",callback_data="plans")],
      [InlineKeyboardButton("🌐 Game / API",callback_data="gamelinks"),InlineKeyboardButton("📣 Thông báo",callback_data="notice")],
      [InlineKeyboardButton("🎨 Giao diện",callback_data="ui"),InlineKeyboardButton("⚙️ Cấu hình",callback_data="settings")],
      [InlineKeyboardButton("📊 Báo cáo 24H",callback_data="dailyreport"),InlineKeyboardButton("🔄 Làm mới",callback_data="home")],
    ])

async def render_panel(update:Update,text,reply_markup=None,parse_mode=None):
    """Edit the current dashboard for callbacks; commands create only one output message."""
    text=(text or "-")[:4090]
    markup=reply_markup or menu()
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text,reply_markup=markup,parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            return update.callback_query.message
        except BadRequest as e:
            if "Message is not modified" in str(e):
                return update.callback_query.message
        except Exception:
            pass
        return await update.callback_query.message.reply_text(
            text,reply_markup=markup,parse_mode=parse_mode,
            disable_web_page_preview=True
        )
    if update.message:
        return await update.message.reply_text(
            text,reply_markup=markup,parse_mode=parse_mode,
            disable_web_page_preview=True
        )

async def dashboard_text():
    try:
        d=await asyncio.to_thread(req,"GET","/api/admin/stats")
        s=await asyncio.to_thread(req,"GET","/api/admin/settings")
        cfg=s.get("settings",{})
        return (
          "╭─ 🛡 TAIXIUTOOL ADMIN ─╮\n"
          "│ 🟢 SERVER ONLINE   🔔 LIVE AUTO: ON\n"
          "╰────────────────────────╯\n\n"
          f"🔑 KEY     {d.get('active_keys',0)} hoạt động / {d.get('total_keys',0)} tổng\n"
          f"📱 DEVICE  {d.get('devices',0)} đã kích hoạt\n"
          f"✅ TODAY   {d.get('activations_today',0)} kích hoạt\n"
          f"⚡ FREE    {d.get('free_today',0)} hoàn tất hôm nay\n\n"
          f"📡 POLL    LC79 {cfg.get('lc79_poll_seconds','11')}s · SUNWIN {cfg.get('sunwin_poll_seconds','12')}s\n"
          f"📜 HISTORY {cfg.get('history_limit','60')} phiên\n"
          f"🕶 NỀN     {d.get('background_active',0)} lượt đang theo dõi\n"
          f"👤 ACCOUNT {d.get('accounts_total',0)} tài khoản · 💳 {d.get('deposit_pending',0)} nạp chờ duyệt\n"
          f"💰 WALLET  {fmt_money(d.get('wallet_total',0))} tổng số dư\n\n"
          "🔔 Người mới truy cập + key kích hoạt mới được báo tự động.\n"
          "AUTO luôn bật · không có nút tắt · chống trùng 24h."
        )
    except Exception as e:
        return "🛡 TAIXIUTOOL ADMIN\n\n⚠️ Backend: "+str(e)

def ua_label(ua,os_name=""):
    u=ua or ""
    if "CriOS" in u: br="Chrome"
    elif "FxiOS" in u: br="Firefox"
    elif "EdgiOS" in u or "Edg/" in u: br="Edge"
    elif "Safari" in u and "Chrome" not in u: br="Safari"
    elif "Chrome" in u: br="Chrome"
    else: br="Browser"
    return f"{os_name or 'Thiết bị'} · {br}"

def event_line(e):
    t=fmt_time(e.get("created_at"))
    if t!="-": t=t.split(" ")[0]
    dev=(e.get("device_hash") or "-")[:10].upper()
    who=ua_label(e.get("user_agent"),e.get("os_name"))
    ip=e.get("ip_address") or "-"
    if e.get("event")=="key_first_activation":
        label=e.get("key_label") or f"KEY #{e.get('key_id') or '-'}"
        return f"🔑 {t} · {label}\n   {who} · {ip} · {dev}"
    return f"🌐 {t} · USER MỚI\n   {who} · {ip} · {dev}"

def live_text(ctx):
    items=list(ctx.application.bot_data.get("live_items") or [])[-6:]
    body="\n\n".join(event_line(x) for x in reversed(items)) if items else "Chưa có sự kiện mới từ lúc bot khởi động."
    return (
      "╭─ 🔔 LIVE AUTO · ALWAYS ON ─╮\n"
      "│ Tự báo user mới + key kích hoạt mới\n"
      "╰────────────────────────╯\n\n"+body+
      "\n\n🧹 Tin LIVE cũ tự xóa khi có cập nhật mới."
    )

async def push_live_alert(app):
    text=live_text(type("Ctx",(),{"application":app})())
    old=app.bot_data.get("live_message_id")
    if old:
        try: await app.bot.delete_message(chat_id=ADMIN_ID,message_id=old)
        except Exception: pass
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛡 Dashboard",callback_data="home"),InlineKeyboardButton("🔄 LIVE",callback_data="live")]])
    m=await app.bot.send_message(chat_id=ADMIN_ID,text=text,reply_markup=kb,disable_web_page_preview=True)
    app.bot_data["live_message_id"]=m.message_id

async def live_worker(app):
    # Start at the newest event to avoid flooding old history after a restart.
    try:
        d=await asyncio.to_thread(req,"GET","/api/admin/events?after_id=0&limit=1")
        app.bot_data["live_cursor"]=int(d.get("latest_id") or 0)
    except Exception:
        app.bot_data["live_cursor"]=0
    app.bot_data.setdefault("live_items",[])
    while True:
        try:
            cur=int(app.bot_data.get("live_cursor") or 0)
            d=await asyncio.to_thread(req,"GET",f"/api/admin/events?after_id={cur}&limit=50")
            events=d.get("events") or []
            if events:
                buf=list(app.bot_data.get("live_items") or [])
                buf.extend(events)
                app.bot_data["live_items"]=buf[-12:]
                app.bot_data["live_cursor"]=max(cur,max(int(x.get("id") or 0) for x in events))
                await push_live_alert(app)
            else:
                app.bot_data["live_cursor"]=max(cur,int(d.get("latest_id") or cur))
        except Exception:
            pass
        await asyncio.sleep(4)


def report_text_payload(d):
    game=str(d.get('game','')).upper();sm=d.get('summary') or {};br=d.get('breakdown') or {}
    lines=[f"TAIXIUTOOL DATASET 24H · {game}",
           f"Period UTC: {d.get('period_start','')} -> {d.get('period_end','')}",
           f"Rows: {sm.get('rows',0)} | Settled: {sm.get('settled',0)} | Win: {sm.get('wins',0)} | Loss: {sm.get('losses',0)} | Skip: {sm.get('skips',0)} | Accuracy: {sm.get('accuracy',0)}%",
           ""]
    for t,x in br.items():
        lines.append(f"[{t}] rows={x.get('rows',0)} settled={x.get('settled',0)} win={x.get('wins',0)} loss={x.get('losses',0)} accuracy={x.get('accuracy',0)}%")
    lines += ["","time_utc | table | session | predict | actual | correct | confidence | reason"]
    for r in d.get('rows') or []:
        side=r.get('side') or 'SKIP';actual=r.get('actual') or '-';correct='-' if r.get('correct') is None else ('1' if int(r.get('correct') or 0)==1 else '0')
        reason=str(r.get('reason') or '').replace('\n',' ').replace('|','/').strip()
        lines.append(f"{r.get('created_at','')} | {r.get('table_name','')} | {r.get('session_id','')} | {side} | {actual} | {correct} | {r.get('confidence',0)} | {reason}")
    return '\n'.join(lines)+'\n'

async def send_daily_reports(app,manual=False):
    today=datetime.now(TZ).strftime('%Y-%m-%d')
    sent=[]
    for game in ('lc79','sunwin','max789'):
        d=await asyncio.to_thread(req,'GET',f'/api/admin/daily-report?game={game}&hours=24')
        raw=report_text_payload(d).encode('utf-8')
        bio=io.BytesIO(raw);bio.name=f'{game}_24h_{today}.txt'
        sm=d.get('summary') or {}
        caption=(f"📊 {game.upper()} · 24H\n"
                 f"Phiên: {sm.get('rows',0)} · Đã chốt: {sm.get('settled',0)}\n"
                 f"Đúng: {sm.get('wins',0)} · Sai: {sm.get('losses',0)} · Tỷ lệ: {sm.get('accuracy',0)}%")
        await app.bot.send_document(ADMIN_ID,document=bio,caption=caption)
        sent.append(game)
    if not manual:
        await asyncio.to_thread(req,'POST','/api/admin/daily-report-state',json={'last_sent':today})
    return sent

async def daily_report_worker(app):
    while True:
        try:
            now=datetime.now(TZ);today=now.strftime('%Y-%m-%d')
            state=await asyncio.to_thread(req,'GET','/api/admin/daily-report-state')
            due=(now.hour>DAILY_REPORT_HOUR or (now.hour==DAILY_REPORT_HOUR and now.minute>=DAILY_REPORT_MINUTE))
            if due and state.get('last_sent')!=today:
                await send_daily_reports(app,manual=False)
        except Exception:
            pass
        await asyncio.sleep(60)

async def daily_report_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    m=await update.message.reply_text('⏳ Đang tạo 3 báo cáo 24H...')
    try:
        await send_daily_reports(ctx.application,manual=True)
        await m.edit_text('✅ Đã gửi 3 file: LC79 / SUNWIN / MAX789.')
    except Exception as e:
        await m.edit_text('⚠️ '+str(e)[:350])

async def post_init(app):
    app.create_task(live_worker(app),name="taixiutool-live-auto")
    app.create_task(account_live_worker(app),name="taixiutool-account-live")
    app.create_task(daily_report_worker(app),name="taixiutool-daily-report")
    app.create_task(report48_worker(app),name="taixiutool-48h-report")

async def auto_delete_admin_command(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update) or not update.message:return
    await asyncio.sleep(.65)
    try: await update.message.delete()
    except Exception: pass

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    await render_panel(update,await dashboard_text())

async def plans(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    data=req("GET","/api/admin/plans")["plans"]
    if not data: txt="Chưa có gói key."
    else:
        rows=["💰 GÓI KEY / BẢNG GIÁ\n"]
        for p in data:
            state="🟢" if p["enabled"] else "⚫"
            rows.append(f"{state} ID {p['id']} · {p['days']} ngày · {fmt_money(p['price_vnd'])} · {p['max_devices']} thiết bị · {p['name']}")
        rows += ["",
                 "Thêm: /addplan DAYS PRICE [DEVICES]",
                 "Sửa: /editplan ID DAYS PRICE [DEVICES]",
                 "Ẩn gói: /delplan ID"]
        txt="\n".join(rows)
    await render_panel(update,txt[:3900])

async def price(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    await plans(update,ctx)

async def create_key_plan(update:Update,ctx:ContextTypes.DEFAULT_TYPE,plan_id:int):
    if not allowed(update):return
    d=req("POST","/api/admin/keys",json={"plan_id":plan_id})
    txt=(f"✅ TẠO KEY THÀNH CÔNG\n\n"
         f"🔐 Key: <code>{html.escape(d['key'])}</code>\n"
         f"📦 Gói: {html.escape(d.get('label') or '-')}\n"
         f"⏳ Thời hạn: {d['days']} ngày\n"
         f"💰 Giá: {fmt_money(d['price_vnd'])}\n"
         f"📱 Thiết bị: {d['max_devices']}\n"
         f"🕐 Tạo lúc: {datetime.now(TZ).strftime('%H:%M:%S %d/%m/%Y')}\n"
         f"⌛ Hết hạn: {fmt_time(d['expires_at'])}")
    await render_panel(update,txt,parse_mode="HTML")

async def list_keys(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    data=req("GET","/api/admin/keys")["keys"][:40]
    if not data:txt="Chưa có key."
    else:
        rows=[]
        for k in data:
            icon="🟢" if k["enabled"] else "🔴"
            days=k.get("days") if k.get("days") is not None else "-"
            price=fmt_money(k.get("price_vnd") or 0)
            rows.append(f"{icon} ID {k['id']} · {days}D · {price} · {k['devices']}/{k['max_devices']} máy · {k['label'] or '-'}")
        txt="📋 DANH SÁCH KEY\n\n"+"\n".join(rows)+"\n\nDùng /key ID để xem chi tiết."
    await render_panel(update,txt[:3900])

async def key_detail(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Dùng: /key ID\nVí dụ: /key 12");return
    kid=int(ctx.args[0]);d=req("GET",f"/api/admin/keys/{kid}");k=d["key"]
    lines=[
        f"🔎 KEY ID {kid}",
        f"🏷️ Nhãn: {k.get('label') or '-'}",
        f"Trạng thái: {'🟢 hoạt động' if k['enabled'] else '🔴 đã khóa'}",
        f"⏳ Số ngày: {k.get('days') if k.get('days') is not None else '-'}",
        f"💰 Giá: {fmt_money(k.get('price_vnd') or 0)}",
        f"🕐 Tạo: {fmt_time(k['created_at'])}",
        f"⌛ Hết hạn: {fmt_time(k['expires_at'])}",
        f"📱 Thiết bị: {len(d['devices'])}/{k['max_devices']}",
    ]
    for i,x in enumerate(d["devices"],1):
        lines += ["",f"📱 THIẾT BỊ {i}",
                  f"• ID: {x['device_id']}",
                  f"• HĐH: {x.get('os_name') or '-'}",
                  f"• Trình duyệt: {x.get('browser_name') or '-'}",
                  f"• IP public: {x.get('ip_address') or '-'}",
                  f"• Vị trí theo IP: {x.get('location') or '-'}",
                  f"• Lần đầu: {fmt_time(x.get('first_seen'))}",
                  f"• Lần cuối: {fmt_time(x.get('last_seen'))}"]
        if x.get("gps_lat") is not None and x.get("gps_lon") is not None:
            lines += [f"• GPS đã đồng ý: {x['gps_lat']:.6f}, {x['gps_lon']:.6f}",
                      f"• Độ chính xác: ~{round(float(x.get('gps_accuracy') or 0))}m",
                      f"• Cập nhật GPS: {fmt_time(x.get('gps_updated_at'))}",
                      f"• Maps: https://maps.google.com/?q={x['gps_lat']},{x['gps_lon']}"]
        else:
            lines += ["• GPS: chưa chia sẻ / đã từ chối"]
        ua=(x.get("user_agent") or "").strip()
        if ua: lines.append(f"• User-Agent: {ua[:180]}")
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Khóa key",callback_data=f"disable:{kid}"),
         InlineKeyboardButton("♻️ Reset thiết bị",callback_data=f"reset:{kid}")]
    ])
    await update.message.reply_text("\n".join(lines)[:3900],reply_markup=kb)

async def stats(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    d=req("GET","/api/admin/stats")
    gs=d.get("game_stats") or {}
    def gline(k,label):
        x=gs.get(k) or {};return f"{label}: {x.get('wins',0)}/{x.get('settled',0)} · {x.get('rate',0)}%"
    txt=("📊 THỐNG KÊ TAIXIUTOOL\n\n"
         f"🔑 Tổng key: {d['total_keys']}\n🟢 Key hoạt động: {d['active_keys']}\n"
         f"📱 Thiết bị đã kích hoạt: {d['devices']}\n⚡ FREE hoàn tất hôm nay: {d['free_today']}\n"
         f"1️⃣ Mã 1 xác minh: {d.get('free_step1',0)}\n2️⃣ Mã 2 xác minh: {d.get('free_step2',0)}\n"
         f"✅ Kích hoạt hôm nay: {d['activations_today']}\n🧾 Sự kiện hôm nay: {d['events_today']}\n"
         f"🕶 Theo dõi nền: {d.get('background_active',0)}\n\n"
         "🎮 KẾT QUẢ ĐÃ CHỐT\n"
         +gline("hu","◆ LC79 HŨ")+"\n"+gline("md5","◆ LC79 MD5")+"\n"+gline("sunwin","👑 SUNWIN"))
    await render_panel(update,txt)

async def users(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    rows=req("GET","/api/admin/users")["users"][:15]
    txt="👥 THIẾT BỊ GẦN ĐÂY\n\n" if rows else "Chưa có thiết bị."
    for x in rows:
        txt+=f"📱 {x['device_hash']} · key {x['key_id']} · {x.get('os_name') or '-'} · {x.get('browser_name') or '-'}\n"
        txt+=f"IP: {x.get('ip_address') or '-'}\nVị trí IP: {x.get('location') or '-'}\n"
        if x.get("gps_lat") is not None and x.get("gps_lon") is not None:
            txt+=f"GPS: {x['gps_lat']:.5f},{x['gps_lon']:.5f} (~{round(float(x.get('gps_accuracy') or 0))}m)\n"
        else: txt+="GPS: chưa chia sẻ\n"
        txt+=f"Last: {fmt_time(x.get('last_seen'))}\n\n"
    await render_panel(update,txt[:3900])

async def free_stats(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    rows=req("GET","/api/admin/free")["claims"][:20]
    txt="⚡ FREE LINK4M 2 BƯỚC GẦN ĐÂY\n\n" if rows else "Chưa có lượt FREE."
    for x in rows:
        if x.get("completed_at"):
            state="✅ HOÀN TẤT · ĐÃ CẤP KEY"
        elif x.get("step2_verified_at"):
            state="✅ MÃ 2 ĐÃ XÁC MINH"
        elif x.get("step1_verified_at"):
            state="2️⃣ ĐANG CHỜ MÃ 2"
        else:
            state="1️⃣ ĐANG CHỜ MÃ 1"
        txt+=f"#{x['id']} · {state}\n"
        txt+=f"Device: {x.get('device_hash') or '-'} · Step {min(int(x.get('current_step') or 1),2)}/2\n"
        txt+=f"IP tạo: {x.get('request_ip') or '-'}\n"
        if x.get('step1_ip'):txt+=f"IP Link #1: {x.get('step1_ip')}\n"
        if x.get('step2_ip'):txt+=f"IP Link #2: {x.get('step2_ip')}\n"
        txt+=f"Tạo: {fmt_time(x.get('created_at'))}\n"
        if x.get('completed_at'):txt+=f"Hoàn tất: {fmt_time(x.get('completed_at'))} · key ID {x.get('key_id') or '-'}\n"
        txt+="\n"
    await render_panel(update,txt[:3900])

async def settings_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    s=req("GET","/api/admin/settings").get("settings",{})
    mode=lambda v:{"1":"BẢO THỦ","2":"CÂN BẰNG","3":"AGGRESSIVE"}.get(str(v),str(v))
    txt=("⚙️ CẤU HÌNH TAIXIUTOOL\n\n"
         f"⚡ FREE: {s.get('free_key_hours','1')} giờ · {s.get('free_daily_limit','2')} lượt/ngày · IP limit {s.get('free_ip_daily_limit','6')}\n"
         f"🧩 CAPTCHA: {s.get('captcha_ttl_seconds','300')}s · mã Link: {s.get('free_step_ttl_minutes','12')} phút\n"
         f"📡 Poll: LC79 {s.get('lc79_poll_seconds','3')}s · SUNWIN {s.get('sunwin_poll_seconds','4')}s · MAX789 {s.get('max789_poll_seconds','3')}s\n"
         f"📜 History: {s.get('history_limit','60')} dòng · refresh {s.get('history_refresh_seconds','24')}s\n"
         f"◆ Phân tích LC79: {mode(s.get('lc79_algo_mode','2'))}\n👑 Phân tích SUNWIN: {mode(s.get('sunwin_algo_mode','2'))}\n🐉 Phân tích MAX789: {mode(s.get('max789_algo_mode','3'))}\n"
         f"📍 Hỏi GPS: {'BẬT' if s.get('gps_prompt','1')=='1' else 'TẮT'}\n"
         f"💬 Admin: {s.get('admin_contact','@huanhoahong11111')}\n"
         f"◆ LC79: {s.get('lc79_game_url','https://play.lc79.bet/')}\n"
         f"👑 SUNWIN: {s.get('sunwin_game_url','https://sunwin.villas')}\n🐉 MAX789: {s.get('max789_game_url','https://play.max789a.vin/')}\n\n"
         "Lệnh: /gamelinks · /setgame · /apiurls · /setapi · /setfree · /setpoll · /sethistory · /setalgo · /setcontact · /setgps")
    await render_panel(update,txt[:3900])


def clean_http_url(raw):
    u=(raw or "").strip().strip("<>\"'“”‘’")
    if not re.match(r"^https?://",u,re.I):
        u="https://"+u
    try:
        p=urlsplit(u)
        if p.scheme.lower() not in ("http","https") or not p.netloc:
            return None
        # Spaces are never valid inside the URL token passed to the command.
        if any(ch.isspace() for ch in u):
            return None
        return urlunsplit((p.scheme.lower(),p.netloc,p.path or "",p.query,p.fragment))
    except Exception:
        return None

async def gamelinks(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    s=req("GET","/api/admin/settings").get("settings",{})
    lc=s.get("lc79_game_url","https://play.lc79.bet/")
    sw=s.get("sunwin_game_url","https://sunwin.villas")
    mx=s.get("max789_game_url","https://play.max789a.vin/")
    api=s.get("sunwin_api_url","") or "Chưa cấu hình"
    mxhu=s.get("max789_hu_api_url","") or "Chưa cấu hình"
    mxmd5=s.get("max789_md5_api_url","") or "Chưa cấu hình"
    txt=("🌐 GAME / API CENTER\n\n"
         f"◆ LC79\n{lc}\n\n"
         f"👑 SUNWIN\n{sw}\n\n"
         f"🐉 MAX789\n{mx}\n\n"
         f"🔌 SUNWIN API\n{api}\n\n"
         f"🐉 MAX789 HŨ API\n{mxhu}\n\n"
         f"🐉 MAX789 MD5 API\n{mxmd5}\n\n"
         "Đổi nhanh:\n"
         "/setgame lc79 URL\n/setgame sunwin URL\n/setgame max789 URL\n"
         "/setapi sunwin URL\n/setapi max789_hu URL\n/setapi max789_md5 URL")
    await render_panel(update,txt[:3900])

async def setgame(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /setgame lc79 URL · /setgame sunwin URL · /setgame max789 URL")
        return
    game=ctx.args[0].strip().lower()
    key={"lc79":"lc79_game_url","sunwin":"sunwin_game_url","max789":"max789_game_url"}.get(game)
    if not key:
        await update.message.reply_text("GAME chỉ nhận: lc79, sunwin hoặc max789");return
    url=clean_http_url(ctx.args[1])
    if not url:
        await update.message.reply_text("URL không hợp lệ. Hãy gửi URL http/https đầy đủ.");return
    req("PATCH","/api/admin/settings",json={key:url})
    await update.message.reply_text(f"✅ Đã đổi link {game.upper()}\n{url}\n\nReload web để áp dụng.")

async def apiurls(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    s=req("GET","/api/admin/settings").get("settings",{})
    u=s.get("sunwin_api_url","")
    hu=s.get("max789_hu_api_url","")
    md5=s.get("max789_md5_api_url","")
    await update.message.reply_text("🔌 API TAIXIUTOOL\n\n👑 SUNWIN API\n"+(u or "Chưa cấu hình")+"\n\n🐉 MAX789 HŨ API\n"+(hu or "Chưa cấu hình")+"\n\n🐉 MAX789 MD5 API\n"+(md5 or "Chưa cấu hình")+"\n\nĐổi bằng /setapi sunwin|max789_hu|max789_md5 URL")

async def setapi(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /setapi sunwin|max789_hu|max789_md5 URL");return
    target=ctx.args[0].lower()
    key={"sunwin":"sunwin_api_url","max789_hu":"max789_hu_api_url","max789_md5":"max789_md5_api_url","maxhu":"max789_hu_api_url","maxmd5":"max789_md5_api_url"}.get(target)
    if not key:
        await update.message.reply_text("API chỉ nhận: sunwin, max789_hu, max789_md5");return
    url=clean_http_url(ctx.args[1])
    if not url:
        await update.message.reply_text("API URL không hợp lệ.");return
    req("PATCH","/api/admin/settings",json={key:url})
    await update.message.reply_text(f"✅ Đã đổi {target.upper()} API\n{url}\nBackend dùng từ lần poll tiếp theo.")

async def setfree(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:h=max(1,min(72,int(ctx.args[0])));limit=max(1,min(20,int(ctx.args[1])));ip=max(1,min(100,int(ctx.args[2]))) if len(ctx.args)>2 else max(6,limit*3)
    except Exception:await update.message.reply_text("Dùng: /setfree HOURS DAILY_LIMIT [IP_LIMIT]\nVí dụ: /setfree 1 2 6");return
    req("PATCH","/api/admin/settings",json={"free_key_hours":h,"free_daily_limit":limit,"free_ip_daily_limit":ip})
    await update.message.reply_text(f"✅ FREE = {h} giờ · {limit} lượt/ngày · IP limit {ip}")

async def setpoll(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:
        a=max(2,min(60,int(ctx.args[0])));b=max(2,min(60,int(ctx.args[1])));c=max(2,min(60,int(ctx.args[2]))) if len(ctx.args)>2 else a
    except Exception:await update.message.reply_text("Dùng: /setpoll LC79 SUNWIN MAX789\nVí dụ: /setpoll 3 4 3");return
    req("PATCH","/api/admin/settings",json={"lc79_poll_seconds":a,"sunwin_poll_seconds":b,"max789_poll_seconds":c})
    await update.message.reply_text(f"✅ Poll LC79 {a}s · SUNWIN {b}s · MAX789 {c}s")

async def sethistory(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:limit=max(20,min(200,int(ctx.args[0])));sec=max(10,min(120,int(ctx.args[1])))
    except Exception:await update.message.reply_text("Dùng: /sethistory LIMIT REFRESH_SECONDS\nVí dụ: /sethistory 60 24");return
    req("PATCH","/api/admin/settings",json={"history_limit":limit,"history_refresh_seconds":sec})
    await update.message.reply_text(f"✅ History {limit} dòng · refresh {sec}s")

async def setalgo(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:game=ctx.args[0].lower();mode=max(1,min(3,int(ctx.args[1])));key={"lc79":"lc79_algo_mode","sunwin":"sunwin_algo_mode","max789":"max789_algo_mode"}[game]
    except Exception:await update.message.reply_text("Dùng: /setalgo lc79|sunwin|max789 1|2|3\n1=Bảo thủ · 2=Cân bằng · 3=Ít bỏ qua");return
    req("PATCH","/api/admin/settings",json={key:mode})
    await update.message.reply_text(f"✅ {game.upper()} algorithm mode = {mode}")

async def setcontact(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args:await update.message.reply_text("Dùng: /setcontact @username");return
    val=ctx.args[0].strip();val=val if val.startswith('@') else '@'+val
    req("PATCH","/api/admin/settings",json={"admin_contact":val})
    await update.message.reply_text(f"✅ Admin mua key: {val}")

async def setgps(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or ctx.args[0].lower() not in ("on","off"):await update.message.reply_text("Dùng: /setgps on hoặc /setgps off");return
    v=1 if ctx.args[0].lower()=="on" else 0;req("PATCH","/api/admin/settings",json={"gps_prompt":v})
    await update.message.reply_text("✅ Hỏi quyền GPS: "+("BẬT" if v else "TẮT"))

async def enable_plan(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or not ctx.args[0].isdigit():await update.message.reply_text("Dùng: /enableplan ID");return
    pid=int(ctx.args[0]);req("POST",f"/api/admin/plans/{pid}/enable");await update.message.reply_text(f"✅ Đã bật gói ID {pid}.")

async def enable_key(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or not ctx.args[0].isdigit():await update.message.reply_text("Dùng: /enablekey ID");return
    kid=int(ctx.args[0]);req("POST",f"/api/admin/keys/{kid}/enable");await update.message.reply_text(f"✅ Đã bật key ID {kid}.")

async def reset_key(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or not ctx.args[0].isdigit():await update.message.reply_text("Dùng: /resetkey ID");return
    kid=int(ctx.args[0]);req("DELETE",f"/api/admin/keys/{kid}/devices");await update.message.reply_text(f"♻️ Đã reset thiết bị key ID {kid}.")

async def custom_key(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:days=int(ctx.args[0]);price=int(ctx.args[1]);devices=int(ctx.args[2]);label=" ".join(ctx.args[3:]) or f"CUSTOM {days}D"
    except Exception:await update.message.reply_text("Dùng: /customkey DAYS PRICE DEVICES [LABEL]\nVí dụ: /customkey 30 50000 2 VIP30");return
    d=req("POST","/api/admin/keys",json={"days":days,"price_vnd":price,"max_devices":devices,"label":label})
    await update.message.reply_text(f"✅ CUSTOM KEY\n🔐 <code>{html.escape(d['key'])}</code>\n⏳ {days} ngày · 💰 {fmt_money(price)} · 📱 {devices} máy",parse_mode="HTML")


async def accounts_panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    data=req("GET","/api/admin/accounts").get("accounts",[])
    rows=["👤 TÀI KHOẢN WEB\n"]
    for a in data[:30]:
        rows.append(f"#{a['id']} · {a['username']} · 💰 {fmt_money(a['balance_vnd'])} · 🔑 {a.get('key_count',0)}")
    if not data:rows.append("Chưa có tài khoản.")
    rows += ["","💰 CHỈNH SỐ DƯ THEO USERNAME","/congtien USERNAME SOTIEN","/trutien USERNAME SOTIEN","/balance USERNAME +/-SOTIEN"]
    await render_panel(update,"\n".join(rows)[:3900])

async def deposits_panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    data=req("GET","/api/admin/deposits").get("deposits",[])
    pending=[x for x in data if x.get('status')=='sent']
    rows=["💳 YÊU CẦU NẠP TIỀN\n"]
    kb=[]
    for d in pending[:12]:
        rows.append(f"🟡 #{d['id']} · @{d['username']} · {fmt_money(d['amount'])}\n   ND: {d['transfer_content']} · Mã {d['request_code']}")
        kb.append([InlineKeyboardButton(f"✅ Duyệt #{d['id']}",callback_data=f"depok:{d['id']}"),InlineKeyboardButton("❌ Từ chối",callback_data=f"depno:{d['id']}")])
    if not pending:rows.append("Không có giao dịch đang chờ duyệt.")
    kb.append([InlineKeyboardButton("← Dashboard",callback_data="home")])
    await render_panel(update,"\n\n".join(rows)[:3900],InlineKeyboardMarkup(kb))

async def notice_panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    d=req("GET","/api/admin/settings").get("settings",{})
    txt=("📣 THÔNG BÁO WEB\n\n"+(d.get('site_announcement') or '(đang trống)')+
         "\n\nĐổi bằng:\n/announce NỘI DUNG\n\n🏦 Bank: "+(d.get('bank_code') or '-')+" · "+(d.get('bank_account') or '-')+
         "\nĐổi bank: /setbank BANKCODE SOTK TENCHUTK")
    await render_panel(update,txt[:3900])

async def announce_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    txt=" ".join(ctx.args).strip()
    if not txt:
        await update.message.reply_text("Dùng: /announce nội dung thông báo trên web");return
    req("PATCH","/api/admin/portal-settings",json={"site_announcement":txt})
    await update.message.reply_text("✅ Đã cập nhật thông báo web.")

async def setbank_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<3:
        await update.message.reply_text("Dùng: /setbank BANKCODE SOTK TEN CHU TK\nVí dụ: /setbank MB 0123456789 NGUYEN VAN A");return
    code=ctx.args[0];acc=ctx.args[1];name=" ".join(ctx.args[2:])
    req("PATCH","/api/admin/portal-settings",json={"bank_code":code,"bank_account":acc,"bank_account_name":name})
    await update.message.reply_text(f"✅ Đã cấu hình QR: {code} · {acc} · {name}")

async def _adjust_balance_by_username(update:Update,username:str,delta:int,note:str):
    username=(username or "").strip().lower()
    accs=req("GET","/api/admin/accounts").get("accounts",[])
    a=next((x for x in accs if str(x.get('username','')).lower()==username),None)
    if not a:
        await update.message.reply_text("❌ Không tìm thấy tài khoản: "+username);return
    d=req("POST",f"/api/admin/accounts/{a['id']}/balance",json={"delta":int(delta),"note":note})
    sign="+" if int(d.get('delta',delta))>=0 else ""
    await update.message.reply_text(
        f"💰 @{username}\n"
        f"Thay đổi: {sign}{fmt_money(int(d.get('delta',delta)))}\n"
        f"Số dư mới: {fmt_money(d['balance_vnd'])}"
    )

async def balance_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /balance USERNAME +/-SOTIEN\nVí dụ: /balance htung 50000 hoặc /balance htung -20000");return
    try:delta=int(ctx.args[1].replace('.','').replace(',',''))
    except Exception:
        await update.message.reply_text("Số tiền không hợp lệ.");return
    await _adjust_balance_by_username(update,ctx.args[0],delta,"Telegram admin /balance")

async def congtien_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /congtien USERNAME SOTIEN\nVí dụ: /congtien htung 50000");return
    try:amount=abs(int(ctx.args[1].replace('.','').replace(',','')))
    except Exception:
        await update.message.reply_text("Số tiền không hợp lệ.");return
    await _adjust_balance_by_username(update,ctx.args[0],amount,"Telegram admin /congtien")

async def trutien_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /trutien USERNAME SOTIEN\nVí dụ: /trutien htung 20000");return
    try:amount=abs(int(ctx.args[1].replace('.','').replace(',','')))
    except Exception:
        await update.message.reply_text("Số tiền không hợp lệ.");return
    await _adjust_balance_by_username(update,ctx.args[0],-amount,"Telegram admin /trutien")


async def ui_panel(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    s=req("GET","/api/admin/settings").get("settings",{})
    txt=("🎨 GIAO DIỆN / PORTAL\n\n"
         f"🏷 Brand: {s.get('brand','TAIXIUTOOL')}\n"
         f"📝 Tagline: {s.get('tagline','-')}\n"
         f"🎨 Màu: {s.get('ui_primary','#49e8ff')} · {s.get('ui_secondary','#766bff')} · {s.get('ui_accent','#ff66b8')}\n"
         f"🔤 Font: {s.get('ui_font_scale','100')}% · Compact: {'ON' if s.get('ui_compact','1')=='1' else 'OFF'}\n"
         f"✈ Telegram nổi: {'ON' if s.get('telegram_floating','1')=='1' else 'OFF'}\n"
         f"🛠 Bảo trì: {'ON' if s.get('maintenance_mode','0')=='1' else 'OFF'}\n\n"
         "Lệnh nhanh:\n"
         "/setui primary #49E8FF\n/setui secondary #766BFF\n/setui accent #FF66B8\n/setui surface #07111B\n/setui font 95\n/setui compact on|off\n"
         "/settext brand|tagline|start|login|support|maintenance NỘI_DUNG\n"
         "/setnotice title|body|telegram|zalo|phone|remind|on|off VALUE\n"
         "/toggle lc79|sunwin|max789|telegram|maintenance|gps on|off\n"
         "/setlimits DEVICES IP\n/setdeposit MIN MAX TTL_MINUTES\n/allsettings")
    await render_panel(update,txt[:3900])

async def setui_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /setui primary|secondary|accent|surface|font|compact VALUE");return
    fld=ctx.args[0].lower();raw=ctx.args[1]
    key={"primary":"ui_primary","secondary":"ui_secondary","accent":"ui_accent","surface":"ui_surface","font":"ui_font_scale","compact":"ui_compact"}.get(fld)
    if not key:
        await update.message.reply_text("Field: primary, secondary, accent, surface, font, compact");return
    if fld=="compact":raw=1 if raw.lower() in ("on","1","true","yes") else 0
    elif fld=="font":
        try:raw=max(85,min(115,int(raw)))
        except Exception:await update.message.reply_text("Font 85..115");return
    req("PATCH","/api/admin/settings",json={key:raw})
    await update.message.reply_text(f"✅ {key} = {raw}")

async def settext_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text("Dùng: /settext brand|tagline|start|login|support|maintenance NỘI_DUNG");return
    fld=ctx.args[0].lower();val=" ".join(ctx.args[1:]).strip()
    key={"brand":"brand","tagline":"tagline","start":"start_button_text","login":"login_title","support":"support_report_text","maintenance":"maintenance_message"}.get(fld)
    if not key:await update.message.reply_text("Field không hợp lệ.");return
    req("PATCH","/api/admin/settings",json={key:val});await update.message.reply_text(f"✅ Đã cập nhật {fld}.")

async def setnotice_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<1:
        await update.message.reply_text("Dùng: /setnotice title|body|telegram|zalo|phone|remind|on|off VALUE")
        return
    fld=ctx.args[0].lower();val=" ".join(ctx.args[1:]).strip()
    if fld in ("on","off"):
        req("PATCH","/api/admin/portal-settings",json={"notice_enabled":"1" if fld=="on" else "0"})
        await update.message.reply_text(f"✅ Popup thông báo = {fld.upper()}")
        return
    if fld=="remind":
        try:mins=max(5,min(1440,int(val)))
        except Exception:
            await update.message.reply_text("Ví dụ: /setnotice remind 60");return
        req("PATCH","/api/admin/portal-settings",json={"notice_remind_minutes":str(mins)})
        await update.message.reply_text(f"✅ Nhắc sau = {mins} phút");return
    key={"title":"notice_title","body":"notice_body","telegram":"notice_telegram_url","zalo":"notice_zalo_url","phone":"notice_support_phone"}.get(fld)
    if not key:
        await update.message.reply_text("Mục hợp lệ: title, body, telegram, zalo, phone, remind, on, off");return
    req("PATCH","/api/admin/portal-settings",json={key:val})
    await update.message.reply_text(f"✅ Đã cập nhật thông báo: {fld}")

async def toggle_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2 or ctx.args[1].lower() not in ("on","off"):
        await update.message.reply_text("Dùng: /toggle lc79|sunwin|max789|telegram|maintenance|gps on|off");return
    fld=ctx.args[0].lower();v=1 if ctx.args[1].lower()=="on" else 0
    key={"lc79":"lc79_enabled","sunwin":"sunwin_enabled","max789":"max789_enabled","telegram":"telegram_floating","maintenance":"maintenance_mode","gps":"gps_prompt"}.get(fld)
    if not key:await update.message.reply_text("Mục không hợp lệ.");return
    req("PATCH","/api/admin/settings",json={key:v});await update.message.reply_text(f"✅ {fld.upper()} = {'ON' if v else 'OFF'}")

async def setlimits_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:d=max(1,min(20,int(ctx.args[0])));ip=max(1,min(50,int(ctx.args[1])))
    except Exception:await update.message.reply_text("Dùng: /setlimits DEVICES IP\nVí dụ: /setlimits 3 3");return
    req("PATCH","/api/admin/settings",json={"account_device_limit":d,"account_ip_limit":ip});await update.message.reply_text(f"✅ Giới hạn: {d} tài khoản/thiết bị · {ip} tài khoản/IP")

async def setdeposit_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:mn=int(ctx.args[0]);mx=int(ctx.args[1]);ttl=int(ctx.args[2])
    except Exception:await update.message.reply_text("Dùng: /setdeposit MIN MAX TTL_MINUTES\nVí dụ: /setdeposit 10000 5000000 10");return
    req("PATCH","/api/admin/settings",json={"deposit_min_vnd":mn,"deposit_max_vnd":mx,"deposit_ttl_minutes":ttl});await update.message.reply_text(f"✅ Nạp: min {fmt_money(mn)} · max {fmt_money(mx)} · TTL {ttl} phút")

async def allsettings_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    s=req("GET","/api/admin/settings").get("settings",{})
    keys=['brand','tagline','site_announcement','notice_enabled','notice_title','notice_body','notice_telegram_url','notice_zalo_url','notice_support_phone','notice_remind_minutes','admin_contact','ui_primary','ui_secondary','ui_accent','ui_surface','ui_font_scale','ui_compact','telegram_floating','maintenance_mode','lc79_enabled','sunwin_enabled','max789_enabled','account_device_limit','account_ip_limit','deposit_min_vnd','deposit_max_vnd','deposit_ttl_minutes','lc79_poll_seconds','sunwin_poll_seconds','max789_poll_seconds','history_limit']
    lines=['🧩 CẤU HÌNH ĐANG ÁP DỤNG','']+[f"{k} = {s.get(k,'-')}" for k in keys]
    await render_panel(update,'\n'.join(lines)[:3900])

async def account_live_worker(app):
    try:
        d=await asyncio.to_thread(req,"GET","/api/admin/account-events?after_id=0&limit=1")
        cur=int(d.get('latest_id') or 0)
    except Exception:cur=0
    while True:
        try:
            d=await asyncio.to_thread(req,"GET",f"/api/admin/account-events?after_id={cur}&limit=50")
            events=d.get('events') or []
            for e in events:
                cur=max(cur,int(e.get('id') or 0));ev=e.get('event');detail=e.get('detail') or {};user=e.get('username') or detail.get('username') or '-'
                if ev=='deposit_sent':
                    did=detail.get('deposit_id');amount=detail.get('amount',0)
                    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ DUYỆT",callback_data=f"depok:{did}"),InlineKeyboardButton("❌ TỪ CHỐI",callback_data=f"depno:{did}")]])
                    await app.bot.send_message(ADMIN_ID,f"💳 GIAO DỊCH ĐANG KIỂM TRA\n👤 User: {user}\n💰 Số tiền: {fmt_money(amount)}\n🧾 Nội dung: {detail.get('content','-')}\n🔖 Mã: {detail.get('request_code','-')}\n🆔 #{did}",reply_markup=kb)
                elif ev=='account_registered':
                    await app.bot.send_message(ADMIN_ID,f"👤 TÀI KHOẢN MỚI\n{user} · IP {detail.get('ip','-')}")
                elif ev=='key_purchased':
                    await app.bot.send_message(ADMIN_ID,f"🔑 MUA KEY\n👤 {user}\n💰 {fmt_money(detail.get('price',0))}")
            cur=max(cur,int(d.get('latest_id') or cur))
        except Exception:pass
        await asyncio.sleep(4)

async def callbacks(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    if not allowed(update):return
    await q.answer();data=q.data
    try:
        if data=="home": await render_panel(update,await dashboard_text())
        elif data=="accounts": await accounts_panel(update,ctx)
        elif data=="deposits": await deposits_panel(update,ctx)
        elif data=="notice": await notice_panel(update,ctx)
        elif data=="ui": await ui_panel(update,ctx)
        elif data=="dailyreport":
            await q.message.reply_text("⏳ Đang tạo 3 báo cáo 24H...")
            await send_daily_reports(ctx.application,manual=True)
        elif data.startswith("depok:"):
            did=int(data.split(":",1)[1]);d=req("POST",f"/api/admin/deposits/{did}/approve")
            await render_panel(update,f"✅ Đã duyệt nạp #{did} · {d.get('username','')} · {fmt_money(d.get('amount',0))}")
        elif data.startswith("depno:"):
            did=int(data.split(":",1)[1]);req("POST",f"/api/admin/deposits/{did}/reject")
            await render_panel(update,f"❌ Đã từ chối nạp #{did}.")
        elif data=="live": await render_panel(update,live_text(ctx))
        elif data=="newkey":
            rows=plan_buttons()
            if not rows: await render_panel(update,"Chưa có gói key. Dùng /addplan DAYS PRICE [DEVICES]")
            else:
                rows.append([InlineKeyboardButton("← Dashboard",callback_data="home")])
                await render_panel(update,"➕ TẠO KEY MỚI\n\nChọn gói bên dưới:",InlineKeyboardMarkup(rows))
        elif data.startswith("newp:"):await create_key_plan(update,ctx,int(data.split(":")[1]))
        elif data=="stats":await stats(update,ctx)
        elif data=="users":await users(update,ctx)
        elif data=="free":await free_stats(update,ctx)
        elif data=="list":await list_keys(update,ctx)
        elif data in ("price","plans"):await plans(update,ctx)
        elif data=="settings":await settings_cmd(update,ctx)
        elif data=="gamelinks":await gamelinks(update,ctx)
        elif data.startswith("disable:"):
            kid=int(data.split(":")[1]);req("POST",f"/api/admin/keys/{kid}/disable")
            await render_panel(update,f"🔴 Đã khóa key ID {kid}.")
        elif data.startswith("reset:"):
            kid=int(data.split(":")[1]);req("DELETE",f"/api/admin/keys/{kid}/devices")
            await render_panel(update,f"♻️ Đã reset thiết bị key ID {kid}.")
    except Exception as e:
        await render_panel(update,"⚠️ "+str(e))

async def cmd_new(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    rows=plan_buttons()
    if not rows:await update.message.reply_text("Chưa có gói. Tạo bằng /addplan DAYS PRICE [DEVICES]");return
    await update.message.reply_text("Chọn gói cần tạo:",reply_markup=InlineKeyboardMarkup(rows))

async def add_plan(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:
        days=int(ctx.args[0]);price=int(ctx.args[1]);devices=int(ctx.args[2]) if len(ctx.args)>=3 else 1
    except Exception:
        await update.message.reply_text("Dùng: /addplan DAYS PRICE [DEVICES]\nVí dụ: /addplan 30 50000 2");return
    d=req("POST","/api/admin/plans",json={"days":days,"price_vnd":price,"max_devices":devices,"name":f"{days} NGÀY"})
    await update.message.reply_text(f"✅ Đã thêm gói ID {d['id']}: {days} ngày · {fmt_money(price)} · {devices} thiết bị",reply_markup=menu())

async def edit_plan(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:
        pid=int(ctx.args[0]);days=int(ctx.args[1]);price=int(ctx.args[2]);devices=int(ctx.args[3]) if len(ctx.args)>=4 else 1
    except Exception:
        await update.message.reply_text("Dùng: /editplan ID DAYS PRICE [DEVICES]\nVí dụ: /editplan 2 7 35000 1");return
    req("PATCH",f"/api/admin/plans/{pid}",json={"days":days,"price_vnd":price,"max_devices":devices,"name":f"{days} NGÀY"})
    await update.message.reply_text(f"✅ Đã sửa gói ID {pid}: {days} ngày · {fmt_money(price)} · {devices} thiết bị",reply_markup=menu())

async def del_plan(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Dùng: /delplan ID");return
    pid=int(ctx.args[0]);req("DELETE",f"/api/admin/plans/{pid}")
    await update.message.reply_text(f"✅ Đã ẩn gói ID {pid}.",reply_markup=menu())

async def edit_key(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    try:
        kid=int(ctx.args[0]);days=int(ctx.args[1]);price=int(ctx.args[2]);devices=int(ctx.args[3])
    except Exception:
        await update.message.reply_text("Dùng: /editkey ID DAYS PRICE DEVICES\nVí dụ: /editkey 12 30 50000 2\nLưu ý: DAYS sẽ đặt lại hạn tính từ lúc sửa.");return
    d=req("PATCH",f"/api/admin/keys/{kid}",json={"days":days,"price_vnd":price,"max_devices":devices})
    await update.message.reply_text(f"✅ Đã sửa key ID {kid}\n⏳ {days} ngày từ bây giờ\n💰 {fmt_money(price)}\n📱 {devices} thiết bị\n⌛ {fmt_time(d['expires_at'])}")

def _find_account_by_username(username):
    username=(username or '').strip().lower()
    accs=req('GET','/api/admin/accounts').get('accounts',[])
    return next((x for x in accs if str(x.get('username','')).lower()==username),None)

async def user_detail_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args:
        await update.message.reply_text('Dùng: /user USERNAME');return
    a=_find_account_by_username(ctx.args[0])
    if not a:
        await update.message.reply_text('❌ Không tìm thấy tài khoản.');return
    d=req('GET',f"/api/admin/accounts/{a['id']}")
    x=d.get('account') or {};devices=d.get('devices') or [];tx=d.get('transactions') or [];deps=d.get('deposits') or []
    lines=[f"👤 TÀI KHOẢN @{x.get('username','-')}",
           f"ID: {x.get('id','-')}",f"Email: {x.get('email') or '-'}",
           f"Số dư: {fmt_money(x.get('balance_vnd',0))}",
           f"Trạng thái: {'🟢 hoạt động' if x.get('enabled') else '🔴 đã khóa'}",
           f"Tạo: {fmt_time(x.get('created_at'))}",f"Login cuối: {fmt_time(x.get('last_login_at'))}",
           f"IP đăng ký: {x.get('signup_ip') or '-'}",f"IP cuối: {x.get('last_login_ip') or '-'}",
           f"Thiết bị: {len(devices)} · Giao dịch ví: {len(tx)} · Yêu cầu nạp: {len(deps)}",'',
           '🔒 Mật khẩu được hash một chiều, không thể xem lại.',
           'Đặt lại: /resetpass USERNAME MATKHAUMOI',
           'Khóa/mở: /enableuser USERNAME on|off',
           'Xóa: /deluser USERNAME CONFIRM']
    await update.message.reply_text('\n'.join(lines)[:3900])

async def transactions_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if not ctx.args:
        await update.message.reply_text('Dùng: /transactions USERNAME');return
    a=_find_account_by_username(ctx.args[0])
    if not a:
        await update.message.reply_text('❌ Không tìm thấy tài khoản.');return
    d=req('GET',f"/api/admin/accounts/{a['id']}")
    rows=[f"💳 LỊCH SỬ @{a['username']}\n"]
    for x in (d.get('transactions') or [])[:20]:
        rows.append(f"{fmt_time(x.get('created_at'))} · {x.get('kind','')} · {fmt_money(x.get('amount',0))} · Số dư {fmt_money(x.get('balance_after',0))}")
    if len(rows)==1: rows.append('Chưa có giao dịch ví.')
    rows.append('\nYÊU CẦU NẠP')
    for x in (d.get('deposits') or [])[:12]:
        rows.append(f"#{x.get('id')} · {fmt_money(x.get('amount',0))} · {x.get('status')} · {x.get('transfer_content','')}")
    await update.message.reply_text('\n'.join(rows)[:3900])

async def resetpass_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2:
        await update.message.reply_text('Dùng: /resetpass USERNAME MATKHAUMOI');return
    a=_find_account_by_username(ctx.args[0])
    if not a:
        await update.message.reply_text('❌ Không tìm thấy tài khoản.');return
    pw=' '.join(ctx.args[1:])
    req('POST',f"/api/admin/accounts/{a['id']}/reset-password",json={'password':pw})
    await update.message.reply_text(f"✅ Đã đặt mật khẩu mới cho @{a['username']}.\nKhông hiển thị lại mật khẩu trong bot.")

async def enableuser_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2 or ctx.args[1].lower() not in ('on','off'):
        await update.message.reply_text('Dùng: /enableuser USERNAME on|off');return
    a=_find_account_by_username(ctx.args[0])
    if not a:
        await update.message.reply_text('❌ Không tìm thấy tài khoản.');return
    enabled=ctx.args[1].lower()=='on'
    req('PATCH',f"/api/admin/accounts/{a['id']}/status",json={'enabled':enabled})
    await update.message.reply_text(f"✅ @{a['username']} → {'MỞ' if enabled else 'KHÓA'}")

async def deluser_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    if len(ctx.args)<2 or ctx.args[1].upper()!='CONFIRM':
        await update.message.reply_text('Xóa tài khoản là vĩnh viễn.\nDùng: /deluser USERNAME CONFIRM');return
    a=_find_account_by_username(ctx.args[0])
    if not a:
        await update.message.reply_text('❌ Không tìm thấy tài khoản.');return
    req('DELETE',f"/api/admin/accounts/{a['id']}")
    await update.message.reply_text(f"🗑 Đã xóa tài khoản @{a['username']}.")

def analysis_report_text_payload(d):
    lines=[f"TAIXIUTOOL ANALYSIS REPORT {d.get('hours',48)}H",
           f"Period UTC: {d.get('period_start','')} -> {d.get('period_end','')}",'',
           'SOURCE STATUS']
    for k,v in (d.get('sources') or {}).items():
        lines.append(f"{k}: state={v.get('state')} latest={v.get('latest_session')} age={v.get('age_seconds')}s")
    lines += ['', 'RESULT STATS']
    for x in d.get('tables') or []:
        lines.append(f"{x.get('table_name')}: rows={x.get('rows',0)} settled={x.get('settled',0)} win={x.get('wins',0)} loss={x.get('losses',0)} accuracy={x.get('accuracy',0)}%")
    lines += ['', 'NEW / LEARNED PATTERNS']
    for x in (d.get('learned_patterns') or [])[:120]:
        tw=float(x.get('t_weight') or 0);xw=float(x.get('x_weight') or 0);side='T' if tw>xw else 'X' if xw>tw else '-'
        lines.append(f"{x.get('table_name')} | {x.get('context_key')} | samples={x.get('samples',0)} | T={tw:.3f} X={xw:.3f} => {side} | {x.get('updated_at','')}")
    return '\n'.join(lines)+'\n'

async def send_48h_reports(app,manual=False):
    stamp=datetime.now(TZ).strftime('%Y-%m-%d_%H%M')
    for game in ('lc79','sunwin','max789'):
        d=await asyncio.to_thread(req,'GET',f'/api/admin/daily-report?game={game}&hours=48')
        raw=report_text_payload(d).replace('24H','48H').encode('utf-8')
        bio=io.BytesIO(raw);bio.name=f'{game}_48h_{stamp}.txt'
        sm=d.get('summary') or {}
        await app.bot.send_document(ADMIN_ID,document=bio,caption=f"📊 {game.upper()} · 48H · {sm.get('wins',0)}/{sm.get('settled',0)} đúng · {sm.get('accuracy',0)}%")
    d=await asyncio.to_thread(req,'GET','/api/admin/analysis-report?hours=48')
    bio=io.BytesIO(analysis_report_text_payload(d).encode('utf-8'));bio.name=f'api_patterns_48h_{stamp}.txt'
    await app.bot.send_document(ADMIN_ID,document=bio,caption='🧩 API STATUS + HÌNH THÁI/CẦU MỚI · 48H')
    if not manual:
        await asyncio.to_thread(req,'POST','/api/admin/analysis-report-state',json={'last_sent_at':datetime.now(TZ).isoformat()})

async def report48_cmd(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not allowed(update):return
    m=await update.message.reply_text('⏳ Đang tạo báo cáo 48H...')
    try:
        await send_48h_reports(ctx.application,manual=True)
        await m.edit_text('✅ Đã gửi 4 file báo cáo 48H.')
    except Exception as e:
        await m.edit_text('⚠️ '+str(e)[:350])

async def report48_worker(app):
    while True:
        try:
            state=await asyncio.to_thread(req,'GET','/api/admin/analysis-report-state')
            last=state.get('last_sent_at') or ''
            due=True
            if last:
                try:
                    dt=datetime.fromisoformat(last)
                    if dt.tzinfo is None:dt=dt.replace(tzinfo=TZ)
                    due=(datetime.now(TZ)-dt.astimezone(TZ)).total_seconds()>=172800
                except Exception:due=True
            if due:await send_48h_reports(app,manual=False)
        except Exception:
            pass
        await asyncio.sleep(300)


def main():
    if not BOT_TOKEN or not ADMIN_ID:raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_ADMIN_ID")
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("newkey",cmd_new))
    app.add_handler(CommandHandler("keys",list_keys))
    app.add_handler(CommandHandler("key",key_detail))
    app.add_handler(CommandHandler("price",price))
    app.add_handler(CommandHandler("plans",plans))
    app.add_handler(CommandHandler("addplan",add_plan))
    app.add_handler(CommandHandler("editplan",edit_plan))
    app.add_handler(CommandHandler("delplan",del_plan))
    app.add_handler(CommandHandler("editkey",edit_key))
    app.add_handler(CommandHandler("stats",stats))
    app.add_handler(CommandHandler("users",users))
    app.add_handler(CommandHandler("free",free_stats))
    app.add_handler(CommandHandler("settings",settings_cmd))
    app.add_handler(CommandHandler("gamelinks",gamelinks))
    app.add_handler(CommandHandler("setgame",setgame))
    app.add_handler(CommandHandler("apiurls",apiurls))
    app.add_handler(CommandHandler("setapi",setapi))
    app.add_handler(CommandHandler("setfree",setfree))
    app.add_handler(CommandHandler("setpoll",setpoll))
    app.add_handler(CommandHandler("sethistory",sethistory))
    app.add_handler(CommandHandler("setalgo",setalgo))
    app.add_handler(CommandHandler("setcontact",setcontact))
    app.add_handler(CommandHandler("setgps",setgps))
    app.add_handler(CommandHandler("enableplan",enable_plan))
    app.add_handler(CommandHandler("enablekey",enable_key))
    app.add_handler(CommandHandler("resetkey",reset_key))
    app.add_handler(CommandHandler("customkey",custom_key))
    app.add_handler(CommandHandler("accounts",accounts_panel))
    app.add_handler(CommandHandler("deposits",deposits_panel))
    app.add_handler(CommandHandler("dailyreport",daily_report_cmd))
    app.add_handler(CommandHandler("announce",announce_cmd))
    app.add_handler(CommandHandler("setbank",setbank_cmd))
    app.add_handler(CommandHandler("balance",balance_cmd))
    app.add_handler(CommandHandler("congtien",congtien_cmd))
    app.add_handler(CommandHandler("trutien",trutien_cmd))
    app.add_handler(CommandHandler("ui",ui_panel))
    app.add_handler(CommandHandler("setui",setui_cmd))
    app.add_handler(CommandHandler("settext",settext_cmd))
    app.add_handler(CommandHandler("setnotice",setnotice_cmd))
    app.add_handler(CommandHandler("toggle",toggle_cmd))
    app.add_handler(CommandHandler("setlimits",setlimits_cmd))
    app.add_handler(CommandHandler("setdeposit",setdeposit_cmd))
    app.add_handler(CommandHandler("allsettings",allsettings_cmd))
    app.add_handler(CommandHandler("user",user_detail_cmd))
    app.add_handler(CommandHandler("transactions",transactions_cmd))
    app.add_handler(CommandHandler("resetpass",resetpass_cmd))
    app.add_handler(CommandHandler("enableuser",enableuser_cmd))
    app.add_handler(CommandHandler("deluser",deluser_cmd))
    app.add_handler(CommandHandler("report48",report48_cmd))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.COMMAND,auto_delete_admin_command),group=1)
    app.run_polling(drop_pending_updates=True,allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":main()
