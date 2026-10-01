import os, time, json, sqlite3, secrets, hashlib, hmac, re, base64, math, threading, uuid, smtplib, ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from email.message import EmailMessage

import requests
from flask import Flask, request, jsonify, send_from_directory

BASE = Path(__file__).resolve().parent
DB = Path(os.getenv("DB_PATH", str(BASE / "lc79_secure.db")))
DB.parent.mkdir(parents=True, exist_ok=True)
app = Flask(__name__, static_folder=None)

# Put real upstream URLs ONLY in Railway/VPS environment variables.
UPSTREAM_HU = os.getenv("UPSTREAM_HU", "")
UPSTREAM_MD5 = os.getenv("UPSTREAM_MD5", "")
SUNWIN_API = os.getenv("SUNWIN_API", "").strip()
SUNWIN_HISTORY_API = os.getenv("SUNWIN_HISTORY_API", "").strip()
MAX789_HU_API = os.getenv("MAX789_HU_API", "https://person-talent-mission-opening.trycloudflare.com/api/tx").strip()
MAX789_MD5_API = os.getenv("MAX789_MD5_API", "https://person-talent-mission-opening.trycloudflare.com/api/txmd5").strip()
LC79_GAME_URL = os.getenv("LC79_GAME_URL", "https://play.lc79.bet/").strip() or "https://play.lc79.bet/"
SUNWIN_GAME_URL = os.getenv("SUNWIN_GAME_URL", "https://sunwin.villas").strip() or "https://sunwin.villas"
MAX789_GAME_URL = os.getenv("MAX789_GAME_URL", "https://play.max789a.vin/").strip() or "https://play.max789a.vin/"
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
TOKEN_SECRET = os.getenv("TOKEN_SECRET", secrets.token_hex(32))
SESSION_SECONDS = int(os.getenv("SESSION_SECONDS", "21600"))
MAX_DEVICES_DEFAULT = int(os.getenv("MAX_DEVICES", "1"))
LINK4M_API_TOKEN = os.getenv("LINK4M_API_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USER).strip()
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "TAIXIUTOOL").strip() or "TAIXIUTOOL"
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").strip().lower() not in ("0","false","off","no")
RESET_CODE_TTL_MINUTES = max(5, min(30, int(os.getenv("RESET_CODE_TTL_MINUTES", "10"))))
SOURCE_STALE_SECONDS = max(120, int(os.getenv("SOURCE_STALE_SECONDS", "300")))
SOURCE_HARD_STALE_SECONDS = max(SOURCE_STALE_SECONDS + 60, int(os.getenv("SOURCE_HARD_STALE_SECONDS", "900")))

SETTING_DEFAULTS = {
    "brand":"TAIXIUTOOL",
    "admin_contact":"@huanhoahong11111",
    "free_key_hours":"1",
    "free_daily_limit":"2",
    "free_ip_daily_limit":"6",
    "captcha_ttl_seconds":"300",
    "free_step_ttl_minutes":"12",
    "free_flow_ttl_minutes":"30",
    "lc79_poll_seconds":"3",
    "sunwin_poll_seconds":"4",
    "max789_poll_seconds":"3",
    "history_refresh_seconds":"24",
    "history_limit":"60",
    "history_ttl_hours":"24",
    "lc79_algo_mode":"2",
    "sunwin_algo_mode":"2",
    "max789_algo_mode":"3",
    "gps_prompt":"1",
    "lc79_game_url":LC79_GAME_URL,
    "lc79_hu_api_url":UPSTREAM_HU,
    "lc79_md5_api_url":UPSTREAM_MD5,
    "sunwin_game_url":SUNWIN_GAME_URL,
    "sunwin_api_url":SUNWIN_API,
    "sunwin_history_api_url":SUNWIN_HISTORY_API,
    "max789_game_url":MAX789_GAME_URL,
    "max789_hu_api_url":MAX789_HU_API,
    "max789_md5_api_url":MAX789_MD5_API,
    "site_announcement":"Chào mừng bạn đến TAIXIUTOOL.",
    "notice_enabled":"1",
    "notice_title":"Thông báo",
    "notice_body":"Theo dõi kênh hỗ trợ để nhận cập nhật mới nhất từ hệ thống.",
    "notice_telegram_url":"",
    "notice_zalo_url":"",
    "notice_support_phone":"",
    "notice_remind_minutes":"60",
    "bank_code":"970443",
    "bank_account":"0988712947",
    "bank_account_name":"TRUONG VAN NGOC DOANH",
    "support_report_text":"Hỗ trợ / báo lỗi",
    "tagline":"Gọn · nhanh · đồng bộ realtime",
    "start_button_text":"BẮT ĐẦU",
    "login_title":"Đăng nhập TAIXIUTOOL",
    "ui_primary":"#49e8ff",
    "ui_secondary":"#766bff",
    "ui_accent":"#ff66b8",
    "ui_surface":"#07111b",
    "ui_font_scale":"100",
    "ui_compact":"1",
    "telegram_floating":"1",
    "maintenance_mode":"0",
    "maintenance_message":"Hệ thống đang bảo trì, vui lòng quay lại sau.",
    "lc79_enabled":"1",
    "sunwin_enabled":"1",
    "max789_enabled":"1",
    "account_device_limit":"3",
    "account_ip_limit":"3",
    "deposit_min_vnd":"10000",
    "deposit_max_vnd":"100000000",
    "deposit_ttl_minutes":"10",
}

# Short in-process cache for temporary Cloudflare/API hiccups.
_SUNWIN_CACHE={
    "current":{"ts":0.0,"data":None},
    "history":{"ts":0.0,"data":None},
}
_UPSTREAM_CACHE={"hu":{"ts":0.0,"data":None},"md5":{"ts":0.0,"data":None},"max789_hu":{"ts":0.0,"data":None},"max789_md5":{"ts":0.0,"data":None}}
_SOURCE_STATE={}
_SOURCE_ERRORS={}
_UPSTREAM_LOCKS={k:threading.Lock() for k in ("hu","md5","sunwin","max789_hu","max789_md5")}



def db():
    con=sqlite3.connect(DB, timeout=20)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA busy_timeout=8000")
    return con

def init_db():
    with db() as con:
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass
        con.executescript("""
        CREATE TABLE IF NOT EXISTS keys(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          key_hash TEXT UNIQUE NOT NULL,
          label TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          max_devices INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS devices(
          key_id INTEGER NOT NULL,
          device_hash TEXT NOT NULL,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          UNIQUE(key_id,device_hash)
        );
        CREATE TABLE IF NOT EXISTS free_claims(
          id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT UNIQUE NOT NULL,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL, claimed_at TEXT, claimed_ip TEXT
        );
        CREATE TABLE IF NOT EXISTS analytics(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event TEXT NOT NULL, key_id INTEGER, device_hash TEXT, ip_address TEXT,
          os_name TEXT, user_agent TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics(created_at);
        CREATE INDEX IF NOT EXISTS idx_analytics_event ON analytics(event);
        CREATE TABLE IF NOT EXISTS captchas(
          id TEXT PRIMARY KEY,
          answer_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          used INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_captchas_expires ON captchas(expires_at);
        CREATE TABLE IF NOT EXISTS free_flows(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          flow_token_hash TEXT UNIQUE NOT NULL,
          device_hash TEXT NOT NULL, request_ip TEXT,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          current_step INTEGER NOT NULL DEFAULT 1,
          step1_verified_at TEXT, step2_verified_at TEXT,
          completed_at TEXT, key_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS free_steps(
          id INTEGER PRIMARY KEY AUTOINCREMENT, flow_id INTEGER NOT NULL, step INTEGER NOT NULL,
          token_hash TEXT UNIQUE NOT NULL, code_text TEXT NOT NULL, code_hash TEXT NOT NULL,
          short_url TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          visited_at TEXT, visited_ip TEXT, verified_at TEXT,
          UNIQUE(flow_id,step)
        );
        CREATE INDEX IF NOT EXISTS idx_free_flows_device ON free_flows(device_hash,completed_at);
        CREATE INDEX IF NOT EXISTS idx_free_steps_flow ON free_steps(flow_id,step);
        CREATE TABLE IF NOT EXISTS history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          key_id INTEGER NOT NULL,
          table_name TEXT NOT NULL,
          session_id TEXT NOT NULL,
          side TEXT,
          confidence INTEGER NOT NULL,
          reason TEXT DEFAULT '',
          actual TEXT,
          correct INTEGER,
          created_at TEXT NOT NULL,
          UNIQUE(key_id,table_name,session_id)
        );
        CREATE TABLE IF NOT EXISTS global_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          table_name TEXT NOT NULL,
          session_id TEXT NOT NULL,
          side TEXT,
          confidence INTEGER NOT NULL,
          reason TEXT DEFAULT '',
          actual TEXT,
          correct INTEGER,
          created_at TEXT NOT NULL,
          settled_at TEXT,
          UNIQUE(table_name,session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_global_history_table_created ON global_history(table_name,created_at);
        CREATE INDEX IF NOT EXISTS idx_global_history_unsettled ON global_history(table_name,actual);
        CREATE TABLE IF NOT EXISTS plans(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          days INTEGER NOT NULL,
          price_vnd INTEGER NOT NULL DEFAULT 0,
          max_devices INTEGER NOT NULL DEFAULT 1,
          enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS custom_games(
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT DEFAULT '',
          game_url TEXT NOT NULL,
          image_url TEXT DEFAULT '',
          api_url TEXT DEFAULT '',
          history_api_url TEXT DEFAULT '',
          algo_mode INTEGER NOT NULL DEFAULT 2,
          poll_seconds INTEGER NOT NULL DEFAULT 4,
          enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 100,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_custom_games_enabled_sort ON custom_games(enabled,sort_order,name);
        CREATE TABLE IF NOT EXISTS background_watches(
          key_id INTEGER NOT NULL,
          device_hash TEXT NOT NULL,
          started_at TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(key_id,device_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_background_watches_active ON background_watches(active,expires_at);
        CREATE TABLE IF NOT EXISTS worker_leases(
          name TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          until_ts REAL NOT NULL
        );
        """)
        # V36 privacy/security metadata migrations
        fcols={r[1] for r in con.execute("PRAGMA table_info(free_claims)").fetchall()}
        for name,typ in [("device_hash","TEXT"),("request_ip","TEXT")]:
            if name not in fcols:
                con.execute(f"ALTER TABLE free_claims ADD COLUMN {name} {typ}")
        cols={r[1] for r in con.execute("PRAGMA table_info(devices)").fetchall()}
        for name,typ in [
            ("ip_address","TEXT"),("location","TEXT"),("os_name","TEXT"),("user_agent","TEXT"),
            ("browser_name","TEXT"),("gps_lat","REAL"),("gps_lon","REAL"),("gps_accuracy","REAL"),
            ("gps_updated_at","TEXT")
        ]:
            if name not in cols:
                con.execute(f"ALTER TABLE devices ADD COLUMN {name} {typ}")
        kcols={r[1] for r in con.execute("PRAGMA table_info(keys)").fetchall()}
        for name,typ in [("days","INTEGER"),("price_vnd","INTEGER"),("plan_id","INTEGER"),("owner_account_id","INTEGER")]:
            if name not in kcols:
                con.execute(f"ALTER TABLE keys ADD COLUMN {name} {typ}")

        # Flexible plan durations: supports 1 hour and a long-lived lifetime plan.
        pcols={r[1] for r in con.execute("PRAGMA table_info(plans)").fetchall()}
        for name,typ,default in [("duration_seconds","INTEGER",0),("lifetime","INTEGER",0)]:
            if name not in pcols:
                con.execute(f"ALTER TABLE plans ADD COLUMN {name} {typ} DEFAULT {default}")

        # Metadata for online learning from settled REAL sessions.
        ghcols={r[1] for r in con.execute("PRAGMA table_info(global_history)").fetchall()}
        for name,typ,default in [("learn_keys","TEXT",None),("learned","INTEGER",0)]:
            if name not in ghcols:
                if default is None:
                    con.execute(f"ALTER TABLE global_history ADD COLUMN {name} {typ}")
                else:
                    con.execute(f"ALTER TABLE global_history ADD COLUMN {name} {typ} DEFAULT {default}")
        con.execute('''CREATE TABLE IF NOT EXISTS learned_patterns(
          table_name TEXT NOT NULL,
          context_key TEXT NOT NULL,
          t_weight REAL NOT NULL DEFAULT 0,
          x_weight REAL NOT NULL DEFAULT 0,
          samples INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(table_name,context_key)
        )''')
        con.execute("CREATE INDEX IF NOT EXISTS idx_learned_patterns_table ON learned_patterns(table_name,samples)")

        # Official portal price board. Existing databases are upgraded in place.
        official_plans=[
          ("1 GIỜ",0,10000,3600,0,10),
          ("1 NGÀY",1,20000,86400,0,20),
          ("7 NGÀY",7,67000,604800,0,30),
          ("1 THÁNG",30,123000,2592000,0,40),
          ("VĨNH VIỄN",36500,236000,3153600000,1,50),
        ]
        for pname,pdays,pprice,pseconds,plife,psort in official_plans:
            row=con.execute("SELECT id FROM plans WHERE upper(name)=upper(?) ORDER BY id LIMIT 1",(pname,)).fetchone()
            if row:
                con.execute("UPDATE plans SET days=?,price_vnd=?,max_devices=1,enabled=1,sort_order=?,duration_seconds=?,lifetime=? WHERE id=?",
                            (pdays,pprice,psort,pseconds,plife,row['id']))
            else:
                con.execute("INSERT INTO plans(name,days,price_vnd,max_devices,enabled,sort_order,created_at,duration_seconds,lifetime) VALUES(?,?,?,?,1,?,?,?,?)",
                            (pname,pdays,pprice,1,psort,now_iso(),pseconds,plife))
        for sk,sv in SETTING_DEFAULTS.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",(sk,str(sv),now_iso()))

def now_iso(): return datetime.now(timezone.utc).isoformat()
def get_setting(key, default=None):
    fallback=SETTING_DEFAULTS.get(key,default)
    try:
        with db() as con:
            r=con.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        return str(r["value"]) if r else (str(fallback) if fallback is not None else "")
    except Exception:
        return str(fallback) if fallback is not None else ""

def setting_int(key, default=0, lo=None, hi=None):
    try:v=int(float(get_setting(key,default)))
    except Exception:v=int(default)
    if lo is not None:v=max(lo,v)
    if hi is not None:v=min(hi,v)
    return v

def setting_bool(key, default=True):
    return get_setting(key,"1" if default else "0").strip().lower() in ("1","true","yes","on")

def set_setting(key,value):
    with db() as con:
        con.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,str(value),now_iso()))

def key_hash(key:str): return hashlib.sha256(key.strip().encode()).hexdigest()
def device_hash(device:str): return hashlib.sha256(device.encode()).hexdigest()

def sign_token(payload:dict)->str:
    raw=json.dumps(payload,separators=(",",":"),sort_keys=True).encode()
    body=raw.hex()
    sig=hmac.new(TOKEN_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+"."+sig

def verify_token(token:str)->Optional[dict]:
    try:
        body,sig=token.split(".",1)
        expected=hmac.new(TOKEN_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected): return None
        p=json.loads(bytes.fromhex(body))
        if int(p["exp"]) < int(time.time()): return None
        return p
    except Exception: return None

def current_auth():
    auth=request.headers.get("Authorization","")
    if not auth.startswith("Bearer "): return None
    p=verify_token(auth[7:])
    if not p:return None
    if p.get('aid') is not None and p.get('dev'):
        raw_device=str(request.headers.get('X-Device-ID') or '').strip()
        if not raw_device or not hmac.compare_digest(str(p.get('dev')),device_hash(raw_device)):return None
    with db() as con:
        row=con.execute("SELECT * FROM keys WHERE id=? AND enabled=1",(p["kid"],)).fetchone()
    if not row:return None
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc): return None
    return p

def require_auth(fn):
    def wrap(*a,**kw):
        p=current_auth()
        if not p:return jsonify({"detail":"Key hoặc phiên đăng nhập không hợp lệ"}),401
        request.auth_payload=p
        return fn(*a,**kw)
    wrap.__name__=fn.__name__
    return wrap

def require_admin(fn):
    def wrap(*a,**kw):
        supplied=request.headers.get("X-Admin-Secret","")
        if not ADMIN_SECRET or not hmac.compare_digest(supplied,ADMIN_SECRET):
            return jsonify({"detail":"Admin unauthorized"}),401
        return fn(*a,**kw)
    wrap.__name__=fn.__name__
    return wrap

def normalize_tx(item):
    if not isinstance(item,dict):return None
    for k in ("result","ketqua","ket_qua","type","side","tx","taiXiu","tai_xiu","gameResult"):
        if k not in item:continue
        v=str(item[k]).strip().lower()
        if v in ("tai","tài","t","big","over"):return "T"
        if v in ("xiu","xỉu","x","small","under"):return "X"
    for ks in (("d1","d2","d3"),("dice1","dice2","dice3"),("xucxac1","xucxac2","xucxac3")):
        try:
            a=[int(item[k]) for k in ks]
            if all(1<=n<=6 for n in a):
                s=sum(a)
                if 11<=s<=17:return "T"
                if 4<=s<=10:return "X"
        except Exception: pass
    try:
        s=int(item.get("total",item.get("tong",item.get("sum",item.get("point")))))
        if 11<=s<=17:return "T"
        if 4<=s<=10:return "X"
    except Exception:pass
    return None

def get_upstream(table):
    """Resilient fetch for LC79/MAX789.

    One table fetch is single-flight inside the process, duplicate UI/background
    polls collapse into the same short cache, and a recently successful real
    payload may be reused briefly during a transient network failure. No fake
    session ids or synthetic results are ever created here.
    """
    if table=="hu": url=get_setting("lc79_hu_api_url",UPSTREAM_HU).strip()
    elif table=="md5": url=get_setting("lc79_md5_api_url",UPSTREAM_MD5).strip()
    elif table=="max789_hu": url=get_setting("max789_hu_api_url",MAX789_HU_API).strip()
    elif table=="max789_md5": url=get_setting("max789_md5_api_url",MAX789_MD5_API).strip()
    else: url=""
    if not url: raise RuntimeError(f"Chưa cấu hình API cho {table.upper()}")

    now=time.time();slot=_UPSTREAM_CACHE.setdefault(table,{"ts":0.0,"data":None})
    cached=slot.get("data");cached_ts=float(slot.get("ts") or 0)
    if cached is not None and now-cached_ts < 2.4:
        return cached

    lock=_UPSTREAM_LOCKS.setdefault(table,threading.Lock())
    with lock:
        now=time.time();cached=slot.get("data");cached_ts=float(slot.get("ts") or 0)
        if cached is not None and now-cached_ts < 2.4:
            return cached
        headers={"Accept":"application/json, text/plain, */*","User-Agent":"TAIXIUTOOL/1.0","Cache-Control":"no-cache","Pragma":"no-cache"}
        last_err=None
        for timeout in ((2.4,4.2),(3.0,5.5)):
            try:
                r=requests.get(url,headers=headers,timeout=timeout)
                r.raise_for_status()
                try:data=r.json()
                except ValueError:data=json.loads(r.text.lstrip('\ufeff').strip())
                slot["ts"]=time.time();slot["data"]=data
                _SOURCE_ERRORS[table]=""
                st=_SOURCE_STATE.setdefault(table,{"sid":None,"changed":time.time()})
                st["last_success"]=time.time()
                return data
            except requests.HTTPError as e:
                code=getattr(getattr(e,'response',None),'status_code',None);last_err=f"HTTP {code or 'ERR'}"
            except requests.Timeout:
                last_err="timeout"
            except requests.RequestException:
                last_err="không kết nối được"
            except ValueError:
                last_err="JSON không hợp lệ"
        _SOURCE_ERRORS[table]=last_err or "không phản hồi"
        # Keep the last REAL payload briefly so UI/background polls do not all
        # collapse during a short upstream hiccup.
        if cached is not None and time.time()-cached_ts < 30.0:
            return cached
        raise RuntimeError(f"{table.upper()} API {_SOURCE_ERRORS[table]}")

def _strict_session_id(item):
    if not isinstance(item,dict): return None
    low={str(k).lower():v for k,v in item.items()}
    for k in ("phien","phiên","sessionid","session_id","session","sid","roundid","round_id","round","referenceid","reference_id","id"):
        v=low.get(k)
        if v is None or isinstance(v,(dict,list)): continue
        out=str(v).strip()
        if out:return out
    return None


def _sort_and_dedupe_sessions(rows):
    """Return newest-first unique real sessions. Never invent an ID."""
    if not rows:return []
    best={}
    for sid,tx in rows:
        sid=str(sid).strip()
        if not sid or tx not in ("T","X"):continue
        if sid not in best:best[sid]=tx
    rows=list(best.items())
    numeric=[];other=[]
    for sid,tx in rows:
        try:numeric.append((int(sid),sid,tx))
        except Exception:other.append((sid,tx))
    if numeric and len(numeric)>=max(3,int(len(rows)*.55)):
        numeric.sort(key=lambda x:x[0],reverse=True)
        return [(sid,tx) for _,sid,tx in numeric]
    return rows


def extract_history(data):
    """LC79 adapter. Prefer the documented list/data array, then fall back to
    the recursive adapter so small upstream wrapper changes do not break the UI.
    Real session ids are still mandatory; no index-based/fake sessions are made.
    """
    arr=data.get("list") if isinstance(data,dict) else None
    if not isinstance(arr,list) and isinstance(data,dict):arr=data.get("data")
    if not isinstance(arr,list):arr=[]
    out=[]
    for x in arr:
        tx=normalize_tx(x)
        sid=_strict_session_id(x)
        if tx and sid is not None:out.append((sid,tx))
    rows=_sort_and_dedupe_sessions(out)
    if len(rows)>=3:
        return rows
    # API providers often move history under result/history/records without notice.
    fallback=extract_any_history(data)
    return fallback if len(fallback)>len(rows) else rows


def extract_any_history(data):
    """Nested JSON history adapter for third-party T/X endpoints.

    Accepts list/data wrappers and nested dict/list payloads, but still requires
    a real session id. It never creates synthetic sessions.
    """
    rows=[]
    def walk(obj):
        if isinstance(obj,dict):
            tx=normalize_tx(obj);sid=_strict_session_id(obj)
            if tx and sid is not None:rows.append((str(sid),tx))
            for v in obj.values():walk(v)
        elif isinstance(obj,list):
            for v in obj:walk(v)
    walk(data)
    return _sort_and_dedupe_sessions(rows)

def _numeric_consecutive_head(seq, need=3):
    """Validate newest-first numeric ids like 100,99,98 before deriving 101."""
    vals=[]
    for sid,_ in seq[:max(need,5)]:
        try:vals.append(int(str(sid)))
        except Exception:return None
    if len(vals)<need:return None
    for a,b in zip(vals[:need-1],vals[1:need]):
        if a-b!=1:return None
    return vals[0]


def _source_freshness(table, latest_sid, stale_after=95.0):
    """Track when the upstream's latest completed session actually advances."""
    now=time.time();key=str(latest_sid)
    st=_SOURCE_STATE.setdefault(table,{"sid":None,"changed":now})
    if st.get("sid")!=key:
        st["sid"]=key;st["changed"]=now
    age=max(0.0,now-float(st.get("changed") or now))
    return age, age<=stale_after


def _sun_walk(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():
            yield from _sun_walk(v)
    elif isinstance(obj,list):
        for v in obj:
            yield from _sun_walk(v)

def _sun_session_id(item):
    if not isinstance(item,dict): return None
    low={str(k).lower():v for k,v in item.items()}
    for k in ("phien","phiên","sessionid","session_id","session","sid","roundid","round_id","round","referenceid","reference_id","id"):
        if k in low and low[k] is not None and not isinstance(low[k],(dict,list)):
            s=str(low[k]).strip()
            if s: return s
    return None

def normalize_sunwin(item):
    tx=normalize_tx(item)
    if tx:return tx
    if not isinstance(item,dict):return None
    low={str(k).lower():v for k,v in item.items()}
    for k in ("dice","dices","xucxac","xúc_xắc","xuc_xac","dice_values","dicevalue"):
        v=low.get(k)
        if isinstance(v,(list,tuple)) and len(v)>=3:
            try:
                a=[int(v[0]),int(v[1]),int(v[2])]
                if all(1<=n<=6 for n in a):
                    s=sum(a)
                    return "T" if 11<=s<=17 else "X" if 4<=s<=10 else None
            except Exception: pass
    # Separate dice fields used by many Tài/Xỉu APIs.
    for keys in (("dice1","dice2","dice3"),("d1","d2","d3"),("xuc_xac_1","xuc_xac_2","xuc_xac_3")):
        if all(k in low for k in keys):
            try:
                a=[int(low[k]) for k in keys]
                if all(1<=n<=6 for n in a):
                    s=sum(a);return "T" if 11<=s<=17 else "X" if 4<=s<=10 else None
            except Exception: pass
    for k in ("ket_qua","ketqua","result","result_name","game_result","tai_xiu","taixiu","outcome","win","winner","type"):
        if k in low:
            v=str(low[k]).strip().lower()
            if "tài" in v or v=="tai" or v=="big":return "T"
            if "xỉu" in v or v=="xiu" or v=="small":return "X"
    return None

def extract_sunwin_history(data):
    rows=[];seen=set()
    for d in _sun_walk(data):
        tx=normalize_sunwin(d)
        if not tx:continue
        sid=_sun_session_id(d)
        # Never fabricate auto-* session ids.
        if sid is None:continue
        key=(str(sid),tx)
        if key in seen:continue
        seen.add(key);rows.append((str(sid),tx))
    return _sort_and_dedupe_sessions(rows)


def find_sunwin_current_session(data):
    candidates=[]
    for d in _sun_walk(data):
        sid=_sun_session_id(d)
        if sid is None:continue
        score=0; ks={str(k).lower() for k in d.keys()}
        if any(k in ks for k in ("phien","phiên","sessionid","session_id","session","sid")):score+=4
        if normalize_sunwin(d) is None:score+=1
        try:num=int(str(sid));score+=2;candidates.append((score,num,str(sid)))
        except Exception:candidates.append((score,-1,str(sid)))
    if not candidates:return None
    candidates.sort(reverse=True)
    return candidates[0][2]

def _fetch_json_source(url, table, cache_slot, user_agent):
    """Fetch one JSON source with single-flight-friendly cache semantics."""
    import time as _time
    now=_time.time();cached=cache_slot.get("data");cached_ts=float(cache_slot.get("ts") or 0)
    if cached is not None and now-cached_ts < 2.4:
        return cached
    headers={
        "Accept":"application/json, text/plain, */*",
        "User-Agent":user_agent,
        "Cache-Control":"no-cache",
        "Pragma":"no-cache",
        "Connection":"keep-alive",
    }
    last_err=None
    for timeout in (4.0,6.2):
        try:
            r=requests.get(url,headers=headers,timeout=timeout)
            r.raise_for_status()
            try:data=r.json()
            except ValueError:
                # Some providers return JSON with a text/plain content type.
                data=json.loads(r.text.lstrip('\ufeff').strip())
            cache_slot["ts"]=_time.time();cache_slot["data"]=data
            _SOURCE_ERRORS[table]=""
            st=_SOURCE_STATE.setdefault(table,{"sid":None,"changed":_time.time()});st["last_success"]=_time.time()
            return data
        except requests.HTTPError as e:
            code=getattr(getattr(e,'response',None),'status_code',None);last_err=f"HTTP {code or 'ERR'}"
        except requests.Timeout:last_err="timeout"
        except requests.RequestException:last_err="không kết nối được"
        except (ValueError,json.JSONDecodeError):last_err="JSON không hợp lệ"
    _SOURCE_ERRORS[table]=last_err or "không phản hồi"
    if cached is not None and _time.time()-cached_ts < 35.0:
        return cached
    raise RuntimeError(f"{table.upper()} API {_SOURCE_ERRORS[table]}")


def get_sunwin_upstream():
    """SUNWIN adapter. Supports a separate history endpoint when configured.

    `sunwin_api_url` may be a current+history endpoint. If the provider exposes
    history separately, set `sunwin_history_api_url`; otherwise the same real
    payload is reused for both roles.
    """
    table="sunwin"
    current_url=get_setting("sunwin_api_url",SUNWIN_API).strip()
    history_url=get_setting("sunwin_history_api_url","").strip() or current_url
    if not current_url:raise RuntimeError("Chưa cấu hình SUNWIN API")
    lock=_UPSTREAM_LOCKS.setdefault(table,threading.Lock())
    with lock:
        current=_fetch_json_source(current_url,table,_SUNWIN_CACHE["current"],"TAIXIUTOOL-SUNWIN/2.0")
        if history_url==current_url:
            # Keep both cache slots aligned so a later history URL change starts cleanly.
            _SUNWIN_CACHE["history"]["ts"]=_SUNWIN_CACHE["current"]["ts"]
            _SUNWIN_CACHE["history"]["data"]=current
            return current,current
        history=_fetch_json_source(history_url,table,_SUNWIN_CACHE["history"],"TAIXIUTOOL-SUNWIN-HISTORY/2.0")
        return current,history


# =============================================================
# LEGACY ENGINE V57 / V58 / V59 — giữ nguyên để backup.
# V61 KHÔNG gọi các hàm này, nhưng giữ lại để rollback nhanh nếu cần.
# =============================================================
def predict_lc79_v57(seq):
    """LC79 V57 walk-forward adaptive ensemble.
    Input `seq` is newest-first: [(sid, 'T'/'X'), ...].
    """
    import math as _m
    newest=[x[1] for x in seq[:180] if x[1] in ("T","X")]
    if len(newest) < 12:
        return None,0,"LC79 V57 · CHƯA ĐỦ DỮ LIỆU · BỎ QUA"
    x=list(reversed(newest))

    def sgn(v): return 1.0 if v=="T" else -1.0
    def clamp(v,a,b): return a if v<a else b if v>b else v

    def mk(hist,order):
        if len(hist)<order+5:return 0.0,0.0
        ctx=hist[-order:]; t=z=.85; support=0.0; n=len(hist)
        for i in range(order,n):
            if hist[i-order:i]==ctx:
                age=n-1-i
                w=.5**(age/24.0)
                if hist[i]=="T":t+=w
                else:z+=w
                support+=w
        return ((t-z)/(t+z),support) if support>.12 else (0.0,0.0)

    def context(hist,order):
        if len(hist)<order+6:return 0.0,0.0
        ctx=hist[-order:]; t=z=.65; support=0.0;n=len(hist)
        for i in range(order,n):
            if hist[i-order:i]==ctx:
                w=.5**((n-1-i)/16.0)
                if hist[i]=="T":t+=w
                else:z+=w
                support+=w
        if support<.18:return 0.0,0.0
        return (clamp((t-z)/(t+z),-1,1),support*(1+.05*order))

    def run_model(hist):
        if len(hist)<12:return 0.0,0.0
        cur=hist[-1]; run=1
        for i in range(len(hist)-2,-1,-1):
            if hist[i]==cur:run+=1
            else:break
        run=min(run,8)
        cont=rev=.8; sup=0.0;n=len(hist)
        for i in range(2,n-1):
            r=1;j=i-1
            while j>=0 and hist[j]==hist[i] and r<9:
                r+=1;j-=1
            if hist[i]==cur and abs(r-run)<=1:
                w=.5**((n-2-i)/22.0)
                if hist[i+1]==cur:cont+=w
                else:rev+=w
                sup+=w
        if sup<.2:return 0.0,0.0
        p=(cont-rev)/(cont+rev)
        return clamp(sgn(cur)*p,-1,1),sup

    def alt_trend(hist):
        r=hist[-18:]
        if len(r)<8:return 0.0,0.0
        ch=sum(r[i]!=r[i-1] for i in range(1,len(r)))/(len(r)-1)
        if ch>=.68:return -sgn(r[-1])*clamp((ch-.5)*2.2,0,1),1.0+(ch-.68)*2
        if ch<=.32:return sgn(r[-1])*clamp((.5-ch)*2.0,0,1),.9+(.32-ch)*2
        return 0.0,.15

    def momentum(hist):
        if len(hist)<15:return 0.0,0.0
        vals=[]
        for w,wt in ((5,.36),(9,.28),(15,.22),(27,.14)):
            r=hist[-w:]
            if len(r)<4:continue
            vals.append((sum(sgn(v) for v in r)/len(r),wt))
        if not vals:return 0.0,0.0
        den=sum(w for _,w in vals)
        edge=sum(e*w for e,w in vals)/den
        r5=sum(sgn(v) for v in hist[-5:])/min(5,len(hist))
        r15=sum(sgn(v) for v in hist[-15:])/min(15,len(hist))
        slope=r5-r15
        return clamp(edge*.48+slope*.52,-1,1),.7+abs(slope)*.5

    def cycle(hist):
        y=[sgn(v) for v in hist];n=len(y)
        if n<18:return 0.0,0.0
        best=[]
        for lag in range(2,min(13,n//2+1)):
            vals=[y[i]*y[i-lag] for i in range(lag,n)]
            if len(vals)<8:continue
            ac=sum(vals)/len(vals)
            pred=ac*y[-lag]
            q=abs(ac)/(lag**.25)
            if q>.10:best.append((pred,q))
        if not best:return 0.0,0.0
        den=sum(q for _,q in best)
        return clamp(sum(e*q for e,q in best)/den,-1,1),clamp(den/2.2,.1,1.4)

    candidates=[]
    for o in (1,2,3,4,5):candidates.append((f"MK{o}",lambda h,o=o:mk(h,o)))
    for o in (2,3,4,5,6):candidates.append((f"CTX{o}",lambda h,o=o:context(h,o)))
    candidates += [("RUN",run_model),("REG",alt_trend),("MOM",momentum),("CYCLE",cycle)]

    eval_start=max(12,len(x)-72)
    perf={}
    for name,fn in candidates:
        hit=tot=0.0; active=0
        for i in range(eval_start,len(x)):
            e,sup=fn(x[:i])
            if sup<=.12 or abs(e)<.035:continue
            age=len(x)-1-i
            w=.5**(age/30.0) * min(1.35,.55+sup*.28) * min(1.0,.40+abs(e))
            pred="T" if e>0 else "X"
            tot+=w; hit+=w if pred==x[i] else 0.0; active+=1
        acc=(hit+2.4)/(tot+4.8) if tot>0 else .5
        perf[name]=(acc,tot,active)

    scored=[]
    for name,fn in candidates:
        edge,sup=fn(x)
        if sup<=.10 or abs(edge)<.025:continue
        acc,tot,active=perf[name]
        sample_factor=clamp(tot/8.5,0.15,1.0)
        direction=1.0
        skill=acc-.5
        effective_acc=acc
        if active>=10 and acc<.455:
            direction=-1.0; skill=.5-acc; effective_acc=1.0-acc
        elif acc<.505:
            skill=.005; effective_acc=.5
        weight=(.18+skill*5.2) * sample_factor * clamp(.45+sup*.32,.35,1.35)
        scored.append((edge*direction,weight,name,effective_acc,tot))

    if not scored:
        return None,50,"ENSEMBLE LC79 V57 · KHÔNG CÓ MODEL ĐỦ SUPPORT · BỎ QUA"

    den=sum(w for _,w,_,_,_ in scored) or 1.0
    norm=sum(e*w for e,w,_,_,_ in scored)/den
    pos=sum(w*min(1,abs(e)+.25) for e,w,_,_,_ in scored if e>0)
    neg=sum(w*min(1,abs(e)+.25) for e,w,_,_,_ in scored if e<0)
    agreement=max(pos,neg)/max(.001,pos+neg)
    edge=abs(norm)

    skill_den=sum(w for _,w,_,_,_ in scored) or 1
    avg_acc=sum(acc*w for _,w,_,acc,_ in scored)/skill_den

    tail=x[-48:]
    changes=sum(tail[i]!=tail[i-1] for i in range(1,len(tail)))/max(1,len(tail)-1)
    pT=tail.count("T")/len(tail)
    entropy=0 if pT in (0,1) else -(pT*_m.log2(pT)+(1-pT)*_m.log2(1-pT))
    regime=abs(changes-.5)*2

    raw=48 + max(0,avg_acc-.5)*105 + max(0,agreement-.5)*28 + edge*16 + regime*2 - entropy*1.2
    conf=int(round(clamp(raw,50,84)))

    if avg_acc<.53 or (edge<.035 and agreement<.58):
        top=sorted(scored,key=lambda z:abs(z[0]*z[1]),reverse=True)[:4]
        why="+".join(z[2] for z in top)
        return None,conf,f"ENSEMBLE LC79 V57 · {why} · SKILL {avg_acc*100:.1f}% · AG {agreement*100:.0f}% · BỎ QUA"

    side="T" if norm>=0 else "X"
    top=sorted(scored,key=lambda z:abs(z[0]*z[1]),reverse=True)[:5]
    why="+".join(f"{z[2]}:{z[3]*100:.0f}" for z in top)
    return side,conf,f"ENSEMBLE LC79 V57 · {why} · SKILL {avg_acc*100:.1f}% · AG {agreement*100:.0f}% · E {edge:.2f}"


def predict_sunwin_v57(seq):
    """SUNWIN-only adaptive engine. Input is newest-first [(sid,T/X),...]."""
    import math as _m
    newest=[x[1] for x in seq[:220] if x[1] in ("T","X")]
    if len(newest)<14:return None,0,"SUNWIN V57 · CHƯA ĐỦ DỮ LIỆU"
    x=list(reversed(newest))
    def s(v):return 1.0 if v=="T" else -1.0
    def clamp(v,a,b):return max(a,min(b,v))

    def ctx(hist,order,half=20.0):
        if len(hist)<order+7:return 0.0,0.0
        suffix=hist[-order:];a=b=.72;sup=0.0;n=len(hist)
        for i in range(order,n):
            if hist[i-order:i]==suffix:
                w=.5**((n-1-i)/half)
                if hist[i]=="T":a+=w
                else:b+=w
                sup+=w
        if sup<.16:return 0.0,0.0
        return (a-b)/(a+b),sup

    def streak(hist):
        if len(hist)<15:return 0.0,0.0
        cur=hist[-1];run=1
        for i in range(len(hist)-2,-1,-1):
            if hist[i]==cur and run<10:run+=1
            else:break
        cont=rev=.65;sup=0.0;n=len(hist)
        for i in range(2,n-1):
            r=1;j=i-1
            while j>=0 and hist[j]==hist[i] and r<10:
                r+=1;j-=1
            if hist[i]==cur and abs(r-run)<=1:
                w=.5**((n-2-i)/18.0)
                if hist[i+1]==cur:cont+=w
                else:rev+=w
                sup+=w
        if sup<.22:return 0.0,0.0
        return s(cur)*((cont-rev)/(cont+rev)),sup

    def alternating(hist):
        r=hist[-24:]
        if len(r)<10:return 0.0,0.0
        ch=sum(r[i]!=r[i-1] for i in range(1,len(r)))/(len(r)-1)
        if ch>.67:return -s(r[-1])*clamp((ch-.55)*2.3,0,1),1.0+(ch-.67)*2
        if ch<.34:return s(r[-1])*clamp((.45-ch)*2.0,0,1),.9+(.34-ch)*2
        return 0.0,.12

    def multiwindow(hist):
        parts=[]
        for w,wt in ((5,.34),(8,.25),(13,.20),(21,.13),(34,.08)):
            if len(hist)>=w:
                parts.append((sum(s(v) for v in hist[-w:])/w,wt))
        if not parts:return 0.0,0.0
        den=sum(w for _,w in parts)
        base=sum(e*w for e,w in parts)/den
        recent=sum(s(v) for v in hist[-5:])/min(5,len(hist))
        mid=sum(s(v) for v in hist[-13:])/min(13,len(hist))
        slope=recent-mid
        return clamp(base*.42+slope*.58,-1,1),.75+abs(slope)*.55

    def cycle(hist):
        y=[s(v) for v in hist];n=len(y)
        if n<22:return 0.0,0.0
        votes=[]
        for lag in range(2,min(15,n//2+1)):
            vals=[y[i]*y[i-lag] for i in range(lag,n)]
            if len(vals)<10:continue
            ac=sum(vals)/len(vals);q=abs(ac)/(lag**.30)
            if q>.09:votes.append((ac*y[-lag],q))
        if not votes:return 0.0,0.0
        den=sum(q for _,q in votes)
        return clamp(sum(e*q for e,q in votes)/den,-1,1),clamp(den/2.0,.1,1.5)

    def pair_state(hist):
        if len(hist)<16:return 0.0,0.0
        state=tuple(hist[-2:]);a=b=.75;sup=0.0;n=len(hist)
        for i in range(2,n):
            if tuple(hist[i-2:i])==state:
                w=.5**((n-1-i)/17.0)
                if hist[i]=="T":a+=w
                else:b+=w
                sup+=w
        return ((a-b)/(a+b),sup) if sup>.18 else (0.0,0.0)

    models=[]
    for o in (1,2,3,4,5):models.append((f"SW-MK{o}",lambda h,o=o:ctx(h,o,23)))
    for o in (2,3,4,5,6,7):models.append((f"SW-P{o}",lambda h,o=o:ctx(h,o,14)))
    models += [("SW-STREAK",streak),("SW-REGIME",alternating),("SW-MOM",multiwindow),
               ("SW-CYCLE",cycle),("SW-PAIR",pair_state)]

    begin=max(14,len(x)-84);perf={}
    for name,fn in models:
        hit=tot=0.0;active=0
        for i in range(begin,len(x)):
            e,sup=fn(x[:i])
            if sup<.13 or abs(e)<.035:continue
            age=len(x)-1-i
            w=.5**(age/26.0)*min(1.35,.55+sup*.30)*min(1.0,.38+abs(e))
            pred="T" if e>0 else "X"
            tot+=w;hit+=w if pred==x[i] else 0.0;active+=1
        perf[name]=((hit+2.7)/(tot+5.4) if tot else .5,tot,active)

    votes=[]
    for name,fn in models:
        e,sup=fn(x)
        if sup<.11 or abs(e)<.025:continue
        acc,tot,active=perf[name]
        sf=clamp(tot/9.0,.14,1.0);direction=1.0;skill=acc-.5;eff=acc
        if active>=11 and acc<.45:
            direction=-1.0;skill=.5-acc;eff=1-acc
        elif acc<.505:
            skill=.004;eff=.5
        weight=(.16+max(.004,skill)*5.8)*sf*clamp(.44+sup*.34,.32,1.42)
        votes.append((e*direction,weight,name,eff,tot))
    if not votes:return None,49,"SUNWIN V57 · MODEL CHƯA CÓ SUPPORT"

    den=sum(w for _,w,_,_,_ in votes) or 1
    norm=sum(e*w for e,w,_,_,_ in votes)/den
    pos=sum(w*min(1,abs(e)+.22) for e,w,_,_,_ in votes if e>0)
    neg=sum(w*min(1,abs(e)+.22) for e,w,_,_,_ in votes if e<0)
    agree=max(pos,neg)/max(.001,pos+neg);avg=sum(a*w for _,w,_,a,_ in votes)/den;edge=abs(norm)
    tail=x[-56:];changes=sum(tail[i]!=tail[i-1] for i in range(1,len(tail)))/max(1,len(tail)-1)
    p=tail.count("T")/len(tail)
    entropy=0 if p in (0,1) else -(p*_m.log2(p)+(1-p)*_m.log2(1-p))
    regime=abs(changes-.5)*2
    conf=int(round(clamp(47+max(0,avg-.5)*112+max(0,agree-.5)*30+edge*19+regime*3-entropy*1.4,49,83)))

    if avg<.525 or (edge<.032 and agree<.57):
        top=sorted(votes,key=lambda z:abs(z[0]*z[1]),reverse=True)[:4]
        return None,conf,"SUNWIN V57 · "+"+".join(z[2] for z in top)+f" · SKILL {avg*100:.1f}% · AG {agree*100:.0f}% · BỎ"
    side="T" if norm>=0 else "X"
    top=sorted(votes,key=lambda z:abs(z[0]*z[1]),reverse=True)[:5]
    why="+".join(f"{z[2]}:{z[3]*100:.0f}" for z in top)
    return side,conf,f"SUNWIN V57 · {why} · SKILL {avg*100:.1f}% · AG {agree*100:.0f}% · E {edge:.2f}"


def _v58_seq_values(seq, cap=220):
    vals=[x[1] for x in seq[:cap] if len(x)>1 and x[1] in ("T","X")]
    return list(reversed(vals))

def _v58_lc79_meta_edge(hist):
    if len(hist)<12:return 0.0,0.0
    def sg(v):return 1.0 if v=="T" else -1.0
    n=len(hist); votes=[]
    for order,half,wt in ((1,18,.75),(2,17,1.0),(3,15,1.08),(4,13,.88)):
        if n<order+6:continue
        suf=hist[-order:];a=b=.9;sup=0.0
        for i in range(order,n):
            if hist[i-order:i]==suf:
                w=.5**((n-1-i)/half)
                if hist[i]=="T":a+=w
                else:b+=w
                sup+=w
        if sup>.18:
            votes.append(((a-b)/(a+b),wt*min(1.4,.45+sup*.35)))
    cur=hist[-1];run=1
    for i in range(n-2,-1,-1):
        if hist[i]==cur and run<9:run+=1
        else:break
    cont=rev=.8;rsup=0.0
    for i in range(2,n-1):
        r=1;j=i-1
        while j>=0 and hist[j]==hist[i] and r<9:
            r+=1;j-=1
        if hist[i]==cur and abs(r-run)<=1:
            w=.5**((n-2-i)/18.0)
            if hist[i+1]==cur:cont+=w
            else:rev+=w
            rsup+=w
    if rsup>.18:
        votes.append((sg(cur)*(cont-rev)/(cont+rev), .92*min(1.35,.5+rsup*.3)))
    r=hist[-20:]
    changes=sum(r[i]!=r[i-1] for i in range(1,len(r)))/max(1,len(r)-1)
    if changes>.66:
        votes.append((-sg(r[-1])*min(1,(changes-.52)*2.1),1.06))
    elif changes<.34:
        votes.append((sg(r[-1])*min(1,(.48-changes)*2.0),1.0))
    e5=sum(sg(v) for v in hist[-5:])/min(5,n)
    e13=sum(sg(v) for v in hist[-13:])/min(13,n)
    slope=e5-e13
    if abs(slope)>.08:
        votes.append((max(-1,min(1,slope*.85+e5*.18)),.82))
    if not votes:return 0.0,0.0
    den=sum(w for _,w in votes)
    edge=sum(e*w for e,w in votes)/den
    agree=max(sum(w for e,w in votes if e>=0),sum(w for e,w in votes if e<0))/den
    return max(-1,min(1,edge)),agree

def _v58_sunwin_meta_edge(hist):
    if len(hist)<12:return 0.0,0.0
    def sg(v):return 1.0 if v=="T" else -1.0
    n=len(hist);votes=[]
    for order,half,wt in ((2,14,1.05),(3,13,1.18),(4,12,.92),(5,11,.72)):
        if n<order+6:continue
        suf=hist[-order:];a=b=.85;sup=0.0
        for i in range(order,n):
            if hist[i-order:i]==suf:
                w=.5**((n-1-i)/half)
                if hist[i]=="T":a+=w
                else:b+=w
                sup+=w
        if sup>.16:votes.append(((a-b)/(a+b),wt*min(1.45,.5+sup*.36)))
    r=hist[-24:]
    ch=sum(r[i]!=r[i-1] for i in range(1,len(r)))/max(1,len(r)-1)
    if ch>.63:votes.append((-sg(r[-1])*min(1,(ch-.50)*2.35),1.18))
    elif ch<.37:votes.append((sg(r[-1])*min(1,(.50-ch)*2.2),1.05))
    cur=hist[-1];run=1
    for i in range(n-2,-1,-1):
        if hist[i]==cur and run<10:run+=1
        else:break
    c=rvs=.75;sup=0.0
    for i in range(2,n-1):
        rr=1;j=i-1
        while j>=0 and hist[j]==hist[i] and rr<10:
            rr+=1;j-=1
        if hist[i]==cur and abs(rr-run)<=1:
            w=.5**((n-2-i)/15.0)
            if hist[i+1]==cur:c+=w
            else:rvs+=w
            sup+=w
    if sup>.15:votes.append((sg(cur)*(c-rvs)/(c+rvs),1.0*min(1.4,.52+sup*.33)))
    e4=sum(sg(v) for v in hist[-4:])/min(4,n)
    e10=sum(sg(v) for v in hist[-10:])/min(10,n)
    d=e4-e10
    if abs(d)>.10:votes.append((max(-1,min(1,d*.72+e4*.13)),.66))
    if not votes:return 0.0,0.0
    den=sum(w for _,w in votes)
    edge=sum(e*w for e,w in votes)/den
    agree=max(sum(w for e,w in votes if e>=0),sum(w for e,w in votes if e<0))/den
    return max(-1,min(1,edge)),agree

def _v58_meta_skill(hist, fn, window=72):
    if len(hist)<18:return .5,0
    begin=max(12,len(hist)-window)
    hit=tot=0.0;active=0
    for i in range(begin,len(hist)):
        e,a=fn(hist[:i])
        if abs(e)<.045 or a<.52:continue
        age=len(hist)-1-i
        w=.5**(age/24.0)*min(1.0,.45+abs(e)*.75)
        pred="T" if e>0 else "X"
        tot+=w;hit+=w if pred==hist[i] else 0.0;active+=1
    return ((hit+2.8)/(tot+5.6) if tot else .5),active

def predict_lc79_v58(seq):
    base_side,base_conf,base_reason=predict_lc79_v57(seq)
    hist=_v58_seq_values(seq)
    if len(hist)<14:return base_side,base_conf,base_reason.replace("V57","V58")
    edge,agree=_v58_lc79_meta_edge(hist)
    skill,active=_v58_meta_skill(hist,_v58_lc79_meta_edge,76)
    meta_side="T" if edge>0 else "X"
    strength=abs(edge)
    if base_side is None:
        if active>=10 and skill>=.555 and strength>=.11 and agree>=.57:
            conf=int(max(52,min(72,50+(skill-.5)*115+strength*18+(agree-.5)*10)))
            return meta_side,conf,f"LC79 V58 META · RESCUE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}% · E {strength:.2f}"
        return None,min(base_conf,64),base_reason.replace("V57","V58")
    if meta_side==base_side and active>=8:
        conf=int(max(50,min(86,base_conf+(skill-.5)*34+strength*8+(agree-.5)*5)))
        return base_side,conf,base_reason.replace("V57","V58")+f" · META {skill*100:.1f}%"
    if active>=12 and skill>=.575 and strength>=.16 and agree>=.60:
        conf=int(max(53,min(76,52+(skill-.5)*105+strength*14)))
        return meta_side,conf,f"LC79 V58 META · OVERRIDE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}% · E {strength:.2f}"
    if active>=9 and strength>=.12 and skill>=.54:
        return None,min(base_conf,67),f"LC79 V58 · BASE/META XUNG ĐỘT · META {skill*100:.1f}% · BỎ QUA"
    return base_side,max(50,min(82,base_conf-2)),base_reason.replace("V57","V58")

def predict_sunwin_v58(seq):
    base_side,base_conf,base_reason=predict_sunwin_v57(seq)
    hist=_v58_seq_values(seq)
    if len(hist)<14:return base_side,base_conf,base_reason.replace("V57","V58")
    edge,agree=_v58_sunwin_meta_edge(hist)
    skill,active=_v58_meta_skill(hist,_v58_sunwin_meta_edge,82)
    meta_side="T" if edge>0 else "X"
    strength=abs(edge)
    if base_side is None:
        if active>=9 and skill>=.55 and strength>=.105 and agree>=.56:
            conf=int(max(52,min(73,50+(skill-.5)*118+strength*18)))
            return meta_side,conf,f"SUNWIN V58 META · RESCUE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}% · E {strength:.2f}"
        return None,min(base_conf,64),base_reason.replace("V57","V58")
    if meta_side==base_side and active>=8:
        conf=int(max(50,min(86,base_conf+(skill-.5)*36+strength*8)))
        return base_side,conf,base_reason.replace("V57","V58")+f" · META {skill*100:.1f}%"
    if active>=11 and skill>=.57 and strength>=.15 and agree>=.59:
        conf=int(max(53,min(77,52+(skill-.5)*108+strength*15)))
        return meta_side,conf,f"SUNWIN V58 META · OVERRIDE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}% · E {strength:.2f}"
    if active>=9 and skill>=.54 and strength>=.115:
        return None,min(base_conf,67),f"SUNWIN V58 · BASE/META XUNG ĐỘT · META {skill*100:.1f}% · BỎ QUA"
    return base_side,max(50,min(82,base_conf-2)),base_reason.replace("V57","V58")


def _v59_empirical(hist, game="lc79"):
    if len(hist)<14:return 0.0,0.0
    def sg(v):return 1.0 if v=="T" else -1.0
    n=len(hist);votes=[]
    orders=(2,3,4,5) if game=="lc79" else (2,3,4,5,6)
    half=16.0 if game=="lc79" else 14.0
    for order in orders:
        if n<order+7:continue
        suf=hist[-order:];a=b=.8;sup=0.0
        for i in range(order,n):
            if hist[i-order:i]==suf:
                w=.5**((n-1-i)/(half-order*.35))
                if hist[i]=="T":a+=w
                else:b+=w
                sup+=w
        if sup>.15:votes.append(((a-b)/(a+b),min(1.35,.45+sup*.34)))
    r=hist[-24:];ch=sum(r[i]!=r[i-1] for i in range(1,len(r)))/max(1,len(r)-1)
    if ch>.66:votes.append((-sg(r[-1])*min(1,(ch-.52)*2.3),1.08 if game=="sunwin" else .92))
    elif ch<.34:votes.append((sg(r[-1])*min(1,(.48-ch)*2.1),1.0))
    e5=sum(sg(v) for v in hist[-5:])/min(5,n);e13=sum(sg(v) for v in hist[-13:])/min(13,n);d=e5-e13
    if abs(d)>.08:votes.append((max(-1,min(1,d*.78+e5*.14)),.72))
    if not votes:return 0.0,0.0
    den=sum(w for _,w in votes);edge=sum(e*w for e,w in votes)/den
    agree=max(sum(w for e,w in votes if e>=0),sum(w for e,w in votes if e<0))/den
    return max(-1,min(1,edge)),agree

def _v59_empirical_skill(hist,game):
    if len(hist)<22:return .5,0
    hit=tot=0.0;active=0;begin=max(14,len(hist)-88)
    for i in range(begin,len(hist)):
        e,a=_v59_empirical(hist[:i],game)
        if abs(e)<.04 or a<.52:continue
        age=len(hist)-1-i;w=.5**(age/26.0)*min(1.0,.42+abs(e)*.8)
        pred="T" if e>0 else "X";tot+=w;hit+=w if pred==hist[i] else 0;active+=1
    return ((hit+3)/(tot+6) if tot else .5),active

def _v59_merge(base_side,base_conf,base_reason,seq,game):
    hist=_v58_seq_values(seq)
    if len(hist)<16:return base_side,base_conf,base_reason.replace("V58","V59")
    edge,agree=_v59_empirical(hist,game);skill,active=_v59_empirical_skill(hist,game);side="T" if edge>=0 else "X";strength=abs(edge)
    mode=setting_int(f"{game}_algo_mode",2,1,3)
    rescue_skill={1:.565,2:.545,3:.525}[mode];rescue_edge={1:.12,2:.09,3:.06}[mode]
    conflict_skill={1:.545,2:.56,3:.585}[mode]
    if base_side is None:
        if active>=8 and skill>=rescue_skill and strength>=rescue_edge and agree>=.55:
            conf=int(max(51,min(82,50+(skill-.5)*125+strength*18+(agree-.5)*8)))
            return side,conf,f"{game.upper()} V59 · ADAPTIVE RESCUE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}%"
        return None,min(base_conf,66),base_reason.replace("V58","V59")
    if side==base_side and active>=7:
        boost=(skill-.5)*30+strength*6+(agree-.5)*4
        return base_side,int(max(50,min(88,base_conf+boost))),base_reason.replace("V58","V59")+f" · A59 {skill*100:.1f}%"
    if active>=11 and skill>=.59 and strength>=.17 and agree>=.60:
        conf=int(max(53,min(79,52+(skill-.5)*110+strength*14)))
        return side,conf,f"{game.upper()} V59 · ADAPTIVE OVERRIDE · SKILL {skill*100:.1f}% · AG {agree*100:.0f}%"
    if mode<3 and active>=9 and skill>=conflict_skill and strength>=(.12 if mode==1 else .10):
        return None,min(base_conf,68),f"{game.upper()} V59 · XUNG ĐỘT MODEL · SKILL {skill*100:.1f}% · BỎ QUA"
    return base_side,max(50,min(85,base_conf-(1 if mode==3 else 2))),base_reason.replace("V58","V59")

def predict_lc79_v59(seq):
    return _v59_merge(*predict_lc79_v58(seq),seq,"lc79")

def predict_sunwin_v59(seq):
    return _v59_merge(*predict_sunwin_v58(seq),seq,"sunwin")


# =============================================================
# V61 ENGINE — server-side only.
# LC79 V61 và SUNWIN V61 là hai engine HOÀN TOÀN ĐỘC LẬP.
# Nguyên tắc thiết kế:
#   • Nhiều HỌ model khác bản chất (Markov biến bậc, context,
#     run-length, regime, momentum đa khung, autocorrelation,
#     Bayesian transition) để giảm tương quan giữa các voter.
#   • Walk-forward validation đa horizon (20/40/80) + recency weight
#     → mỗi model có "skill" đo trên dữ liệu nó CHƯA thấy.
#   • Adaptive weighting + phát hiện model gãy (invert khi đủ bằng chứng).
#   • Bayesian smoothing + entropy meter để tránh ép dự đoán khi thuần nhiễu.
#   • `confidence` = ĐỘ MẠNH TÍN HIỆU, không phải xác suất thắng.
#   • Ít BỎ QUA hơn V59, nhưng vẫn từ chối khi tín hiệu hoàn toàn nhiễu.
# =============================================================

def _v61_clamp(v, a, b):
    return a if v < a else b if v > b else v

def _v61_sgn(v):
    return 1.0 if v == "T" else -1.0

def _v61_seq_values(seq, cap=280):
    """Newest-first [(sid, 'T'/'X'), ...] -> oldest-first list."""
    vals = [x[1] for x in seq[:cap] if len(x) > 1 and x[1] in ("T", "X")]
    return list(reversed(vals))

def _v61_entropy(hist, w=64):
    """Sequence-randomness meter in [0,1].

    Uses mostly conditional transition entropy instead of only T/X balance.
    This avoids calling a perfectly alternating T-X-T-X sequence maximum noise
    merely because it contains 50% T and 50% X.
    """
    if len(hist) < 16:
        return 0.5
    r = hist[-w:] if len(hist) >= w else hist
    p = r.count("T") / len(r)
    if p <= 0.0 or p >= 1.0:
        marginal = 0.0
    else:
        marginal = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
    trans = {"T":{"T":0.0,"X":0.0},"X":{"T":0.0,"X":0.0}}
    prev_count = {"T":0.0,"X":0.0}
    for a,b in zip(r[:-1], r[1:]):
        if a in trans and b in ("T","X"):
            trans[a][b] += 1.0
            prev_count[a] += 1.0
    total = sum(prev_count.values()) or 1.0
    cond = 0.0
    for a in ("T","X"):
        n = prev_count[a]
        if n <= 0:
            continue
        pt = trans[a]["T"] / n
        px = trans[a]["X"] / n
        h = 0.0
        if pt > 0:
            h -= pt * math.log2(pt)
        if px > 0:
            h -= px * math.log2(px)
        cond += (n / total) * h
    return _v61_clamp(cond * 0.82 + marginal * 0.18, 0.0, 1.0)

def _v61_change_rate(hist, w=48):
    r = hist[-w:] if len(hist) >= w else hist
    if len(r) < 4:
        return 0.5
    return sum(r[i] != r[i-1] for i in range(1, len(r))) / (len(r) - 1)


# ---------- FAMILY 1: Weighted Markov (order 1..6) ----------
def _v61_markov(hist, order, half_life=18.0, prior_t=0.9, prior_x=0.9):
    n = len(hist)
    if n < order + 6:
        return 0.0, 0.0
    ctx = hist[-order:]
    a, b = prior_t, prior_x
    sup = 0.0
    for i in range(order, n):
        if hist[i-order:i] == ctx:
            w = 0.5 ** ((n - 1 - i) / half_life)
            if hist[i] == "T":
                a += w
            else:
                b += w
            sup += w
    if sup < 0.14:
        return 0.0, 0.0
    return _v61_clamp((a - b) / (a + b), -1.0, 1.0), sup


# ---------- FAMILY 2: Variable-order Markov with backoff ----------
def _v61_varmarkov(hist, max_order=8, base_half=16.0):
    n = len(hist)
    if n < 14:
        return 0.0, 0.0
    contribs = []
    top = min(max_order, max(1, n - 6))
    for o in range(1, top + 1):
        hl = max(8.0, base_half - o * 0.45)
        e, sup = _v61_markov(hist, o, half_life=hl, prior_t=0.85, prior_x=0.85)
        if sup <= 0.0:
            continue
        contribs.append((e, sup * (1.0 + 0.09 * o)))
    if not contribs:
        return 0.0, 0.0
    den = sum(w for _, w in contribs)
    if den <= 0.0:
        return 0.0, 0.0
    return _v61_clamp(sum(e * w for e, w in contribs) / den, -1.0, 1.0), min(3.0, den / 2.5)


# ---------- FAMILY 3: Context pattern 1..8 ----------
def _v61_context(hist, order, half_life=13.5, prior=0.75):
    n = len(hist)
    if n < order + 6:
        return 0.0, 0.0
    ctx = hist[-order:]
    a = b = prior
    sup = 0.0
    for i in range(order, n):
        if hist[i-order:i] == ctx:
            w = 0.5 ** ((n - 1 - i) / half_life)
            if hist[i] == "T":
                a += w
            else:
                b += w
            sup += w
    if sup < 0.17:
        return 0.0, 0.0
    return _v61_clamp((a - b) / (a + b), -1.0, 1.0), sup * (1.0 + 0.06 * order)


# ---------- FAMILY 4: Run-length transition ----------
def _v61_run(hist, max_run=10, half_life=17.0, min_sup=0.18):
    n = len(hist)
    if n < 14:
        return 0.0, 0.0
    cur = hist[-1]
    run = 1
    for i in range(n - 2, -1, -1):
        if hist[i] == cur and run < max_run:
            run += 1
        else:
            break
    cont = rev = 0.7
    sup = 0.0
    for i in range(2, n - 1):
        r = 1
        j = i - 1
        while j >= 0 and hist[j] == hist[i] and r < max_run:
            r += 1
            j -= 1
        if hist[i] == cur and abs(r - run) <= 1:
            w = 0.5 ** ((n - 2 - i) / half_life)
            if hist[i + 1] == cur:
                cont += w
            else:
                rev += w
            sup += w
    if sup < min_sup:
        return 0.0, 0.0
    edge = _v61_sgn(cur) * (cont - rev) / (cont + rev)
    return _v61_clamp(edge, -1.0, 1.0), sup


# ---------- FAMILY 5: Alternation / bệt regime ----------
def _v61_alternation(hist, windows=((20, 1.0), (40, 0.85), (80, 0.70)), hi=0.66, lo=0.34):
    n = len(hist)
    if n < 16:
        return 0.0, 0.0
    votes = []
    for w, wt in windows:
        r = hist[-w:] if n >= w else hist
        if len(r) < 8:
            continue
        ch = sum(r[i] != r[i-1] for i in range(1, len(r))) / (len(r) - 1)
        if ch > hi:
            e = -_v61_sgn(r[-1]) * _v61_clamp((ch - 0.5) * 2.4, 0.0, 1.0)
            votes.append((e, wt * (1.0 + (ch - hi) * 2.0)))
        elif ch < lo:
            e = _v61_sgn(r[-1]) * _v61_clamp((0.5 - ch) * 2.2, 0.0, 1.0)
            votes.append((e, wt * (1.0 + (lo - ch) * 2.0)))
        else:
            votes.append((0.0, wt * 0.15))
    if not votes:
        return 0.0, 0.0
    den = sum(w for _, w in votes)
    if den <= 0.0:
        return 0.0, 0.0
    return _v61_clamp(sum(e * w for e, w in votes) / den, -1.0, 1.0), den / 2.0


# ---------- FAMILY 6: Multi-window momentum ----------
def _v61_momentum(hist):
    n = len(hist)
    if n < 12:
        return 0.0, 0.0
    parts = []
    for w, wt in ((5, 0.30), (9, 0.24), (15, 0.18), (27, 0.16), (40, 0.12)):
        if n >= w:
            r = hist[-w:]
            parts.append((sum(_v61_sgn(v) for v in r) / w, wt))
    if not parts:
        return 0.0, 0.0
    den = sum(w for _, w in parts)
    base = sum(e * w for e, w in parts) / den
    r5 = sum(_v61_sgn(v) for v in hist[-5:]) / min(5, n)
    r15 = sum(_v61_sgn(v) for v in hist[-15:]) / min(15, n)
    slope = r5 - r15
    return _v61_clamp(base * 0.45 + slope * 0.55, -1.0, 1.0), 0.70 + abs(slope) * 0.55


# ---------- FAMILY 7: Autocorrelation / cycle ----------
def _v61_cycle(hist, max_lag=15):
    n = len(hist)
    if n < 20:
        return 0.0, 0.0
    y = [_v61_sgn(v) for v in hist]
    votes = []
    for lag in range(2, min(max_lag + 1, n // 2 + 1)):
        vals = [y[i] * y[i - lag] for i in range(lag, n)]
        if len(vals) < 8:
            continue
        ac = sum(vals) / len(vals)
        q = abs(ac) / (lag ** 0.28)
        if q > 0.09:
            votes.append((ac * y[-lag], q))
    if not votes:
        return 0.0, 0.0
    den = sum(q for _, q in votes)
    if den <= 0.0:
        return 0.0, 0.0
    return _v61_clamp(sum(e * q for e, q in votes) / den, -1.0, 1.0), _v61_clamp(den / 2.2, 0.1, 1.5)


# ---------- FAMILY 8: Bayesian transition ----------
def _v61_bayes(hist, order=2, alpha=1.2, half_life=20.0, min_sup=0.20):
    n = len(hist)
    if n < order + 5:
        return 0.0, 0.0
    ctx = hist[-order:]
    ct, cx = alpha, alpha
    sup = 0.0
    for i in range(order, n):
        if hist[i-order:i] == ctx:
            w = 0.5 ** ((n - 1 - i) / half_life)
            if hist[i] == "T":
                ct += w
            else:
                cx += w
            sup += w
    if sup < min_sup:
        return 0.0, 0.0
    return _v61_clamp((ct - cx) / (ct + cx), -1.0, 1.0), sup


# ---------- Walk-forward validation (multi-horizon) ----------
def _v61_walkforward(hist, fn, horizons=(20, 40, 80), prior_a=2.8, prior_b=5.6):
    """
    Trả về list [(H, acc, tot, active)] — mỗi horizon một entry.
    `acc` đã được Beta-shrink để tránh mẫu nhỏ trông ảo.
    """
    n = len(hist)
    out = []
    for H in horizons:
        begin = max(12, n - H)
        hit = tot = 0.0
        active = 0
        for i in range(begin, n):
            try:
                e, sup = fn(hist[:i])
            except Exception:
                continue
            if abs(e) < 0.04 or sup < 0.13:
                continue
            age = n - 1 - i
            w = 0.5 ** (age / 26.0) * min(1.0, 0.45 + abs(e) * 0.85)
            pred = "T" if e > 0 else "X"
            tot += w
            if pred == hist[i]:
                hit += w
            active += 1
        acc = (hit + prior_a) / (tot + prior_b) if tot > 0 else 0.5
        out.append((H, acc, tot, active))
    return out


# ---------- Shared ensemble framework; LC79/SUNWIN use separate candidate sets ----------
_V61_HORIZONS = ((20, 0.45), (40, 0.35), (80, 0.20))

def _v61_coverage_fallback(hist, prefix="V61"):
    """Best-effort side used only when the rolling skip budget is exhausted.
    This increases prediction coverage; it is not a claim of higher accuracy.
    """
    if not hist:
        return "T", 50, f"{prefix} · COVERAGE FALLBACK · KHÔNG ĐỦ DỮ LIỆU"
    recent = hist[-24:]
    last = recent[-1]
    if len(recent) >= 3:
        changes = sum(1 for a,b in zip(recent[:-1], recent[1:]) if a != b)
        change_rate = changes / max(1, len(recent)-1)
        side = ("X" if last == "T" else "T") if change_rate >= 0.54 else last
        strength = abs(change_rate - 0.5)
        conf = int(round(_v61_clamp(50 + strength * 28, 50, 56)))
        return side, conf, f"{prefix} · COVERAGE FALLBACK · CR {change_rate:.2f}"
    return last, 50, f"{prefix} · COVERAGE FALLBACK · RECENT"

def _v61_ensemble(hist, candidates, mode=2, prefix="V61", force=False):
    """
    candidates: dict {name: callable(hist) -> (edge, support)}.
    mode: 1 = conservative (ít đoán hơn), 2 = balanced, 3 = aggressive (ít BỎ QUA).
    Trả về (side, confidence, reason). Confidence = độ mạnh tín hiệu.
    """
    if len(hist) < 14:
        if force:
            return _v61_coverage_fallback(hist, prefix)
        return None, 48, f"{prefix} · CHƯA ĐỦ DỮ LIỆU · BỎ QUA"

    scored = []
    for name, fn in candidates.items():
        try:
            e, sup = fn(hist)
        except Exception:
            continue
        if sup <= 0.10 or abs(e) < 0.022:
            continue

        per_h = _v61_walkforward(hist, fn, horizons=(20, 40, 80))
        w_sum = 0.0
        skill_num = 0.0
        effective_active = 0
        for (_, horizon_weight), (_, acc, tot, active) in zip(_V61_HORIZONS, per_h):
            sf = _v61_clamp(tot / 8.0, 0.10, 1.0)
            ww = horizon_weight * sf
            w_sum += ww
            skill_num += ww * (acc - 0.5)
            effective_active = max(effective_active, active)
        if w_sum <= 0.0:
            continue
        skill = 0.5 + skill_num / w_sum

        # Quarantine models that are clearly broken recently instead of
        # automatically inverting them (which can amplify short-lived noise).
        acc20 = per_h[0][1] if len(per_h) > 0 else 0.5
        acc40 = per_h[1][1] if len(per_h) > 1 else acc20
        if effective_active >= 12 and skill < 0.465 and acc20 < 0.47 and acc40 < 0.48:
            continue

        eff_skill = skill if skill >= 0.502 else 0.5
        strength = max(0.005, eff_skill - 0.5)
        weight = (
            (0.18 + strength * 5.5)
            * _v61_clamp(w_sum, 0.15, 1.0)
            * _v61_clamp(0.45 + sup * 0.35, 0.32, 1.4)
        )
        scored.append((e, weight, name, eff_skill, sup, effective_active))

    if not scored:
        if force:
            return _v61_coverage_fallback(hist, prefix)
        return None, 50, f"{prefix} · ENSEMBLE KHÔNG CÓ MODEL ĐỦ SUPPORT · BỎ QUA"

    # Cap correlated model families so many near-duplicate Markov/context
    # voters cannot manufacture artificial agreement/confidence.
    def _family(name):
        if name.startswith("MK") or name == "VOM" or name.startswith("BAYES"):
            return "TRANSITION"
        if name.startswith("CTX"):
            return "CONTEXT"
        if name == "PAIR":
            return "PAIR"
        return name
    fam_totals = {}
    for _, w, name, _, _, _ in scored:
        fam = _family(name)
        fam_totals[fam] = fam_totals.get(fam, 0.0) + w
    decorrelated = []
    family_cap = 1.15
    for e, w, name, sk, sup, active in scored:
        total = fam_totals.get(_family(name), w) or w
        scale = min(1.0, family_cap / total)
        decorrelated.append((e, w * scale, name, sk, sup, active))
    scored = decorrelated

    den = sum(w for _, w, _, _, _, _ in scored) or 1.0
    norm = sum(e * w for e, w, _, _, _, _ in scored) / den
    pos = sum(w * min(1.0, abs(e) + 0.22) for e, w, _, _, _, _ in scored if e > 0)
    neg = sum(w * min(1.0, abs(e) + 0.22) for e, w, _, _, _, _ in scored if e < 0)
    agreement = max(pos, neg) / max(0.001, pos + neg)
    edge = abs(norm)
    avg_skill = sum(w * s for _, w, _, s, _, _ in scored) / den

    ent = _v61_entropy(hist)
    cr = _v61_change_rate(hist, 48)
    regime = abs(cr - 0.5) * 2.0

    # Ngưỡng skip theo mode — aggressive ít BỎ QUA hơn conservative.
    if mode == 1:
        skip_skill, skip_edge, skip_agreement = 0.528, 0.038, 0.575
    elif mode == 3:
        skip_skill, skip_edge, skip_agreement = 0.500, 0.020, 0.525
    else:
        skip_skill, skip_edge, skip_agreement = 0.515, 0.028, 0.550

    forced_coverage = False
    if avg_skill < skip_skill and (edge < skip_edge or agreement < skip_agreement):
        top = sorted(scored, key=lambda z: abs(z[0] * z[1]), reverse=True)[:4]
        why = "+".join(z[2] for z in top)
        conf = int(round(_v61_clamp(
            47 + max(0.0, avg_skill - 0.5) * 115 + edge * 16 - ent * 1.2,
            50, 74
        )))
        if not force:
            return None, conf, f"{prefix} · {why} · SKILL {avg_skill*100:.1f}% · AG {agreement*100:.0f}% · BỎ QUA"
        forced_coverage = True

    # Confidence calibration: độ mạnh tín hiệu, không fake win-prob.
    raw = (
        47
        + max(0.0, avg_skill - 0.5) * 115
        + max(0.0, agreement - 0.5) * 26
        + edge * 16
        + regime * 2.5
        - ent * 1.5
    )
    conf = int(round(_v61_clamp(raw, 50, 86)))

    side = "T" if norm >= 0 else "X"
    top = sorted(scored, key=lambda z: abs(z[0] * z[1]), reverse=True)[:5]
    why = "+".join(f"{z[2]}:{z[3]*100:.0f}" for z in top)
    coverage_tag = " · COVERAGE FORCE" if forced_coverage else ""
    return side, conf, f"{prefix} · {why} · SKILL {avg_skill*100:.1f}% · AG {agreement*100:.0f}% · E {edge:.2f}{coverage_tag}"


# =============================================================
# LC79 V61 candidates (HŨ + MD5 dùng chung engine này)
# =============================================================
def _v61_lc79_candidates():
    c = {}
    # Weighted Markov bậc 1..6
    for o in (1, 2, 3, 4, 5, 6):
        c[f"MK{o}"] = (lambda h, o=o: _v61_markov(h, o, half_life=max(9.0, 19.0 - o * 0.5)))
    # Variable-order Markov backoff
    c["VOM"] = (lambda h: _v61_varmarkov(h, max_order=8, base_half=16.0))
    # Context pattern 2..8
    for o in (2, 3, 4, 5, 6, 7, 8):
        c[f"CTX{o}"] = (lambda h, o=o: _v61_context(h, o, half_life=max(8.5, 13.5 - o * 0.3)))
    # Run-length transition
    c["RUN"] = (lambda h: _v61_run(h, max_run=10))
    # Alternation / bệt regime
    c["REGIME"] = (lambda h: _v61_alternation(h, ((20, 1.0), (40, 0.85), (80, 0.70))))
    # Multi-window momentum
    c["MOM"] = _v61_momentum
    # Autocorrelation / cycle
    c["CYCLE"] = (lambda h: _v61_cycle(h, max_lag=15))
    # Bayesian transition
    c["BAYES2"] = (lambda h: _v61_bayes(h, order=2, alpha=1.2))
    c["BAYES3"] = (lambda h: _v61_bayes(h, order=3, alpha=1.2))
    return c


# =============================================================
# SUNWIN V61 candidates — ĐỘC LẬP với LC79, không copy model LC79.
#   • Ưu tiên pattern pair/triple/4-6 phiên.
#   • Bệt / 1-1 / 2-1 / 2-2 regime qua lag-2 và lag-3.
#   • Markov 1..6 nhưng half-life riêng.
#   • Bayesian order 2/3/4 riêng.
# =============================================================
def _v61_sun_pair_triple(hist):
    n = len(hist)
    if n < 12:
        return 0.0, 0.0
    contribs = []
    for o, bw in ((2, 1.35), (3, 1.20), (4, 1.05), (5, 0.88), (6, 0.72), (7, 0.60), (8, 0.50)):
        if n < o + 6:
            continue
        ctx = hist[-o:]
        a = b = 0.75
        sup = 0.0
        hl = max(8.5, 13.5 - o * 0.5)
        for i in range(o, n):
            if hist[i-o:i] == ctx:
                w = 0.5 ** ((n - 1 - i) / hl)
                if hist[i] == "T":
                    a += w
                else:
                    b += w
                sup += w
        if sup < 0.15:
            continue
        e = (a - b) / (a + b)
        contribs.append((e, bw * _v61_clamp(0.55 + sup * 0.35, 0.35, 1.5)))
    if not contribs:
        return 0.0, 0.0
    den = sum(w for _, w in contribs)
    if den <= 0.0:
        return 0.0, 0.0
    return _v61_clamp(sum(e * w for e, w in contribs) / den, -1.0, 1.0), min(2.5, den / 2.5)


def _v61_sun_regime(hist):
    """Bệt / 1-1 / 2-1 / 2-2 rhythm detection."""
    n = len(hist)
    if n < 16:
        return 0.0, 0.0
    votes = []

    # Multi-window change rate → bệt vs 1-1
    for w, wt in ((16, 1.05), (28, 0.95), (48, 0.75)):
        r = hist[-w:] if n >= w else hist
        if len(r) < 8:
            continue
        ch = sum(r[i] != r[i-1] for i in range(1, len(r))) / (len(r) - 1)
        if ch < 0.34:
            e = _v61_sgn(r[-1]) * _v61_clamp((0.5 - ch) * 2.2, 0.0, 1.0)
            votes.append((e, wt * (1.0 + (0.34 - ch) * 2.2)))
        elif ch > 0.66:
            e = -_v61_sgn(r[-1]) * _v61_clamp((ch - 0.5) * 2.4, 0.0, 1.0)
            votes.append((e, wt * (1.0 + (ch - 0.66) * 2.2)))
        else:
            votes.append((0.0, wt * 0.12))

    # 2-2 rhythm (lag-2 self-correlation cao/thấp)
    if n >= 22:
        r = hist[-26:]
        m = len(r)
        agree2 = sum(1 for i in range(2, m) if r[i] == r[i-2]) / (m - 2)
        if agree2 > 0.66:
            pred_same = r[-2]
            votes.append((_v61_sgn(pred_same) * _v61_clamp((agree2 - 0.55) * 2.5, 0.0, 1.0), 1.15))
        elif agree2 < 0.34:
            pred_opp = "X" if r[-2] == "T" else "T"
            votes.append((_v61_sgn(pred_opp) * _v61_clamp((0.5 - agree2) * 2.4, 0.0, 1.0), 1.10))

    # 2-1 rhythm: (a,a,b) — lag-3 same, lag-1 khác lag-2
    if n >= 24:
        r = hist[-30:]
        m = len(r)
        agree3 = sum(1 for i in range(3, m) if r[i] == r[i-3]) / (m - 3)
        if agree3 > 0.62 and r[-1] != r[-2]:
            pred = r[-3]
            votes.append((_v61_sgn(pred) * _v61_clamp((agree3 - 0.55) * 2.0, 0.0, 1.0), 0.90))

    if not votes:
        return 0.0, 0.0
    den = sum(w for _, w in votes)
    if den <= 0.0:
        return 0.0, 0.0
    return _v61_clamp(sum(e * w for e, w in votes) / den, -1.0, 1.0), den / 2.4


def _v61_sun_momentum(hist):
    n = len(hist)
    if n < 10:
        return 0.0, 0.0
    parts = []
    for w, wt in ((4, 0.34), (7, 0.26), (12, 0.20), (20, 0.12), (32, 0.08)):
        if n >= w:
            r = hist[-w:]
            parts.append((sum(_v61_sgn(v) for v in r) / w, wt))
    if not parts:
        return 0.0, 0.0
    den = sum(w for _, w in parts)
    base = sum(e * w for e, w in parts) / den
    r4 = sum(_v61_sgn(v) for v in hist[-4:]) / min(4, n)
    r12 = sum(_v61_sgn(v) for v in hist[-12:]) / min(12, n)
    slope = r4 - r12
    return _v61_clamp(base * 0.40 + slope * 0.60, -1.0, 1.0), 0.72 + abs(slope) * 0.60


def _v61_sun_run(hist, max_run=12):
    return _v61_run(hist, max_run=max_run, half_life=15.0, min_sup=0.16)


def _v61_sun_bayes(hist, order=3, alpha=1.0, half_life=15.0):
    return _v61_bayes(hist, order=order, alpha=alpha, half_life=half_life, min_sup=0.20)


def _v61_sunwin_candidates():
    c = {}
    # Pattern ưu tiên pair/triple/4-6
    c["PAIR"] = _v61_sun_pair_triple
    # Markov 1..6 half-life riêng
    for o in (1, 2, 3, 4, 5, 6):
        c[f"MK{o}"] = (lambda h, o=o: _v61_markov(
            h, o, half_life=max(8.5, 17.0 - o * 0.6), prior_t=0.8, prior_x=0.8
        ))
    # Context 2..8
    for o in (2, 3, 4, 5, 6, 7, 8):
        c[f"CTX{o}"] = (lambda h, o=o: _v61_context(
            h, o, half_life=max(8.0, 12.5 - o * 0.4), prior=0.7
        ))
    # Run-length, regime, momentum, cycle, Bayesian
    c["RUN"] = (lambda h: _v61_sun_run(h, max_run=12))
    c["REGIME"] = _v61_sun_regime
    c["MOM"] = _v61_sun_momentum
    c["CYCLE"] = (lambda h: _v61_cycle(h, max_lag=14))
    c["BAYES2"] = (lambda h: _v61_sun_bayes(h, order=2, alpha=1.0))
    c["BAYES3"] = (lambda h: _v61_sun_bayes(h, order=3, alpha=1.0))
    c["BAYES4"] = (lambda h: _v61_sun_bayes(h, order=4, alpha=1.0))
    return c



# =============================================================
# V68 MAX ENGINE — RLE SHAPE + MULTI-HYPOTHESIS + FAMILY ENSEMBLE
# =============================================================
# Tài liệu pattern của user được dùng như một thư viện giả thuyết:
#   RLE / a-b / a-b-c / chu kỳ / đối xứng / số học / Fibonacci / gãy-bẻ-chuyền.
# Mỗi hypothesis PHẢI qua walk-forward trước khi có trọng số. Confidence bên dưới
# là độ mạnh tín hiệu tương đối, KHÔNG phải xác suất thắng được đảm bảo.


def _v68_rle(hist):
    if not hist:
        return []
    out=[]
    cur=hist[0]
    count=1
    for x in hist[1:]:
        if x==cur:
            count+=1
        else:
            out.append((cur,count))
            cur=x; count=1
    out.append((cur,count))
    return out


def _v68_fit_rhythm(hist, max_period=5, max_runs=26):
    """Fit a repeating run-length rhythm (a-b, a-b-c, ...).

    Current unfinished run is NOT used for fitting, so a partially formed run
    cannot manufacture its own target. Recent completed runs get more weight.
    """
    runs=_v68_rle(hist)
    if len(runs)<7:
        return None
    cur_side,cur_len=runs[-1]
    comp=[min(14,int(n)) for _,n in runs[:-1]][-max_runs:]
    m=len(comp)
    if m<6:
        return None
    best=None
    for k in range(1,min(max_period,m//2)+1):
        if m < k*2+1:
            continue
        pat=comp[-k:]
        anchor=m-k
        num=den=0.0
        exact=0.0
        for i,v in enumerate(comp):
            exp=pat[(i-anchor)%k]
            d=abs(v-exp)
            sim=1.0 if d==0 else 0.58 if d==1 else 0.22 if d==2 else 0.0
            age=m-1-i
            w=0.5**(age/10.0)
            num += sim*w
            den += w
            if d==0:
                exact += w
        if den<=0:
            continue
        similarity=num/den
        exact_rate=exact/den
        cycles=m/k
        # Penalize very long rhythm patterns unless they repeat enough.
        quality=similarity*(0.72+0.28*exact_rate)*min(1.0,cycles/2.7)*(1.0-0.035*(k-1))
        if best is None or quality>best['quality']:
            best={
                'period':k,'pattern':pat,'quality':quality,'similarity':similarity,
                'exact_rate':exact_rate,'cycles':cycles,'expected':pat[0],
                'current_side':cur_side,'current_len':cur_len,
            }
    if not best or best['quality']<0.44:
        return None
    return best


def _v68_rhythm(hist):
    p=_v68_fit_rhythm(hist)
    if not p:
        return 0.0,0.0
    q=p['quality']; target=max(1,p['expected']); cur=p['current_len']; side=p['current_side']
    # Expected run not complete yet -> continuation. At/over target -> reversal.
    if cur < target:
        direction=_v61_sgn(side)
        gap=target-cur
        mag=_v61_clamp(0.26 + q*0.58 + min(3,gap)*0.035,0.0,0.94)
    else:
        direction=-_v61_sgn(side)
        over=max(0,cur-target)
        # Once pattern is exceeded, rapidly reduce confidence rather than blindly flip.
        decay=max(0.35,1.0-over*0.20)
        mag=_v61_clamp((0.34+q*0.62)*decay,0.0,0.95)
    support=_v61_clamp(q*(0.65+min(2.2,p['cycles']/2.0)),0.12,2.3)
    return direction*mag,support


def _v68_shape_target(hist):
    """Low-priority run-shape hypotheses: arithmetic / Fibonacci / geometric."""
    runs=_v68_rle(hist)
    if len(runs)<7:
        return None
    comp=[int(n) for _,n in runs[:-1]][-8:]
    cur_side,cur_len=runs[-1]
    candidates=[]
    # Arithmetic shape: 1-2-3-4..., 5-4-3-2...
    if len(comp)>=5:
        a=comp[-5:]
        dif=[a[i]-a[i-1] for i in range(1,len(a))]
        mean=sum(dif)/len(dif)
        var=sum((d-mean)**2 for d in dif)/len(dif)
        sd=math.sqrt(var)
        if 0.65<=abs(mean)<=3.2 and sd<=0.82:
            target=int(round(_v61_clamp(a[-1]+mean,1,14)))
            score=_v61_clamp(0.82-sd*0.35+min(0.16,abs(mean)*0.035),0.35,0.90)
            candidates.append(('ARITH',target,score))
    # Fibonacci-like shape. Kept low-priority; walk-forward decides whether it survives.
    if len(comp)>=5:
        a=comp[-5:]
        errs=[abs(a[i]-(a[i-1]+a[i-2])) for i in range(2,5)]
        e=sum(errs)/len(errs)
        if e<=0.75:
            target=int(_v61_clamp(a[-1]+a[-2],1,14))
            candidates.append(('FIB',target,_v61_clamp(0.70-e*0.25,0.32,0.72)))
    # Geometric-ish 1-2-4-8, but only if ratios are stable and values remain sane.
    if len(comp)>=4 and all(x>0 for x in comp[-4:]):
        a=comp[-4:]
        ratios=[a[i]/a[i-1] for i in range(1,4)]
        mr=sum(ratios)/3
        sd=math.sqrt(sum((r-mr)**2 for r in ratios)/3)
        if 1.45<=mr<=2.35 and sd<=0.24:
            target=int(round(_v61_clamp(a[-1]*mr,1,14)))
            candidates.append(('GEO',target,_v61_clamp(0.62-sd*0.8,0.30,0.64)))
    if not candidates:
        return None
    name,target,score=max(candidates,key=lambda z:z[2])
    return {'name':name,'target':target,'score':score,'current_side':cur_side,'current_len':cur_len}


def _v68_shape(hist):
    p=_v68_shape_target(hist)
    if not p:
        return 0.0,0.0
    same=p['current_len'] < p['target']
    direction=_v61_sgn(p['current_side']) if same else -_v61_sgn(p['current_side'])
    overshoot=max(0,p['current_len']-p['target'])
    mag=(0.26+p['score']*0.52)*max(0.38,1.0-overshoot*0.22)
    return direction*_v61_clamp(mag,0.0,0.82), _v61_clamp(p['score']*0.95,0.12,0.85)



def _v68_sequence_entropy(hist,max_order=3):
    """Smoothed multi-order conditional entropy in [0,1].

    Unlike marginal 50/50 entropy, this recognizes deterministic 2-2 / 1-2 /
    higher-order rhythms when the next symbol is predictable from context.
    """
    if len(hist)<18:
        return _v61_entropy(hist)
    vals=[]
    for order in range(1,max_order+1):
        if len(hist)<order+12:
            continue
        counts={}
        for i in range(order,len(hist)):
            ctx=tuple(hist[i-order:i])
            d=counts.setdefault(ctx,[0.0,0.0])
            if hist[i]=='T': d[0]+=1.0
            else: d[1]+=1.0
        total_obs=sum(a+b for a,b in counts.values()) or 1.0
        h=0.0
        alpha=0.55
        for a,b in counts.values():
            n=a+b
            pt=(a+alpha)/(n+2*alpha); px=1.0-pt
            hh=0.0
            if pt>0: hh-=pt*math.log2(pt)
            if px>0: hh-=px*math.log2(px)
            h += (n/total_obs)*hh
        # Small complexity penalty prevents order-3 from overfitting random samples.
        vals.append(_v61_clamp(h+0.035*(order-1),0.0,1.0))
    if not vals:
        return _v61_entropy(hist)
    marginal=_v61_entropy(hist)
    return _v61_clamp(min(vals)*0.88 + marginal*0.12,0.0,1.0)


def _v68_change_point(hist):
    if len(hist)<32:
        return 0.20
    r=hist[-32:]
    a,b=r[:16],r[16:]
    pa=a.count('T')/len(a); pb=b.count('T')/len(b)
    ca=sum(a[i]!=a[i-1] for i in range(1,len(a)))/(len(a)-1)
    cb=sum(b[i]!=b[i-1] for i in range(1,len(b)))/(len(b)-1)
    # Also compare recent run-size level to prior run-size level.
    rr=_v68_rle(r)
    lens=[x[1] for x in rr]
    run_shift=0.0
    if len(lens)>=6:
        mid=len(lens)//2
        x=lens[:mid]; y=lens[mid:]
        if x and y:
            mx=sum(x)/len(x); my=sum(y)/len(y)
            run_shift=min(1.0,abs(my-mx)/max(1.0,(mx+my)/2))
    return _v61_clamp(abs(pb-pa)*0.46 + abs(cb-ca)*0.40 + run_shift*0.14,0.0,1.0)


def _v68_break_transition(hist):
    """Conservative regime-transition detector.

    Important: a long run is NOT evidence that a reversal is due.  The old
    implementation treated run "fatigue" as a break signal, which could make
    the ensemble flip after an otherwise healthy streak.  This version only
    emits a transition vote when the change-rate shift is confirmed across
    multiple adjacent windows and the global change-point score agrees.
    """
    if len(hist)<42:
        return 0.0,0.0
    cur_side=hist[-1]

    # Three non-overlapping recent windows. A transition must persist through
    # both steps; one noisy result cannot create a break vote by itself.
    a=hist[-42:-28]
    b=hist[-28:-14]
    c=hist[-14:]
    def cr(x):
        return sum(x[i]!=x[i-1] for i in range(1,len(x)))/max(1,len(x)-1)
    ca,cb,cc=cr(a),cr(b),cr(c)
    d1=cb-ca; d2=cc-cb
    cp=_v68_change_point(hist)

    # Require the two sequential shifts to point in the same direction.
    same_up=d1>0.075 and d2>0.075
    same_down=d1<-0.075 and d2<-0.075
    if not (same_up or same_down) or cp<0.34:
        return 0.0,0.0

    # Larger confirmed movement -> stronger signal, but deliberately capped.
    magnitude=min(1.0,(abs(d1)+abs(d2))/0.42)
    support=_v61_clamp(0.18+cp*0.52+magnitude*0.22,0.16,0.76)
    edge_mag=_v61_clamp(0.10+magnitude*0.34+max(0.0,cp-0.34)*0.28,0.10,0.52)

    # Rising change-rate suggests a more alternating regime; falling rate
    # suggests a more persistent regime. This is regime evidence, not a
    # gambler's-fallacy "run is long so it must break" rule.
    direction=-_v61_sgn(cur_side) if same_up else _v61_sgn(cur_side)
    return direction*edge_mag,support


def _v68_chi_bias(hist,w=56):
    """Weak distribution-bias hypothesis (chi-square spirit), always walk-forward gated."""
    if len(hist)<20:
        return 0.0,0.0
    r=hist[-w:] if len(hist)>=w else hist
    n=len(r); t=r.count('T'); x=n-t
    if n<=0:
        return 0.0,0.0
    chi=((t-n/2)**2+(x-n/2)**2)/(n/2)
    if chi<1.05:
        return 0.0,0.0
    direction=1.0 if t>x else -1.0
    mag=_v61_clamp((chi-1.0)/7.0,0.0,0.52)
    return direction*mag,_v61_clamp(chi/4.5,0.12,1.1)


def _v68_family(name):
    if name.startswith('MK') or name=='VOM' or name.startswith('BAYES'):
        return 'TRANSITION'
    if name.startswith('CTX') or name=='PAIR':
        return 'CONTEXT'
    if name=='RHYTHM':
        return 'RLE-RHYTHM'
    if name=='SHAPE':
        return 'RLE-SHAPE'
    if name=='BREAK':
        return 'BREAKPOINT'
    if name=='RUN':
        return 'RUN-STATE'
    if name=='REGIME':
        return 'REGIME'
    if name=='CYCLE':
        return 'CYCLE'
    if name=='MOM':
        return 'MOMENTUM'
    if name=='CHI':
        return 'DISTRIBUTION'
    return name


def _v68_diagnostics(hist):
    p=_v68_fit_rhythm(hist)
    ent=_v68_sequence_entropy(hist)
    cp=_v68_change_point(hist)
    cr=_v61_change_rate(hist,48)
    if p and p['quality']>=0.52:
        pattern='RLE '+('-'.join(str(x) for x in p['pattern']))
        clarity=p['quality']
    elif cr>=0.72:
        pattern='SO LE / 1-1'
        clarity=min(1.0,(cr-0.5)*2)
    elif cr<=0.28:
        pattern='BỆT / RUN'
        clarity=min(1.0,(0.5-cr)*2)
    else:
        pattern='HỖN HỢP'
        clarity=max(0.0,1.0-ent)
    if cp>=0.48:
        regime='CHUYỂN PHA'
    elif ent>=0.82 and clarity<0.45:
        regime='NHIỄU CAO'
    elif clarity>=0.66:
        regime='CẦU RÕ'
    elif clarity>=0.42:
        regime='CẦU MỜ'
    else:
        regime='TRUNG TÍNH'
    return {
        'pattern':pattern,
        'regime':regime,
        'noise':int(round(ent*100)),
        'break_score':int(round(cp*100)),
        'clarity':int(round(_v61_clamp(clarity,0,1)*100)),
    }


def _v68_ensemble(hist,candidates,mode=2,prefix='V68 MAX',force=False):
    if len(hist)<16:
        if force:
            return _v61_coverage_fallback(hist,prefix)
        return None,48,f'{prefix} · CHƯA ĐỦ DỮ LIỆU · BỎ QUA'

    horizon_spec=((24,0.50),(48,0.32),(96,0.18))
    models=[]
    for name,fn in candidates.items():
        try:
            edge,sup=fn(hist)
        except Exception:
            continue
        if sup<=0.10 or abs(edge)<0.020:
            continue
        per_h=_v61_walkforward(hist,fn,horizons=tuple(x[0] for x in horizon_spec),prior_a=3.0,prior_b=6.0)
        den_h=skill_num=0.0; active=0
        for (_,hw),(_,acc,tot,act) in zip(horizon_spec,per_h):
            sf=_v61_clamp(tot/7.0,0.10,1.0)
            ww=hw*sf
            den_h+=ww; skill_num+=ww*(acc-0.5); active=max(active,act)
        if den_h<=0:
            continue
        skill=0.5+skill_num/den_h
        acc24=per_h[0][1] if per_h else 0.5
        acc48=per_h[1][1] if len(per_h)>1 else acc24
        # Quarantine recent underperformers. Do not auto-invert losing models.
        if active>=12 and skill<0.466 and acc24<0.468 and acc48<0.480:
            continue
        if active>=8 and skill<0.492:
            continue
        recent_factor=_v61_clamp(active/14.0,0.25,1.0)
        skill_edge=max(0.0,skill-0.5)
        weight=(0.11+skill_edge*7.5)*_v61_clamp(0.38+sup*0.36,0.28,1.45)*(0.62+0.38*recent_factor)
        models.append((edge,weight,name,max(0.5,skill),sup,active))

    if not models:
        if force:
            return _v61_coverage_fallback(hist,prefix)
        return None,50,f'{prefix} · KHÔNG CÓ MODEL ĐỦ SUPPORT · BỎ QUA'

    # Collapse correlated models into ONE vote per family.
    fam={}
    for e,w,name,sk,sup,act in models:
        f=_v68_family(name)
        z=fam.setdefault(f,[]); z.append((e,w,name,sk,sup,act))
    families=[]
    for fname,items in fam.items():
        dw=sum(x[1] for x in items) or 1.0
        fe=sum(x[0]*x[1] for x in items)/dw
        fs=sum(x[3]*x[1] for x in items)/dw
        fact=max(x[5] for x in items)
        support=sum(min(1.0,x[4]) for x in items)/len(items)
        fw=(0.17+max(0.0,fs-0.5)*8.0)*_v61_clamp(0.52+support*0.52,0.38,1.15)*_v61_clamp(fact/12.0,0.35,1.0)
        families.append((fe,fw,fname,fs,support,fact))

    den=sum(x[1] for x in families) or 1.0
    norm=sum(x[0]*x[1] for x in families)/den
    pos=sum(x[1]*min(1.0,abs(x[0])+0.20) for x in families if x[0]>0)
    neg=sum(x[1]*min(1.0,abs(x[0])+0.20) for x in families if x[0]<0)
    agreement=max(pos,neg)/max(0.001,pos+neg)
    edge=abs(norm)
    avg_skill=sum(x[1]*x[3] for x in families)/den
    ent=_v68_sequence_entropy(hist)
    cp=_v68_change_point(hist)
    diag=_v68_diagnostics(hist)
    structural=any(
        x[2] in ('RLE-RHYTHM','RLE-SHAPE','CYCLE') and abs(x[0])>=0.24 and x[3]>=0.535
        for x in families
    )

    if mode==1:
        skip_skill,skip_edge,skip_ag=0.526,0.050,0.585
    elif mode==3:
        skip_skill,skip_edge,skip_ag=0.500,0.022,0.525
    else:
        skip_skill,skip_edge,skip_ag=0.513,0.035,0.552

    forced=False
    weak=(avg_skill<skip_skill and (edge<skip_edge or agreement<skip_ag))
    unstable=(cp>0.58 and agreement<0.60 and edge<0.08)
    high_noise=(diag['noise']>=88 and diag['clarity']<35 and not structural)
    if weak or unstable or high_noise:
        top=sorted(families,key=lambda z:abs(z[0]*z[1]),reverse=True)[:4]
        why='+'.join(z[2] for z in top)
        conf=int(round(_v61_clamp(48+max(0,avg_skill-0.5)*100+edge*14+(agreement-0.5)*10-ent*1.5-cp*2,50,70)))
        if not force:
            return None,conf,f"{prefix} · {diag['pattern']} · {why} · SKILL {avg_skill*100:.1f}% · AG {agreement*100:.0f}% · BỎ QUA"
        forced=True

    raw=(
        47
        + max(0.0,avg_skill-0.5)*125
        + max(0.0,agreement-0.5)*24
        + edge*17
        + (1.0-ent)*3.5
        + (1.0-cp)*2.2
    )
    if forced:
        raw=min(raw,58 if high_noise else 66)
    conf=int(round(_v61_clamp(raw,50,88)))
    side='T' if norm>=0 else 'X'
    top=sorted(families,key=lambda z:abs(z[0]*z[1]),reverse=True)[:5]
    why='+'.join(f'{z[2]}:{z[3]*100:.0f}' for z in top)
    tag=(' · NOISE FORCE' if forced and high_noise else ' · COVERAGE FORCE' if forced else '')
    return side,conf,f"{prefix} · {diag['pattern']} · {diag['regime']} · {why} · SKILL {avg_skill*100:.1f}% · AG {agreement*100:.0f}% · E {edge:.2f}{tag}"


def _v68_lc79_candidates():
    c=_v61_lc79_candidates()
    c['RHYTHM']=_v68_rhythm
    c['SHAPE']=_v68_shape
    c['BREAK']=_v68_break_transition
    c['CHI']=_v68_chi_bias
    return c


def _v68_sunwin_candidates():
    c=_v61_sunwin_candidates()
    c['RHYTHM']=_v68_rhythm
    c['SHAPE']=_v68_shape
    c['BREAK']=_v68_break_transition
    c['CHI']=_v68_chi_bias
    return c


def predict_lc79_v68(seq,force=False):
    hist=_v61_seq_values(seq,cap=320)
    mode=setting_int('lc79_algo_mode',2,1,3)
    return _v68_ensemble(hist,_v68_lc79_candidates(),mode=mode,prefix='LC79 V68 MAX',force=force)


def predict_sunwin_v68(seq,force=False):
    hist=_v61_seq_values(seq,cap=320)
    mode=setting_int('sunwin_algo_mode',2,1,3)
    return _v68_ensemble(hist,_v68_sunwin_candidates(),mode=mode,prefix='SUNWIN V68 MAX',force=force)


# =============================================================
# ENTRY POINTS V61 — giữ đúng chữ ký (seq) -> (side, confidence, reason)
# =============================================================
def predict_lc79_v61(seq, force=False):
    hist = _v61_seq_values(seq, cap=280)
    mode = setting_int("lc79_algo_mode", 2, 1, 3)
    return _v61_ensemble(hist, _v61_lc79_candidates(), mode=mode, prefix="LC79 V61", force=force)


def predict_sunwin_v61(seq, force=False):
    hist = _v61_seq_values(seq, cap=280)
    mode = setting_int("sunwin_algo_mode", 2, 1, 3)
    return _v61_ensemble(hist, _v61_sunwin_candidates(), mode=mode, prefix="SUNWIN V61", force=force)



# =============================================================
# DEEP ENSEMBLE — baseline-aware, motif/run-state, no last-result shortcut
# =============================================================
# Kết quả ngay trước đó không được coi là bằng chứng độc lập. Mỗi mô hình
# được so với hai baseline ngây thơ: lặp phiên trước / đảo phiên trước.

def _core_weighted_baselines(hist, horizons=((24,.50),(48,.32),(96,.18))):
    n=len(hist)
    if n<8:return {'repeat':.5,'flip':.5}
    out={'repeat':0.0,'flip':0.0};den=0.0
    for H,hw in horizons:
        begin=max(1,n-H);hit_r=hit_f=tot=0.0
        for i in range(begin,n):
            age=n-1-i;w=0.5**(age/26.0);prev=hist[i-1];actual=hist[i]
            tot+=w
            if prev==actual:hit_r+=w
            if prev!=actual:hit_f+=w
        out['repeat']+=hw*((hit_r+3.0)/(tot+6.0) if tot else .5)
        out['flip']+=hw*((hit_f+3.0)/(tot+6.0) if tot else .5)
        den+=hw
    return {k:v/den for k,v in out.items()} if den else {'repeat':.5,'flip':.5}


def _core_model_relation(hist,fn,window=72):
    n=len(hist);begin=max(12,n-window)
    rn=fnn=rh=fh=0.0
    for i in range(begin,n):
        try:e,sup=fn(hist[:i])
        except Exception:continue
        if abs(e)<.04 or sup<.13:continue
        pred='T' if e>0 else 'X';prev=hist[i-1];age=n-1-i;w=0.5**(age/28.0)
        if pred==prev:
            rn+=w
            if pred==hist[i]:rh+=w
        else:
            fnn+=w
            if pred==hist[i]:fh+=w
    total=rn+fnn
    return {'repeat_frac':rn/total if total else .5,'flip_frac':fnn/total if total else .5,
            'repeat_acc':rh/rn if rn else .5,'flip_acc':fh/fnn if fnn else .5,'active_weight':total}


def _core_motif(hist,min_order=3,max_order=11):
    n=len(hist)
    if n<18:return 0.0,0.0
    votes=[]
    for order in range(min_order,min(max_order,n-7)+1):
        ctx=hist[-order:];t=x=.72;sup=0.0
        for i in range(order,n):
            if hist[i-order:i]!=ctx:continue
            age=n-1-i;w=0.5**(age/(15.0+order))
            if hist[i]=='T':t+=w
            else:x+=w
            sup+=w
        if sup<.24:continue
        edge=(t-x)/(t+x)
        if abs(edge)<.045:continue
        q=min(1.0,sup/(.55+.10*order))
        votes.append((edge,sup*q*(1.0+.055*order)))
    if not votes:return 0.0,0.0
    den=sum(w for _,w in votes) or 1.0
    return _v61_clamp(sum(e*w for e,w in votes)/den,-1,1),min(3.0,den/2.2)


def _core_run_signature(hist):
    if len(hist)<24:return 0.0,0.0
    runs=_v68_rle(hist)
    if len(runs)<5:return 0.0,0.0
    _,cur_len=runs[-1];prev_len=runs[-2][1]
    def rlen_at(seq,i):
        side=seq[i];k=1;j=i-1
        while j>=0 and seq[j]==side and k<12:k+=1;j-=1
        return k
    t=x=sup=0.0;n=len(hist);current_cr=_v61_change_rate(hist,18)
    for i in range(5,n-1):
        rl=rlen_at(hist,i)
        if abs(min(8,rl)-min(8,cur_len))>1:continue
        j=i-rl
        if j<0:continue
        ps=hist[j];pl=1;j-=1
        while j>=0 and hist[j]==ps and pl<12:pl+=1;j-=1
        if abs(min(8,pl)-min(8,prev_len))>2:continue
        cr=_v61_change_rate(hist[:i+1],18)
        if abs(cr-current_cr)>.22:continue
        age=n-2-i;w=0.5**(age/22.0);nxt=hist[i+1]
        if nxt=='T':t+=w
        else:x+=w
        sup+=w
    if sup<.28:return 0.0,0.0
    return _v61_clamp((t-x)/(t+x),-1,1),min(2.4,sup)


def _core_best_effort(hist):
    if not hist:return 'T',50,'DỮ LIỆU MỎNG'
    pool=[(_core_motif,1.25),(_v68_rhythm,1.25),(_v68_shape,1.0),(_core_run_signature,1.15),
          (lambda h:_v61_markov(h,2),.85),(lambda h:_v61_markov(h,3),.95),
          (lambda h:_v61_context(h,3),.85),(lambda h:_v61_context(h,4),.95),
          (_v61_cycle,1.0),(_v68_break_transition,.7)]
    num=den=0.0
    for fn,mul in pool:
        try:e,sup=fn(hist)
        except Exception:continue
        if abs(e)<.025 or sup<=.08:continue
        w=mul*min(1.2,.30+sup*.34)*min(1.0,.35+abs(e)*1.6);num+=e*w;den+=w
    norm=num/den if den else 0.0
    if abs(norm)<.02:
        r=hist[-64:];bal=(r.count('T')-r.count('X'))/max(1,len(r));norm=-bal
        if abs(norm)<.02:
            e,sup=_v61_markov(hist,2);norm=e if sup>.08 else (-1.0 if hist[-1]=='T' else 1.0)
    side='T' if norm>=0 else 'X';conf=int(round(_v61_clamp(50+abs(norm)*18,50,59)))
    return side,conf,'PHỦ DỰ ĐOÁN · TÍN HIỆU YẾU'



def _core_knn_analog(hist):
    """Regime-aware analogue search over prior states.

    The current state is described by multiple independent features rather than
    the last result alone: short/medium balance, change rate, current/previous
    run length, conditional entropy and lag autocorrelation. Historical states
    with a similar shape vote on the next result. This intentionally requires
    several usable neighbours so a single coincidence cannot dominate.
    """
    if len(hist)<48:return 0.0,0.0
    def feat(seq):
        if len(seq)<20:return None
        runs=_v68_rle(seq);cur=runs[-1][1] if runs else 1;prev=runs[-2][1] if len(runs)>1 else 1
        def bal(w):
            r=seq[-w:];return (r.count('T')-r.count('X'))/max(1,len(r))
        cr8=_v61_change_rate(seq,8);cr20=_v61_change_rate(seq,20)
        ent=_v68_sequence_entropy(seq[-48:])
        ac1=_v61_autocorr(seq,1);ac2=_v61_autocorr(seq,2)
        return (bal(8),bal(20),cr8,cr20,min(cur,8)/8,min(prev,8)/8,ent,ac1,ac2)
    cur=feat(hist)
    if not cur:return 0.0,0.0
    weights=(1.2,1.0,1.15,1.0,.9,.7,1.0,.8,.75)
    cand=[]
    # keep at least 12 observations behind current state to reduce self-similarity leakage
    for i in range(28,len(hist)-2):
        f=feat(hist[:i+1])
        if not f:continue
        dist=sum(w*(a-b)*(a-b) for a,b,w in zip(cur,f,weights))**0.5
        if dist>1.55:continue
        age=(len(hist)-2-i);rw=0.5**(age/90.0);sim=1/(0.08+dist)
        cand.append((dist,rw*sim,hist[i+1]))
    if len(cand)<5:return 0.0,0.0
    cand.sort(key=lambda x:x[0]);cand=cand[:18]
    t=x=0.0
    for _,w,nxt in cand:
        if nxt=='T':t+=w
        else:x+=w
    den=t+x
    if den<=0:return 0.0,0.0
    edge=(t-x)/den
    # support grows with neighbour count and effective weight, but stays capped
    support=min(2.2,(len(cand)/8.0)*min(1.2,den/10.0))
    if abs(edge)<.055:return 0.0,support*.5
    return _v61_clamp(edge,-1,1),support


def _core_context_profile(hist):
    """Multi-window conditional profile.

    It asks the same recent suffix question at several context lengths and
    several horizons. A vote is emitted only when enough historical matches
    exist and the windows broadly agree. Walk-forward in _core_ensemble still
    decides whether this family deserves weight.
    """
    if len(hist)<42:return 0.0,0.0
    votes=[]
    for win,ww in ((28,1.00),(56,.90),(112,.72),(224,.54)):
        r=hist[-min(win,len(hist)):]
        if len(r)<24:continue
        for order,ow in ((2,.72),(3,.90),(4,1.00),(5,.88),(6,.72)):
            if len(r)<=order+4:continue
            ctx=tuple(r[-order:]);t=x=0.0;hits=0
            # Use only transitions that are fully in the historical part; the
            # current suffix itself is never used as its own target.
            for i in range(order,len(r)-1):
                if tuple(r[i-order:i])!=ctx:continue
                nxt=r[i];hits+=1
                age=(len(r)-1-i);rw=0.5**(age/max(18.0,win*.55))
                if nxt=='T':t+=rw
                else:x+=rw
            if hits<3:continue
            den=t+x
            if den<=0:continue
            edge=(t-x)/(den+1.25)
            if abs(edge)<.055:continue
            votes.append((edge,ww*ow*min(1.25,hits/6.0),hits))
    if len(votes)<3:return 0.0,0.0
    pos=sum(w for e,w,_ in votes if e>0);neg=sum(w for e,w,_ in votes if e<0);tot=pos+neg
    if max(pos,neg)/max(.001,tot)<.62:return 0.0,.35
    edge=sum(e*w for e,w,_ in votes)/max(.001,tot)
    support=min(2.0,.30+len(votes)*.12+min(1.0,tot/8.0))
    return _v61_clamp(edge,-1,1),support

def _core_multiscale(hist):
    """Require agreement across several time scales before emitting a vote."""
    if len(hist)<36:return 0.0,0.0
    votes=[]
    for w,decay in ((10,.22),(18,.15),(32,.095),(56,.055),(96,.032)):
        if len(hist)<max(12,w//2):continue
        r=hist[-w:];num=den=0.0
        for age,v in enumerate(reversed(r)):
            wt=math.exp(-age*decay);num+=(1 if v=='T' else -1)*wt;den+=wt
        b=num/max(.001,den)
        if abs(b)>=.07:votes.append((b,1.0 if w<=32 else .75))
    if len(votes)<3:return 0.0,0.0
    pos=sum(w for e,w in votes if e>0);neg=sum(w for e,w in votes if e<0);tot=pos+neg
    if max(pos,neg)/max(.001,tot)<.67:return 0.0,.35
    edge=sum(e*w for e,w in votes)/max(.001,tot)
    return _v61_clamp(edge,-1,1),min(1.8,.35+tot*.28)


def _core_state_consensus(hist):
    """Consensus of transition/context/run models over independent windows.

    A direction is emitted only when several windows point the same way. The
    candidate is still walk-forward validated by `_core_ensemble`, so this is
    a stability feature rather than a hard-coded T/X rule.
    """
    if len(hist)<44:return 0.0,0.0
    votes=[]
    for win,ww in ((28,1.0),(48,.92),(80,.78),(128,.62),(220,.46)):
        h=hist[-min(win,len(hist)):]
        if len(h)<24:continue
        local=[]
        for fn,mul in ((lambda x:_v61_markov(x,2),1.0),(lambda x:_v61_markov(x,3),.9),
                       (lambda x:_v61_context(x,3),1.0),(lambda x:_v61_context(x,4),.9),
                       (lambda x:_v61_run(x),.72)):
            try:e,sup=fn(h)
            except Exception:continue
            if sup>.10 and abs(e)>=.045:local.append((e,mul*min(1.0,.35+sup*.38)))
        if len(local)<2:continue
        den=sum(w for _,w in local) or 1.0
        edge=sum(e*w for e,w in local)/den
        pos=sum(w for e,w in local if e>0);neg=sum(w for e,w in local if e<0)
        ag=max(pos,neg)/max(.001,pos+neg)
        if ag<.62 or abs(edge)<.05:continue
        votes.append((edge,ww*ag))
    if len(votes)<3:return 0.0,0.0
    den=sum(w for _,w in votes) or 1.0
    edge=sum(e*w for e,w in votes)/den
    pos=sum(w for e,w in votes if e>0);neg=sum(w for e,w in votes if e<0)
    ag=max(pos,neg)/max(.001,pos+neg)
    if ag<.68:return 0.0,.30
    return _v61_clamp(edge,-1,1),min(2.0,.35+len(votes)*.22+ag*.45)


def _learning_context_keys(hist):
    """Dynamic signatures. They are learned only after a REAL next result settles."""
    if len(hist)<8:return []
    keys=[]
    for n in (2,3,4,5,6,7,8):
        if len(hist)>=n:keys.append(f"S{n}:"+''.join(hist[-n:]))
    runs=[];cur=hist[0];cnt=1
    for v in hist[1:]:
        if v==cur:cnt+=1
        else:runs.append(cnt);cur=v;cnt=1
    runs.append(cnt)
    if len(runs)>=3:keys.append('R3:'+'-'.join(str(min(9,x)) for x in runs[-3:]))
    if len(runs)>=5:keys.append('R5:'+'-'.join(str(min(9,x)) for x in runs[-5:]))
    try:
        d=_v68_diagnostics(hist)
        keys.append('D:'+str(d.get('pattern','?'))+'|'+str(d.get('regime','?')))
    except Exception:pass
    return keys[:12]


def _learn_pattern_row(con,table_name,learn_keys,actual,stamp):
    if actual not in ('T','X') or not learn_keys:return
    now=datetime.now(timezone.utc)
    for key in learn_keys:
        if not key:continue
        row=con.execute('SELECT * FROM learned_patterns WHERE table_name=? AND context_key=?',(table_name,key)).fetchone()
        tw=xw=0.0;samples=0
        if row:
            tw=float(row['t_weight'] or 0);xw=float(row['x_weight'] or 0);samples=int(row['samples'] or 0)
            try:
                prev=datetime.fromisoformat(row['updated_at'])
                hours=max(0.0,(now-prev).total_seconds()/3600.0)
                decay=0.5**(hours/48.0)
                tw*=decay;xw*=decay
            except Exception:pass
        if actual=='T':tw+=1.0
        else:xw+=1.0
        con.execute('''INSERT INTO learned_patterns(table_name,context_key,t_weight,x_weight,samples,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(table_name,context_key) DO UPDATE SET
                       t_weight=excluded.t_weight,x_weight=excluded.x_weight,
                       samples=excluded.samples,updated_at=excluded.updated_at''',
                    (table_name,key,tw,xw,samples+1,stamp))


def _online_pattern_signal(hist,table_name):
    """Settled-only online learner with aggressive shrinkage against small samples.

    Learned patterns are advisory.  They never get to look at the current
    unsettled result, and sparse contexts are shrunk hard toward 50/50 so a
    short lucky streak cannot steer the whole ensemble.
    """
    keys=_learning_context_keys(hist)
    if not keys:return 0.0,0.0
    votes=[];now=datetime.now(timezone.utc)
    with db() as con:
        for key in keys:
            row=con.execute('SELECT * FROM learned_patterns WHERE table_name=? AND context_key=?',(table_name,key)).fetchone()
            samples=int(row['samples'] or 0) if row else 0
            if not row or samples<7:continue
            tw=float(row['t_weight'] or 0);xw=float(row['x_weight'] or 0)
            try:
                prev=datetime.fromisoformat(row['updated_at'])
                hours=max(0.0,(now-prev).total_seconds()/3600.0)
                decay=0.5**(hours/42.0);tw*=decay;xw*=decay
            except Exception:pass
            eff=tw+xw
            if eff<5.0:continue
            # Strong Beta shrinkage + explicit effective-sample shrinkage.
            p=(tw+2.6)/(eff+5.2)
            raw=(p-.5)*2.0
            shrink=eff/(eff+9.0)
            edge=raw*shrink
            if abs(edge)<.055:continue
            specificity=1.0
            if key.startswith('S'):
                try:specificity=.68+min(8,int(key[1:key.index(':')]))*.048
                except Exception:pass
            elif key.startswith('R5:'):specificity=1.00
            elif key.startswith('D:'):specificity=.66
            # Long contexts need more samples before they may carry full weight.
            sample_factor=_v61_clamp((samples-4)/14.0,.20,1.0)
            w=min(1.15,math.log1p(eff)/2.8)*specificity*sample_factor
            votes.append((edge,w,eff,samples))
    if len(votes)<2:return 0.0,0.0
    pos=sum(w for e,w,_,_ in votes if e>0);neg=sum(w for e,w,_,_ in votes if e<0);tot=pos+neg
    if max(pos,neg)/max(.001,tot)<.68:return 0.0,.24
    edge=sum(e*w for e,w,_,_ in votes)/max(.001,tot)
    support=min(1.45,.24+len(votes)*.105+min(.85,sum(v[2] for v in votes)/48.0))
    return _v61_clamp(edge,-1,1),support


def _v69_state_memory(hist):
    """Joint context memory: recent sequence + run bucket + local change-rate.

    It requires repeated historical analogs and recency decay, so one newest
    result cannot become a strong signal on its own.
    """
    n=len(hist)
    if n<28:return 0.0,0.0
    def state_at(end):
        if end<8:return None
        h=hist[:end];ctx=''.join(h[-4:]);cur=h[-1];run=1
        for j in range(len(h)-2,max(-1,len(h)-10),-1):
            if h[j]==cur:run+=1
            else:break
        cr=_v61_change_rate(h,12);bucket=0 if cr<.34 else 2 if cr>.66 else 1
        return (ctx,min(5,run),bucket)
    target=state_at(n)
    if not target:return 0.0,0.0
    t=x=.9;support=0.0
    for end in range(10,n):
        if state_at(end)!=target:continue
        nxt=hist[end];age=n-end;w=.5**(age/22.0)
        if nxt=='T':t+=w
        elif nxt=='X':x+=w
        support+=w
    if support<.34:return 0.0,support
    return _v61_clamp((t-x)/(t+x),-1,1),min(2.0,support)

def _core_candidates(game='lc79',table_name=None):
    c=_v61_lc79_candidates() if game=='lc79' else _v61_sunwin_candidates()
    c.pop('MOM',None);c['RHYTHM']=_v68_rhythm;c['SHAPE']=_v68_shape;c['BREAK']=_v68_break_transition
    c['MOTIF']=_core_motif;c['RUNSIG']=_core_run_signature;c['ANALOG']=_core_knn_analog;c['PROFILE']=_core_context_profile;c['MULTI']=_core_multiscale;c['STATESTACK']=_core_state_consensus;c['STATEV69']=_v69_state_memory
    if table_name:c['LEARNED']=lambda h:_online_pattern_signal(h,table_name)
    return c


def _core_family(name):
    if name.startswith('MK') or name=='VOM' or name.startswith('BAYES'):return 'CHUYỂN TIẾP'
    if name.startswith('CTX') or name in ('PAIR','MOTIF','PROFILE'):return 'NGỮ CẢNH'
    return {'RHYTHM':'NHỊP','SHAPE':'HÌNH THÁI','BREAK':'ĐIỂM GÃY','RUN':'BỆT',
            'RUNSIG':'TRẠNG THÁI NHỊP','REGIME':'CHẾ ĐỘ','CYCLE':'CHU KỲ','ANALOG':'TƯƠNG ĐỒNG','MULTI':'ĐA KHUNG','STATESTACK':'ĐỒNG THUẬN','STATEV69':'BỘ NHỚ TRẠNG THÁI','LEARNED':'TỰ HỌC'}.get(name,name)


def _core_structural_anchor(hist,candidates):
    """Lightweight previous-step consensus used only as hysteresis.

    It evaluates the same structural families on history BEFORE the newest
    outcome.  If one newly appended result alone reverses the sign, the new
    consensus must be materially stronger before the direction changes.
    """
    if len(hist)<22:
        return 0.0,0.0
    h=hist[:-1]
    fam={}
    for name,fn in candidates.items():
        if name=='BREAK':
            continue
        try:e,sup=fn(h)
        except Exception:continue
        if sup<=.10 or abs(e)<.025:
            continue
        family=_core_family(name)
        w=_v61_clamp(.18+sup*.34,.16,1.05)*_v61_clamp(.30+abs(e)*1.45,.25,1.0)
        fam.setdefault(family,[]).append((e,w))
    if not fam:
        return 0.0,0.0
    votes=[]
    for family,items in fam.items():
        den=sum(w for _,w in items) or 1.0
        fe=sum(e*w for e,w in items)/den
        # one vote per family to avoid correlated Markov/context clones
        fw=min(1.0,0.42+0.18*len(items))
        votes.append((fe,fw))
    den=sum(w for _,w in votes) or 1.0
    norm=sum(e*w for e,w in votes)/den
    agreement=max(sum(w for e,w in votes if e>0),sum(w for e,w in votes if e<0))/den
    return _v61_clamp(norm,-1.0,1.0),_v61_clamp(agreement,0.0,1.0)


def _core_anchor_stack(hist,candidates):
    """Consensus of several PREVIOUS structural states.

    The newest result is deliberately excluded by _core_structural_anchor().
    Calling it on progressively shorter prefixes tells us whether a direction
    existed for more than one settled session.  This is a hysteresis guard,
    not an extra prediction model.
    """
    votes=[]
    for cut,recency in ((0,1.00),(1,.84),(2,.70),(3,.58)):
        h=hist[:-cut] if cut else hist
        if len(h)<22:continue
        try:e,ag=_core_structural_anchor(h,candidates)
        except Exception:continue
        if abs(e)<.032:continue
        w=recency*_v61_clamp(.58+.42*ag,.55,1.0)*_v61_clamp(.35+abs(e)*4.2,.38,1.0)
        votes.append((e,w))
    if not votes:return 0.0,0.0,0
    den=sum(w for _,w in votes) or 1.0
    norm=sum(e*w for e,w in votes)/den
    pos=sum(w for e,w in votes if e>0);neg=sum(w for e,w in votes if e<0)
    agreement=max(pos,neg)/max(.001,pos+neg)
    return _v61_clamp(norm,-1.0,1.0),_v61_clamp(agreement,0.0,1.0),len(votes)


def _core_ensemble(hist,candidates,mode=2,force=False):
    if len(hist)<16:return _core_best_effort(hist) if force else (None,48,'CHƯA ĐỦ DỮ LIỆU · BỎ QUA')
    horizons=((20,.42),(40,.30),(80,.18),(140,.10));naive=_core_weighted_baselines(hist,horizons);last=hist[-1];models=[]
    for name,fn in candidates.items():
        try:edge,sup=fn(hist)
        except Exception:continue
        if sup<=.10 or abs(edge)<.020:continue
        # The online learner is trained only from already-settled real sessions.
        # Do NOT walk-forward it on historical prefixes using today's learned DB,
        # because that would leak future information into its validation score.
        if name=='LEARNED':
            pred='T' if edge>0 else 'X';mimics='repeat' if pred==last else 'flip'
            active=max(5,int(round(sup*8)))
            skill=.505+min(.020,max(0.0,sup-.30)*.012)
            weight=min(.30,.055+max(0.0,sup-.30)*.105)*min(1.0,.45+abs(edge)*1.25)
            if weight>=.025:models.append((edge,weight,name,skill,sup,active,0.0,mimics))
            continue
        per_h=_v61_walkforward(hist,fn,horizons=tuple(h for h,_ in horizons),prior_a=3.0,prior_b=6.0)
        den_h=skill_num=0.0;active=0
        for (_,hw),(_,acc,tot,act) in zip(horizons,per_h):
            sf=_v61_clamp(tot/7.0,.10,1.0);ww=hw*sf;den_h+=ww;skill_num+=ww*(acc-.5);active=max(active,act)
        if den_h<=0:continue
        skill=.5+skill_num/den_h;acc24=per_h[0][1] if per_h else .5;acc48=per_h[1][1] if len(per_h)>1 else acc24
        if active>=12 and skill<.466 and acc24<.468 and acc48<.480:continue
        if active>=8 and skill<.492:continue
        relation=_core_model_relation(hist,fn);pred='T' if edge>0 else 'X';mimics='repeat' if pred==last else 'flip'
        frac=relation['repeat_frac'] if mimics=='repeat' else relation['flip_frac']
        relacc=relation['repeat_acc'] if mimics=='repeat' else relation['flip_acc'];baseline=naive[mimics];lift=skill-baseline
        mimic_factor=1.0
        if frac>=.76 and lift<.010:mimic_factor=.24
        elif frac>=.66 and lift<.020:mimic_factor=.48
        elif frac>=.58 and lift<.012:mimic_factor=.70
        if relation['active_weight']>4 and relacc<=baseline+.006:mimic_factor*=.78
        recent_factor=_v61_clamp(active/14.0,.25,1.0);skill_edge=max(0.0,skill-.5)
        weight=(.11+skill_edge*7.7)*_v61_clamp(.38+sup*.36,.28,1.45)*(.62+.38*recent_factor)*mimic_factor
        if weight>=.025:models.append((edge,weight,name,max(.5,skill),sup,active,lift,mimics))
    if not models:return _core_best_effort(hist) if force else (None,50,'KHÔNG CÓ TÍN HIỆU ĐỦ TIN CẬY · BỎ QUA')
    fam={}
    for item in models:fam.setdefault(_core_family(item[2]),[]).append(item)
    families=[]
    for fname,items in fam.items():
        dw=sum(x[1] for x in items) or 1.0;fe=sum(x[0]*x[1] for x in items)/dw;fs=sum(x[3]*x[1] for x in items)/dw
        fl=sum(x[6]*x[1] for x in items)/dw;fact=max(x[5] for x in items);support=sum(min(1.0,x[4]) for x in items)/len(items)
        fw=(.16+max(0,fs-.5)*8.2)*_v61_clamp(.50+support*.50,.36,1.12)*_v61_clamp(fact/12,.35,1.0)
        fw*=_v61_clamp(.72+max(-.02,fl)*5.0,.55,1.18)
        # A break detector is advisory only; it must never dominate the full
        # ensemble on its own.
        if fname=='ĐIỂM GÃY':
            fw*=0.46
        if fname=='TỰ HỌC':
            fw*=0.62  # advisory learner; never allowed to dominate structural families
        families.append((fe,fw,fname,fs,support,fact,fl))
    den=sum(x[1] for x in families) or 1.0;norm=sum(x[0]*x[1] for x in families)/den
    pos=sum(x[1]*min(1,abs(x[0])+.20) for x in families if x[0]>0);neg=sum(x[1]*min(1,abs(x[0])+.20) for x in families if x[0]<0)
    agreement=max(pos,neg)/max(.001,pos+neg);avg_skill=sum(x[1]*x[3] for x in families)/den
    diag=_v68_diagnostics(hist);ent=_v68_sequence_entropy(hist);cp=_v68_change_point(hist)

    # Anti-whipsaw hysteresis: compare current consensus with the structural
    # consensus before the newest outcome. One result may weaken a view, but
    # should not reverse it unless the new evidence is clearly stronger or a
    # real regime change is being detected.
    anchor,anchor_ag,anchor_n=_core_anchor_stack(hist,candidates)
    pre_edge=abs(norm)
    if anchor*norm<0 and abs(anchor)>=.050 and anchor_n>=2:
        # One new settled result is not enough to reverse a multi-prefix view.
        strong_new=(pre_edge>=.155 and agreement>=.66 and avg_skill>=.528)
        confirmed_shift=(cp>=.58 and pre_edge>=.105 and agreement>=.61)
        if not (strong_new or confirmed_shift):
            inertia=_v61_clamp(.64-(cp*.50),.24,.56)
            inertia*=_v61_clamp(.84+anchor_ag*.30,.86,1.12)
            norm=(1.0-inertia)*norm + inertia*anchor

    # A clear run/rhythm may stabilize a direction, but it is only a guard.
    # It can damp an unsupported flip; it never overrides a strong new consensus.
    try:rh_edge,rh_sup=_v68_rhythm(hist)
    except Exception:rh_edge,rh_sup=0.0,0.0
    if rh_edge*norm<0 and abs(rh_edge)>=.24 and rh_sup>=.52 and cp<.52 and agreement<.69:
        norm=.74*norm+.26*rh_edge
    edge=abs(norm)

    independent=sum(1 for x in families if abs(x[0])>=.055 and x[1]>=.10)
    structural=any(x[2] in ('NHỊP','HÌNH THÁI','CHU KỲ','TRẠNG THÁI NHỊP') and abs(x[0])>=.20 and x[3]>=.53 for x in families)
    final_side='T' if norm>=0 else 'X';family_lift=sum(x[1]*x[6] for x in families)/den
    # Symmetric anti-shortcut penalty: neither "repeat last" nor "flip last"
    # gets a free pass if the families fail to beat that naive baseline.
    relation='repeat' if final_side==last else 'flip'
    baseline=naive.get(relation,.5)
    if family_lift<.010 and not structural:
        dep=_v61_clamp((baseline-.50)*3.0,0.0,.24)
        norm*=max(.38,.52-dep)
        edge=abs(norm);final_side='T' if norm>=0 else 'X'
    if mode==1:skip_skill,skip_edge,skip_ag=.526,.050,.585
    elif mode==3:skip_skill,skip_edge,skip_ag=.500,.020,.520
    else:skip_skill,skip_edge,skip_ag=.512,.033,.550
    min_independent=2 if mode==3 else 3
    no_edge_over_naive=(family_lift<=.002 and avg_skill<.525 and not structural)
    weak=(avg_skill<skip_skill and (edge<skip_edge or agreement<skip_ag)) or (independent<min_independent and not structural) or (mode!=3 and no_edge_over_naive)
    unstable=(cp>.58 and agreement<.60 and edge<.08);noisy=(diag['noise']>=89 and diag['clarity']<34 and not structural)
    if weak or unstable or noisy:
        conf=int(round(_v61_clamp(49+max(0,avg_skill-.5)*95+edge*13+(agreement-.5)*9,50,68)))
        if not force:return None,conf,f"{diag['pattern']} · {diag['regime']} · BỎ QUA"
        side,fb_conf,fb_reason=_core_best_effort(hist);return side,min(conf,fb_conf),fb_reason
    raw=47+max(0,avg_skill-.5)*122+max(0,agreement-.5)*23+edge*16+(1-ent)*3+(1-cp)*2
    conf=int(round(_v61_clamp(raw,50,84)))
    # Honest calibration caps.  Few independent families, weak OOS skill, or a
    # transition regime must not display an inflated confidence number.
    if independent<3:conf=min(conf,74)
    if avg_skill<.525:conf=min(conf,72)
    if cp>.48:conf=min(conf,70)
    if diag['noise']>=84 and not structural:conf=min(conf,68)
    top=sorted(families,key=lambda z:abs(z[0]*z[1]),reverse=True)[:3]
    why=' + '.join(z[2] for z in top)
    return final_side,conf,f"{diag['pattern']} · {diag['regime']} · {why}"


def _v10_settled_calibration(table_name,result,force=False):
    """Calibrate displayed confidence using only already-settled predictions.

    This never sees the target of the current/open round. It can only lower
    confidence or skip a weak signal after poor recent out-of-sample results.
    """
    side,conf,reason=result
    if side not in ('T','X'):return result
    try:
        with db() as con:
            rows=con.execute('''SELECT correct FROM global_history WHERE table_name=? AND actual IS NOT NULL AND correct IS NOT NULL ORDER BY id DESC LIMIT 80''',(table_name,)).fetchall()
        vals=[int(r['correct']) for r in rows]
    except Exception:
        vals=[]
    n=len(vals)
    if n<12:return side,min(int(conf),78),str(reason or '')+' · V10 CAL:WARMUP'
    recent=vals[:24];mid=vals[:48]
    # Beta(6,6) shrinkage keeps small lucky samples from inflating confidence.
    p24=(sum(recent)+6.0)/(len(recent)+12.0)
    p48=(sum(mid)+8.0)/(len(mid)+16.0)
    blended=.62*p24+.38*p48
    cap=int(round(_v61_clamp(56+(blended-.5)*92,56,82)))
    conf=min(int(conf),cap)
    bad_run=0
    for v in vals:
        if v==0:bad_run+=1
        else:break
    if bad_run>=4:conf=min(conf,62)
    if n>=24 and blended<.485 and not force:
        return None,min(conf,61),str(reason or '')+' · V10 CAL:RECENT WEAK · BỎ QUA'
    return side,conf,str(reason or '')+f' · V10 CAL:{int(round(blended*100))}%/{n}'


def predict_lc79_core(seq,force=False,table_name='hu'):
    hist=_v61_seq_values(seq,cap=420)
    return _v10_settled_calibration(table_name,_core_ensemble(hist,_core_candidates('lc79',table_name),mode=setting_int('lc79_algo_mode',2,1,3),force=force),force=force)


def predict_sunwin_core(seq,force=False,table_name='sunwin'):
    hist=_v61_seq_values(seq,cap=420)
    return _v10_settled_calibration(table_name,_core_ensemble(hist,_core_candidates('sunwin',table_name),mode=setting_int('sunwin_algo_mode',2,1,3),force=force),force=force)

def predict_max789_core(seq,force=False,table_name='max789_hu'):
    # MAX789 HŨ/MD5 share the full engine but learn patterns in isolated tables.
    hist=_v61_seq_values(seq,cap=420)
    return _v10_settled_calibration(table_name,_core_ensemble(hist,_core_candidates('lc79',table_name),mode=setting_int('max789_algo_mode',3,1,3),force=force),force=force)


def _prediction_payload(table):
    if str(table).startswith('custom__'):
        row=_custom_game_by_slug(_custom_slug_from_table(table),enabled_only=True)
        if not row:raise RuntimeError('Game tùy chỉnh không tồn tại hoặc đang tắt')
        current_data,hist_data=get_custom_upstream(table);seq=extract_any_history(hist_data)
        if not seq:raise RuntimeError(f"{row['name']} chưa trả lịch sử T/X có session ID thật")
        current_sid=find_sunwin_current_session(current_data)
        hist=_v61_seq_values(seq,cap=420)
        side,conf,reason=_v10_settled_calibration(table,_core_ensemble(hist,_core_candidates('lc79',table),mode=max(1,min(3,int(row.get('algo_mode') or 2))),force=False),force=False)
        reason=(reason or '')+' · V10 ADAPTIVE'
    elif table=='sunwin':
        current_data,hist_data=get_sunwin_upstream();seq=extract_sunwin_history(hist_data)
        if not seq:raise RuntimeError('SUNWIN chưa trả lịch sử có session ID thật')
        current_sid=find_sunwin_current_session(current_data);side,conf,reason=predict_sunwin_core(seq,table_name=table)
    elif table in ('max789_hu','max789_md5'):
        data=get_upstream(table);seq=extract_any_history(data)
        if not seq:raise RuntimeError('MAX789 chưa trả lịch sử có session ID thật')
        current_sid=None;side,conf,reason=predict_max789_core(seq,table_name=table)
    else:
        data=get_upstream(table);seq=extract_history(data)
        if not seq:raise RuntimeError('Nguồn LC79 chưa trả lịch sử có session ID thật')
        current_sid=None;side,conf,reason=predict_lc79_core(seq,table_name=table)
    actual_map=dict(seq);latest_sid=str(seq[0][0])
    age,fresh=_source_freshness(table,latest_sid,float(SOURCE_STALE_SECONDS))
    delayed = not fresh
    # Do not kill every table just because a completed-session id pauses briefly.
    # Only hard-stop after a much longer period; we still never fabricate session ids.
    if age > float(SOURCE_HARD_STALE_SECONDS):
        raise RuntimeError(f'Nguồn {table.upper()} đứng quá lâu ({int(age)}s chưa có phiên mới)')

    # Prefer a real current/open session exposed by the API.
    if current_sid and str(current_sid) not in actual_map:
        next_sid=str(current_sid)
    else:
        # Derive +1 ONLY when the last real ids are numeric and strictly consecutive.
        head=_numeric_consecutive_head(seq,3)
        if head is None:
            raise RuntimeError(f'Nguồn {table.upper()} chưa xác nhận phiên kế tiếp; đang chờ session ID thật')
        next_sid=str(head+1)

    diag=_v68_diagnostics(_v61_seq_values(seq,cap=360))
    diag['source_age_seconds']=int(age)
    diag['source_delayed']=bool(delayed)
    if delayed:
        reason=(reason or '') + f' · nguồn chậm {int(age)}s'
    return seq,actual_map,next_sid,side,conf,reason,diag


def _store_for_key(kid,table,seq,actual_map,next_sid,side,conf,reason):
    with db() as con:
        pending=con.execute('SELECT id,session_id,side FROM history WHERE key_id=? AND table_name=? AND actual IS NULL',(kid,table)).fetchall()
        for row in pending:
            act=actual_map.get(str(row['session_id']))
            if act:
                correct=None if row['side'] is None else int(row['side']==act);con.execute('UPDATE history SET actual=?,correct=? WHERE id=?',(act,correct,row['id']))
        existing=con.execute('SELECT side,confidence,reason FROM history WHERE key_id=? AND table_name=? AND session_id=? ORDER BY id DESC LIMIT 1',(kid,table,next_sid)).fetchone()
        if existing is not None:return existing['side'],int(existing['confidence'] or 50),existing['reason'] or reason
        final_side,final_conf,final_reason=side,conf,reason
        if final_side is None:
            if table.startswith('custom__'):
                _cg=_custom_game_by_slug(_custom_slug_from_table(table),enabled_only=True);mode=max(1,min(3,int((_cg or {}).get('algo_mode') or 2)))
            else:
                mode=(setting_int('sunwin_algo_mode',2,1,3) if table=='sunwin' else setting_int('max789_algo_mode',3,1,3) if table.startswith('max789_') else setting_int('lc79_algo_mode',2,1,3))
            if mode==3:
                recent=con.execute('SELECT side FROM history WHERE key_id=? AND table_name=? ORDER BY id DESC LIMIT 8',(kid,table)).fetchall()
                consecutive_skips=0
                for r in recent:
                    if r['side'] is None:consecutive_skips+=1
                    else:break
                if consecutive_skips>=4:
                    if table=='sunwin':cand_side,cand_conf,cand_reason=predict_sunwin_core(seq,force=True,table_name=table)
                    elif table in ('max789_hu','max789_md5'):cand_side,cand_conf,cand_reason=predict_max789_core(seq,force=True,table_name=table)
                    elif table.startswith('custom__'):
                        _cg=_custom_game_by_slug(_custom_slug_from_table(table),enabled_only=True)
                        cand_side,cand_conf,cand_reason=_core_ensemble(_v61_seq_values(seq,cap=420),_core_candidates('lc79',table),mode=max(1,min(3,int((_cg or {}).get('algo_mode') or 2))),force=True)
                    else:cand_side,cand_conf,cand_reason=predict_lc79_core(seq,force=True,table_name=table)
                    # Coverage fallback is intentionally labelled/capped; it is not promoted to a strong signal.
                    if cand_side in ('T','X') and int(cand_conf or 0)>=53:
                        final_side,final_conf,final_reason=cand_side,min(int(cand_conf),58),(cand_reason or '')+' · COVERAGE'
        con.execute('''INSERT OR IGNORE INTO history(key_id,table_name,session_id,side,confidence,reason,created_at)
                       VALUES(?,?,?,?,?,?,?)''',(kid,table,next_sid,final_side,final_conf,final_reason,now_iso()))
        return final_side,final_conf,final_reason


_BG_OWNER=f"{os.getpid()}-{uuid.uuid4().hex[:10]}";_BG_STARTED=False;_BG_START_LOCK=threading.Lock()

def _register_background_watch(kid,dev_hash,expires_at):
    with db() as con:
        con.execute('''INSERT INTO background_watches(key_id,device_hash,started_at,last_seen,expires_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(key_id,device_hash) DO UPDATE SET last_seen=excluded.last_seen,expires_at=excluded.expires_at,active=1''',
                    (kid,dev_hash,now_iso(),now_iso(),expires_at))

def _acquire_background_lease(ttl=8.0):
    now=time.time()
    try:
        with db() as con:
            con.execute('BEGIN IMMEDIATE');row=con.execute("SELECT owner,until_ts FROM worker_leases WHERE name='predictor'").fetchone()
            if row and float(row['until_ts'] or 0)>now and row['owner']!=_BG_OWNER:return False
            con.execute('''INSERT INTO worker_leases(name,owner,until_ts) VALUES('predictor',?,?)
                           ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,until_ts=excluded.until_ts''',(_BG_OWNER,now+ttl))
        return True
    except sqlite3.Error:return False

def _active_background_keys():
    now=now_iso()
    with db() as con:
        con.execute('''UPDATE background_watches SET active=0 WHERE active=1 AND
                       (expires_at<=? OR key_id IN (SELECT id FROM keys WHERE enabled=0 OR expires_at<=?))''',(now,now))
        rows=con.execute('''SELECT DISTINCT w.key_id FROM background_watches w JOIN keys k ON k.id=w.key_id
                            WHERE w.active=1 AND w.expires_at>? AND k.enabled=1 AND k.expires_at>?''',(now,now)).fetchall()
    return [int(r['key_id']) for r in rows]

def _store_global_prediction(table,seq,actual_map,next_sid,side,conf,reason):
    # Always-on 24/7 dataset + online pattern learner. Learning happens ONLY
    # after the real upstream result for a predicted session is available.
    stamp=now_iso();hist=_v61_seq_values(seq,cap=420);keys=_learning_context_keys(hist)
    with db() as con:
        pending=con.execute('SELECT id,session_id,side,learn_keys,learned FROM global_history WHERE table_name=? AND actual IS NULL',(table,)).fetchall()
        for row in pending:
            act=actual_map.get(str(row['session_id']))
            if act:
                correct=None if row['side'] is None else int(row['side']==act)
                learned=int(row['learned'] or 0)
                if not learned:
                    try:lk=json.loads(row['learn_keys'] or '[]')
                    except Exception:lk=[]
                    _learn_pattern_row(con,table,lk,act,stamp);learned=1
                con.execute('UPDATE global_history SET actual=?,correct=?,settled_at=?,learned=? WHERE id=?',(act,correct,stamp,learned,row['id']))
        con.execute('''INSERT OR IGNORE INTO global_history(table_name,session_id,side,confidence,reason,created_at,learn_keys,learned)
                       VALUES(?,?,?,?,?,?,?,0)''',(table,str(next_sid),side,int(conf or 0),reason or '',stamp,json.dumps(keys,ensure_ascii=False)))


def _background_table(table,kids):
    try:
        seq,actual_map,next_sid,side,conf,reason,diag=_prediction_payload(table)
        _store_global_prediction(table,seq,actual_map,next_sid,side,conf,reason)
        # Settle every active key's history from the same upstream snapshot.
        with db() as con:
            pending=con.execute('SELECT id,session_id,side FROM history WHERE table_name=? AND actual IS NULL',(table,)).fetchall()
            for row in pending:
                act=actual_map.get(str(row['session_id']))
                if act:
                    correct=None if row['side'] is None else int(row['side']==act)
                    con.execute('UPDATE history SET actual=?,correct=? WHERE id=?',(act,correct,row['id']))
        for kid in kids:
            _store_for_key(kid,table,seq,actual_map,next_sid,side,conf,reason)
    except Exception as e:
        return str(e)
    return None


def _background_loop():
    due={'hu':0.0,'md5':0.0,'sunwin':0.0,'max789_hu':0.0,'max789_md5':0.0}
    while True:
        try:
            if _acquire_background_lease():
                kids=_active_background_keys()
                now=time.time()
                # Global collection runs 24/7, even with zero active browser/key watches.
                for table in _all_prediction_tables():
                    due.setdefault(table,0.0)
                    if now<due[table]:
                        continue
                    _background_table(table,kids)
                    if table.startswith('custom__'):
                        _cg=_custom_game_by_slug(_custom_slug_from_table(table),enabled_only=True)
                        sec=max(2,min(60,int((_cg or {}).get('poll_seconds') or 4)))
                    else:
                        sec=(setting_int('sunwin_poll_seconds',4,2,60) if table=='sunwin' else
                             setting_int('max789_poll_seconds',3,2,60) if table.startswith('max789_') else
                             setting_int('lc79_poll_seconds',3,2,60))
                    due[table]=time.time()+sec
        except Exception:
            pass
        time.sleep(0.8)


def start_background_predictor():
    global _BG_STARTED
    with _BG_START_LOCK:
        if _BG_STARTED:return
        _BG_STARTED=True;threading.Thread(target=_background_loop,name='background-predictor',daemon=True).start()


# =============================================================
# ACCOUNT / WALLET / DEPOSIT PORTAL
# =============================================================
def init_account_db():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          password_salt TEXT NOT NULL,
          balance_vnd INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          signup_ip TEXT,
          signup_device_hash TEXT,
          last_login_at TEXT,
          last_login_ip TEXT,
          enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS account_devices(
          account_id INTEGER NOT NULL,
          device_hash TEXT NOT NULL,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          ip_address TEXT,
          user_agent TEXT,
          PRIMARY KEY(account_id,device_hash)
        );
        CREATE TABLE IF NOT EXISTS account_sessions(
          session_id TEXT PRIMARY KEY,
          account_id INTEGER NOT NULL,
          device_hash TEXT NOT NULL,
          ua_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          revoked INTEGER NOT NULL DEFAULT 0,
          ip_address TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_account_sessions_account ON account_sessions(account_id,revoked,expires_at);
        CREATE TABLE IF NOT EXISTS account_keys(
          account_id INTEGER NOT NULL,
          key_id INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          plain_hint TEXT DEFAULT '',
          UNIQUE(account_id,key_id)
        );
        CREATE INDEX IF NOT EXISTS idx_account_keys_account ON account_keys(account_id,active);
        CREATE TABLE IF NOT EXISTS wallet_transactions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          amount INTEGER NOT NULL,
          balance_after INTEGER NOT NULL,
          ref_type TEXT,
          ref_id INTEGER,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wallet_account ON wallet_transactions(account_id,id DESC);
        CREATE TABLE IF NOT EXISTS deposits(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          request_code TEXT UNIQUE NOT NULL,
          amount INTEGER NOT NULL,
          transfer_content TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'created',
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          user_sent_at TEXT,
          reviewed_at TEXT,
          review_note TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_deposits_account ON deposits(account_id,id DESC);
        CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status,id DESC);
        CREATE TABLE IF NOT EXISTS account_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event TEXT NOT NULL,
          account_id INTEGER,
          detail_json TEXT DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_account_events_id ON account_events(id);
        CREATE TABLE IF NOT EXISTS password_resets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          email TEXT NOT NULL,
          code_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          used_at TEXT,
          request_ip TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_password_resets_email ON password_resets(email,id DESC);
        ''')
        cols={r['name'] for r in con.execute('PRAGMA table_info(accounts)').fetchall()}
        if 'email' not in cols:
            con.execute('ALTER TABLE accounts ADD COLUMN email TEXT')
        try:
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_email_unique ON accounts(lower(email)) WHERE email IS NOT NULL AND email<>''")
        except sqlite3.Error:
            pass
        for sk,sv in {
            'site_announcement':'Chào mừng bạn đến TAIXIUTOOL.',
            'notice_enabled':'1','notice_title':'Thông báo',
            'notice_body':'Theo dõi kênh hỗ trợ để nhận cập nhật mới nhất từ hệ thống.',
            'notice_telegram_url':'','notice_zalo_url':'','notice_support_phone':'','notice_remind_minutes':'60',
            'bank_code':'970443','bank_account':'0988712947','bank_account_name':'TRUONG VAN NGOC DOANH',
            'support_report_text':'Hỗ trợ / báo lỗi'
        }.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",(sk,sv,now_iso()))
        # Default VietQR receiver; only fills blank values, admin can still change them later.
        for _k,_v in {'bank_code':'970443','bank_account':'0988712947','bank_account_name':'TRUONG VAN NGOC DOANH'}.items():
            con.execute("UPDATE settings SET value=?,updated_at=? WHERE key=? AND (value IS NULL OR trim(value)='')",(_v,now_iso(),_k))

def _account_event(event, account_id=None, **detail):
    try:
        with db() as con:
            con.execute("INSERT INTO account_events(event,account_id,detail_json,created_at) VALUES(?,?,?,?)",
                        (str(event)[:60],account_id,json.dumps(detail,ensure_ascii=False,separators=(',',':')),now_iso()))
    except Exception:
        pass

def _password_hash(password,salt_hex=None):
    salt=bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    out=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,210000)
    return out.hex(),salt.hex()

def _account_ua_hash(ua=None):
    raw=(ua if ua is not None else request.headers.get('User-Agent','')) or ''
    return hashlib.sha256(raw.encode('utf-8','ignore')).hexdigest()

def _create_account_session(uid,device):
    device=str(device or '').strip()
    if not device: raise RuntimeError('Không nhận diện được thiết bị')
    dh=device_hash(device);sid=secrets.token_urlsafe(28);now=datetime.now(timezone.utc)
    hours=setting_int('account_session_hours',12,1,168);exp=now+timedelta(hours=hours)
    ua_hash=_account_ua_hash();ip=client_ip()
    with db() as con:
        # Strict mode: one active browser session per account. Logging in again revokes the old one.
        con.execute('UPDATE account_sessions SET revoked=1 WHERE account_id=? AND revoked=0',(int(uid),))
        con.execute('''INSERT INTO account_sessions(session_id,account_id,device_hash,ua_hash,created_at,last_seen,expires_at,revoked,ip_address)
                       VALUES(?,?,?,?,?,?,?,0,?)''',(sid,int(uid),dh,ua_hash,now.isoformat(),now.isoformat(),exp.isoformat(),ip))
        # Opportunistic cleanup.
        con.execute('DELETE FROM account_sessions WHERE expires_at<?',( (now-timedelta(days=7)).isoformat(), ))
    token=sign_token({'typ':'account','uid':int(uid),'sid':sid,'dev':dh,'exp':int(exp.timestamp())})
    return token,exp.isoformat()

def _current_account():
    auth=request.headers.get('Authorization','')
    if not auth.startswith('Bearer '):return None
    p=verify_token(auth[7:])
    if not p or p.get('typ')!='account' or not p.get('uid') or not p.get('sid') or not p.get('dev'):return None
    raw_device=str(request.headers.get('X-Device-ID') or '').strip()
    if not raw_device:return None
    dh=device_hash(raw_device)
    if not hmac.compare_digest(str(p.get('dev')),dh):return None
    now=datetime.now(timezone.utc);ua_hash=_account_ua_hash()
    with db() as con:
        sess=con.execute('''SELECT * FROM account_sessions WHERE session_id=? AND account_id=? AND revoked=0 AND expires_at>?''',
                         (str(p['sid']),int(p['uid']),now.isoformat())).fetchone()
        if not sess:return None
        if not hmac.compare_digest(str(sess['device_hash']),dh):return None
        # Bind the session to the browser family too. This blocks copied localStorage tokens on another browser.
        if sess['ua_hash'] and not hmac.compare_digest(str(sess['ua_hash']),ua_hash):return None
        con.execute('UPDATE account_sessions SET last_seen=?,ip_address=? WHERE session_id=?',(now.isoformat(),client_ip(),str(p['sid'])))
        row=con.execute('SELECT * FROM accounts WHERE id=? AND enabled=1',(int(p['uid']),)).fetchone()
    if row:
        request.account_session_id=str(p['sid']);request.account_device_hash=dh
    return row

def require_account(fn):
    def wrap(*a,**kw):
        row=_current_account()
        if not row:return jsonify({'detail':'Phiên tài khoản đã hết hạn, hãy đăng nhập lại'}),401
        request.account=row
        return fn(*a,**kw)
    wrap.__name__=fn.__name__
    return wrap

def _active_account_key(con,uid):
    now=now_iso()
    return con.execute('''SELECT k.*,ak.plain_hint FROM account_keys ak JOIN keys k ON k.id=ak.key_id
      WHERE ak.account_id=? AND ak.active=1 AND k.enabled=1 AND k.expires_at>?
      ORDER BY k.expires_at DESC,k.id DESC LIMIT 1''',(uid,now)).fetchone()

def _account_profile(uid):
    with db() as con:
        a=con.execute('SELECT * FROM accounts WHERE id=?',(uid,)).fetchone()
        k=_active_account_key(con,uid)
        tx=con.execute('SELECT id,kind,amount,balance_after,note,created_at FROM wallet_transactions WHERE account_id=? ORDER BY id DESC LIMIT 12',(uid,)).fetchall()
        active_sessions=con.execute('SELECT COUNT(*) c FROM account_sessions WHERE account_id=? AND revoked=0 AND expires_at>?',(uid,now_iso())).fetchone()['c']
    return {
      'id':a['id'],'username':a['username'],'email':(a['email'] or '' if 'email' in a.keys() else ''),'balance_vnd':int(a['balance_vnd'] or 0),
      'created_at':a['created_at'],'last_login_at':a['last_login_at'],'last_login_ip':a['last_login_ip'],
      'key':None if not k else {'id':k['id'],'label':k['label'],'expires_at':k['expires_at'],'days':k['days'],'max_devices':k['max_devices'],'hint':k['plain_hint'] or '','lifetime':('VĨNH VIỄN' in str(k['label']).upper())},
      'wallet':[dict(x) for x in tx],
      'security':{'strict_single_session':True,'active_sessions':int(active_sessions or 0),'device_bound':True,'session_hours':setting_int('account_session_hours',12,1,168)}
    }

def _bind_key_device(k,device,ip,ua):
    dh=device_hash(device);now=now_iso();os_name=detect_os(ua);browser=detect_browser(ua)
    with db() as con:
        exists=con.execute('SELECT 1 FROM devices WHERE key_id=? AND device_hash=?',(k['id'],dh)).fetchone()
        if not exists:
            count=con.execute('SELECT COUNT(*) c FROM devices WHERE key_id=?',(k['id'],)).fetchone()['c']
            if count>=int(k['max_devices']):raise RuntimeError('Key đã đạt giới hạn thiết bị')
            con.execute('''INSERT INTO devices(key_id,device_hash,first_seen,last_seen,ip_address,os_name,user_agent,browser_name)
              VALUES(?,?,?,?,?,?,?,?)''',(k['id'],dh,now,now,ip,os_name,ua,browser))
        else:
            con.execute('UPDATE devices SET last_seen=?,ip_address=?,os_name=?,user_agent=?,browser_name=? WHERE key_id=? AND device_hash=?',
                        (now,ip,os_name,ua,browser,k['id'],dh))
    _register_background_watch(k['id'],dh,k['expires_at'])
    return dh

def _bank_qr_url(amount,content):
    from urllib.parse import quote
    code=get_setting('bank_code','').strip();acc=get_setting('bank_account','').strip();name=get_setting('bank_account_name','').strip()
    if not code or not acc:return ''
    return f"https://img.vietqr.io/image/{quote(code)}-{quote(acc)}-compact2.png?amount={int(amount)}&addInfo={quote(content)}&accountName={quote(name)}"

def _valid_email(email):
    email=str(email or '').strip().lower()
    return bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",email)) and len(email)<=254

def _reset_code_hash(email,code):
    msg=(str(email).lower().strip()+"|"+str(code)).encode('utf-8')
    return hmac.new(TOKEN_SECRET.encode('utf-8'),msg,hashlib.sha256).hexdigest()

def _send_reset_email(email,code):
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not SMTP_FROM_EMAIL:
        raise RuntimeError('Hệ thống email chưa được cấu hình. Liên hệ admin.')
    msg=EmailMessage()
    msg['Subject']='Mã đặt lại mật khẩu TAIXIUTOOL'
    msg['From']=f'{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>'
    msg['To']=email
    msg.set_content('TAIXIUTOOL\n\nMã xác minh đặt lại mật khẩu của bạn là: '+str(code)+'\n\nMã có hiệu lực trong '+str(RESET_CODE_TTL_MINUTES)+' phút.\nNếu bạn không yêu cầu đổi mật khẩu, hãy bỏ qua email này.\n')
    if SMTP_PORT==465:
        with smtplib.SMTP_SSL(SMTP_HOST,SMTP_PORT,timeout=15,context=ssl.create_default_context()) as server:
            server.login(SMTP_USER,SMTP_PASS);server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=15) as server:
            server.ehlo()
            if SMTP_USE_TLS:
                server.starttls(context=ssl.create_default_context());server.ehlo()
            server.login(SMTP_USER,SMTP_PASS);server.send_message(msg)

@app.post('/api/account/register')
def account_register():
    d=request.get_json(silent=True) or {}
    username=str(d.get('username') or '').strip().lower();email=str(d.get('email') or '').strip().lower();password=str(d.get('password') or '');device=str(d.get('device_id') or '').strip()
    if not re.fullmatch(r'[a-z0-9_]{4,20}',username):return jsonify({'detail':'Tên tài khoản 4-20 ký tự, chỉ gồm a-z, 0-9 và _'}),400
    if not _valid_email(email):return jsonify({'detail':'Email không hợp lệ'}),400
    if len(password)<8 or len(password)>72:return jsonify({'detail':'Mật khẩu cần từ 8 đến 72 ký tự'}),400
    if not re.search(r'[A-Za-z]',password) or not re.search(r'\d',password):return jsonify({'detail':'Mật khẩu phải có cả chữ và số'}),400
    if not device:return jsonify({'detail':'Không nhận diện được thiết bị'}),400
    ip=client_ip();dh=device_hash(device);ua=request.headers.get('User-Agent','')[:500]
    with db() as con:
        device_limit=setting_int('account_device_limit',3,1,20);ip_limit=setting_int('account_ip_limit',3,1,50)
        dcount=con.execute('SELECT COUNT(DISTINCT id) c FROM accounts WHERE signup_device_hash=?',(dh,)).fetchone()['c']
        ipcount=con.execute('SELECT COUNT(DISTINCT id) c FROM accounts WHERE signup_ip=?',(ip,)).fetchone()['c']
        if dcount>=device_limit or (ip not in ('unknown','127.0.0.1','::1') and ipcount>=ip_limit):return jsonify({'detail':f'M tạo lắm thế, tạo ít thôi 😭 Giới hạn hiện tại: {device_limit} tài khoản/thiết bị và {ip_limit} tài khoản/IP.'}),429
        if con.execute('SELECT 1 FROM accounts WHERE username=?',(username,)).fetchone():return jsonify({'detail':'Tên tài khoản đã tồn tại'}),409
        if con.execute('SELECT 1 FROM accounts WHERE lower(email)=lower(?)',(email,)).fetchone():return jsonify({'detail':'Email này đã được sử dụng'}),409
        ph,salt=_password_hash(password);now=now_iso()
        cur=con.execute('INSERT INTO accounts(username,email,password_hash,password_salt,balance_vnd,created_at,signup_ip,signup_device_hash,last_login_at,last_login_ip,enabled) VALUES(?,?,?,?,0,?,?,?,?,?,1)',(username,email,ph,salt,now,ip,dh,now,ip));uid=cur.lastrowid
        con.execute('INSERT INTO account_devices(account_id,device_hash,first_seen,last_seen,ip_address,user_agent) VALUES(?,?,?,?,?,?)',(uid,dh,now,now,ip,ua))
    _account_event('account_registered',uid,username=username,email=email,ip=ip,device=dh[:12])
    token,session_expires_at=_create_account_session(uid,device);return jsonify({'ok':True,'token':token,'session_expires_at':session_expires_at,'profile':_account_profile(uid)})

@app.post('/api/account/login')
def account_login():
    d=request.get_json(silent=True) or {};identity=str(d.get('username') or d.get('identity') or '').strip().lower();password=str(d.get('password') or '');device=str(d.get('device_id') or '').strip()
    if not device:return jsonify({'detail':'Không nhận diện được thiết bị'}),400
    with db() as con:a=con.execute('SELECT * FROM accounts WHERE (username=? OR lower(email)=lower(?)) AND enabled=1',(identity,identity)).fetchone()
    if not a:return jsonify({'detail':'Sai tài khoản/email hoặc mật khẩu'}),401
    ph,_=_password_hash(password,a['password_salt'])
    if not hmac.compare_digest(ph,a['password_hash']):return jsonify({'detail':'Sai tài khoản/email hoặc mật khẩu'}),401
    ip=client_ip();dh=device_hash(device);ua=request.headers.get('User-Agent','')[:500];now=now_iso()
    with db() as con:
        con.execute('UPDATE accounts SET last_login_at=?,last_login_ip=? WHERE id=?',(now,ip,a['id']))
        con.execute('INSERT INTO account_devices(account_id,device_hash,first_seen,last_seen,ip_address,user_agent) VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,device_hash) DO UPDATE SET last_seen=excluded.last_seen,ip_address=excluded.ip_address,user_agent=excluded.user_agent',(a['id'],dh,now,now,ip,ua))
    try:
        with db() as con:k=_active_account_key(con,a['id'])
        if k:_register_background_watch(k['id'],dh,k['expires_at'])
    except Exception:pass
    _account_event('account_login',a['id'],username=a['username'],ip=ip,device=dh[:12])
    token,session_expires_at=_create_account_session(a['id'],device);return jsonify({'ok':True,'token':token,'session_expires_at':session_expires_at,'profile':_account_profile(a['id'])})

@app.post('/api/account/password-reset/request')
def password_reset_request():
    d=request.get_json(silent=True) or {};email=str(d.get('email') or '').strip().lower();ip=client_ip()
    if not _valid_email(email):return jsonify({'detail':'Email không hợp lệ'}),400
    if not SMTP_USER or not SMTP_PASS:return jsonify({'detail':'Hệ thống email chưa được cấu hình'}),503
    with db() as con:
        a=con.execute('SELECT id,username,email FROM accounts WHERE lower(email)=lower(?) AND enabled=1',(email,)).fetchone()
        recent=con.execute('SELECT created_at FROM password_resets WHERE lower(email)=lower(?) ORDER BY id DESC LIMIT 1',(email,)).fetchone()
        if recent:
            try:
                if (datetime.now(timezone.utc)-datetime.fromisoformat(recent['created_at'])).total_seconds()<60:return jsonify({'detail':'Vui lòng chờ 60 giây trước khi gửi mã mới'}),429
            except Exception:pass
        if not a:return jsonify({'ok':True,'message':'Nếu email tồn tại, mã xác minh sẽ được gửi.'})
        code=f'{secrets.randbelow(1000000):06d}';now=datetime.now(timezone.utc);exp=now+timedelta(minutes=RESET_CODE_TTL_MINUTES)
        con.execute('INSERT INTO password_resets(account_id,email,code_hash,created_at,expires_at,request_ip) VALUES(?,?,?,?,?,?)',(a['id'],email,_reset_code_hash(email,code),now.isoformat(),exp.isoformat(),ip))
    try:_send_reset_email(email,code)
    except Exception:return jsonify({'detail':'Không gửi được email xác minh. Kiểm tra cấu hình SMTP.'}),503
    _account_event('password_reset_requested',a['id'],username=a['username'])
    return jsonify({'ok':True,'message':'Mã 6 số đã được gửi tới email của bạn.','expires_in':RESET_CODE_TTL_MINUTES*60})

@app.post('/api/account/password-reset/confirm')
def password_reset_confirm():
    d=request.get_json(silent=True) or {};email=str(d.get('email') or '').strip().lower();code=str(d.get('code') or '').strip();password=str(d.get('password') or '')
    if not _valid_email(email) or not re.fullmatch(r'\d{6}',code):return jsonify({'detail':'Email hoặc mã xác minh không hợp lệ'}),400
    if len(password)<8 or len(password)>72 or not re.search(r'[A-Za-z]',password) or not re.search(r'\d',password):return jsonify({'detail':'Mật khẩu mới cần 8-72 ký tự và có cả chữ lẫn số'}),400
    now=datetime.now(timezone.utc)
    with db() as con:
        r=con.execute('SELECT * FROM password_resets WHERE lower(email)=lower(?) AND used_at IS NULL ORDER BY id DESC LIMIT 1',(email,)).fetchone()
        if not r:return jsonify({'detail':'Không tìm thấy yêu cầu đặt lại mật khẩu'}),400
        try:
            if datetime.fromisoformat(r['expires_at'])<=now:return jsonify({'detail':'Mã xác minh đã hết hạn'}),400
        except Exception:return jsonify({'detail':'Mã xác minh không hợp lệ'}),400
        attempts=int(r['attempts'] or 0)
        if attempts>=6:return jsonify({'detail':'Bạn đã nhập sai quá nhiều lần. Hãy yêu cầu mã mới.'}),429
        if not hmac.compare_digest(str(r['code_hash']),_reset_code_hash(email,code)):
            con.execute('UPDATE password_resets SET attempts=attempts+1 WHERE id=?',(r['id'],));return jsonify({'detail':'Mã xác minh không đúng'}),400
        ph,salt=_password_hash(password)
        con.execute('UPDATE accounts SET password_hash=?,password_salt=? WHERE id=?',(ph,salt,r['account_id']))
        con.execute('UPDATE password_resets SET used_at=? WHERE id=?',(now.isoformat(),r['id']));con.execute('UPDATE account_sessions SET revoked=1 WHERE account_id=?',(r['account_id'],))
    _account_event('password_reset_done',r['account_id'])
    return jsonify({'ok':True,'message':'Đặt lại mật khẩu thành công. Bạn có thể đăng nhập ngay.'})

@app.get('/api/account/me')
@require_account
def account_me():
    return jsonify({'profile':_account_profile(request.account['id']),'announcement':get_setting('site_announcement','')})

@app.post('/api/account/logout')
@require_account
def account_logout():
    sid=getattr(request,'account_session_id','')
    if sid:
        with db() as con:con.execute('UPDATE account_sessions SET revoked=1 WHERE session_id=?',(sid,))
    _account_event('account_logout',request.account['id'],device=getattr(request,'account_device_hash','')[:12])
    return jsonify({'ok':True})

@app.post('/api/account/link-key')
@require_account
def account_link_key():
    d=request.get_json(silent=True) or {};plain=str(d.get('key') or '').strip();uid=request.account['id']
    if not plain:return jsonify({'detail':'Nhập key cần liên kết'}),400
    with db() as con:
        k=con.execute('SELECT * FROM keys WHERE key_hash=? AND enabled=1',(key_hash(plain),)).fetchone()
        if not k or datetime.fromisoformat(k['expires_at'])<=datetime.now(timezone.utc):return jsonify({'detail':'Key không hợp lệ hoặc đã hết hạn'}),400
        if 'owner_account_id' in k.keys() and k['owner_account_id'] is not None and int(k['owner_account_id'])!=int(uid):
            return jsonify({'detail':'Key này thuộc tài khoản khác'}),409
        owner=con.execute('SELECT account_id FROM account_keys WHERE key_id=? AND active=1',(k['id'],)).fetchone()
        if owner and owner['account_id']!=uid:return jsonify({'detail':'Key này đã liên kết với tài khoản khác'}),409
        con.execute('INSERT OR IGNORE INTO account_keys(account_id,key_id,created_at,active,plain_hint) VALUES(?,?,?,1,?)',(uid,k['id'],now_iso(),plain[-6:]))
    _account_event('key_linked',uid,key_id=k['id'])
    return jsonify({'ok':True,'profile':_account_profile(uid)})

@app.post('/api/account/game-session')
@require_account
def account_game_session():
    d=request.get_json(silent=True) or {};device=str(d.get('device_id') or '').strip();uid=request.account['id']
    if not device:return jsonify({'detail':'Không nhận diện được thiết bị'}),400
    with db() as con:k=_active_account_key(con,uid)
    if not k:
        if str(request.args.get('allow_guest') or '').strip().lower() in ('1','true','yes','on'):
            return jsonify({'ok':True,'guest':True,'token':None,'expires_at':None,'reason':'no_active_key'})
        return jsonify({'detail':'Tài khoản chưa có key còn hạn. Hãy mua hoặc liên kết key.'}),403
    try:dh=_bind_key_device(k,device,client_ip(),request.headers.get('User-Agent',''))
    except RuntimeError as e:return jsonify({'detail':str(e)}),403
    exp=min(int(datetime.fromisoformat(k['expires_at']).timestamp()),int(time.time())+SESSION_SECONDS)
    token=sign_token({'kid':k['id'],'aid':int(uid),'dev':dh,'dh':dh,'exp':exp})
    return jsonify({'ok':True,'token':token,'expires_at':k['expires_at'],'key_id':k['id']})

@app.post('/api/account/deposits')
@require_account
def create_deposit():
    d=request.get_json(silent=True) or {};uid=request.account['id']
    try:amount=int(d.get('amount') or 0)
    except Exception:amount=0
    min_amount=setting_int('deposit_min_vnd',10000,1000,100000000)
    max_amount=setting_int('deposit_max_vnd',100000000,min_amount,1000000000)
    ttl=setting_int('deposit_ttl_minutes',10,3,60)
    if amount<min_amount:return jsonify({'detail':f'Nạp tối thiểu {min_amount:,}đ'.replace(',', '.') }),400
    if amount>max_amount:return jsonify({'detail':f'Số tiền nạp tối đa {max_amount:,}đ'.replace(',', '.') }),400
    now=datetime.now(timezone.utc);exp=now+timedelta(minutes=ttl)
    with db() as con:
        old=con.execute("SELECT id FROM deposits WHERE account_id=? AND status IN ('created','sent') AND expires_at>? ORDER BY id DESC LIMIT 1",(uid,now.isoformat())).fetchone()
        if old:return jsonify({'detail':'Bạn đang có một yêu cầu nạp chưa hết hạn. Hãy hoàn tất hoặc chờ mã hiện tại hết hiệu lực.'}),409
        username=request.account['username'];code='DP'+secrets.token_hex(3).upper();content='ngulam+'+username
        cur=con.execute('''INSERT INTO deposits(account_id,request_code,amount,transfer_content,status,created_at,expires_at)
          VALUES(?,?,?,?,?,?,?)''',(uid,code,amount,content,'created',now.isoformat(),exp.isoformat()));did=cur.lastrowid
    _account_event('deposit_created',uid,deposit_id=did,amount=amount,username=request.account['username'])
    return jsonify({'ok':True,'deposit':{'id':did,'code':code,'amount':amount,'content':content,'status':'created','expires_at':exp.isoformat(),'qr_url':_bank_qr_url(amount,content),'bank_code':get_setting('bank_code',''),'bank_account':get_setting('bank_account',''),'bank_account_name':get_setting('bank_account_name','')}})

@app.get('/api/account/deposits/current')
@require_account
def current_deposit():
    uid=request.account['id'];now=now_iso()
    with db() as con:
        con.execute("UPDATE deposits SET status='expired' WHERE account_id=? AND status IN ('created','sent') AND expires_at<=?",(uid,now))
        r=con.execute("SELECT * FROM deposits WHERE account_id=? ORDER BY id DESC LIMIT 1",(uid,)).fetchone()
    if not r:return jsonify({'deposit':None})
    x=dict(r);x['qr_url']=_bank_qr_url(x['amount'],x['transfer_content']);x['bank_code']=get_setting('bank_code','');x['bank_account']=get_setting('bank_account','');x['bank_account_name']=get_setting('bank_account_name','')
    return jsonify({'deposit':x})

@app.post('/api/account/deposits/<int:deposit_id>/sent')
@require_account
def mark_deposit_sent(deposit_id):
    uid=request.account['id'];now=datetime.now(timezone.utc)
    with db() as con:
        r=con.execute('SELECT * FROM deposits WHERE id=? AND account_id=?',(deposit_id,uid)).fetchone()
        if not r:return jsonify({'detail':'Không tìm thấy yêu cầu nạp'}),404
        if r['status'] not in ('created','sent'):return jsonify({'detail':'Yêu cầu này đã được xử lý'}),409
        if datetime.fromisoformat(r['expires_at'])<=now:return jsonify({'detail':'Mã nạp đã hết hiệu lực'}),410
        con.execute("UPDATE deposits SET status='sent',user_sent_at=? WHERE id=?",(now.isoformat(),deposit_id))
    _account_event('deposit_sent',uid,deposit_id=deposit_id,amount=r['amount'],username=request.account['username'],content=r['transfer_content'],request_code=r['request_code'])
    return jsonify({'ok':True,'status':'sent','message':'Đã gửi yêu cầu xác nhận. Số dư sẽ cập nhật sau khi giao dịch được duyệt.'})

@app.post('/api/account/buy-key')
@require_account
def account_buy_key():
    d=request.get_json(silent=True) or {};uid=request.account['id']
    try:pid=int(d.get('plan_id'))
    except Exception:return jsonify({'detail':'Gói key không hợp lệ'}),400
    now=datetime.now(timezone.utc)
    with db() as con:
        plan=con.execute('SELECT * FROM plans WHERE id=? AND enabled=1',(pid,)).fetchone()
        a=con.execute('SELECT * FROM accounts WHERE id=?',(uid,)).fetchone()
        if not plan:return jsonify({'detail':'Gói key không tồn tại'}),404
        price=int(plan['price_vnd'] or 0)
        if int(a['balance_vnd'] or 0)<price:return jsonify({'detail':'Số dư không đủ. Hãy nạp thêm tiền.'}),402
        plain='TAIXIU-'+secrets.token_urlsafe(12).replace('_','').replace('-','').upper()[:16]
        duration=int(plan['duration_seconds'] or 0) if 'duration_seconds' in plan.keys() else 0; lifetime=int(plan['lifetime'] or 0) if 'lifetime' in plan.keys() else 0; exp=now+timedelta(seconds=(3153600000 if lifetime else (duration or max(1,int(plan['days'] or 1))*86400)));label=f"{plan['name']} · {a['username']}"
        cur=con.execute('''INSERT INTO keys(key_hash,label,created_at,expires_at,enabled,max_devices,days,price_vnd,plan_id,owner_account_id)
          VALUES(?,?,?,?,1,?,?,?,?,?)''',(key_hash(plain),label,now.isoformat(),exp.isoformat(),plan['max_devices'],plan['days'],price,pid,uid));kid=cur.lastrowid
        con.execute('UPDATE account_keys SET active=0 WHERE account_id=?',(uid,))
        con.execute('INSERT INTO account_keys(account_id,key_id,created_at,active,plain_hint) VALUES(?,?,?,1,?)',(uid,kid,now.isoformat(),plain[-6:]))
        newbal=int(a['balance_vnd'])-price
        con.execute('UPDATE accounts SET balance_vnd=? WHERE id=?',(newbal,uid))
        con.execute("INSERT INTO wallet_transactions(account_id,kind,amount,balance_after,ref_type,ref_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (uid,'key_purchase',-price,newbal,'key',kid,label,now.isoformat()))
    try:
        with db() as con:
            dev=con.execute('SELECT device_hash FROM account_devices WHERE account_id=? ORDER BY last_seen DESC LIMIT 1',(uid,)).fetchone()
        if dev:_register_background_watch(kid,dev['device_hash'],exp.isoformat())
    except Exception:pass
    _account_event('key_purchased',uid,key_id=kid,plan_id=pid,price=price,username=request.account['username'])
    return jsonify({'ok':True,'expires_at':exp.isoformat(),'balance_vnd':newbal,'profile':_account_profile(uid),'message':'Key đã được gắn trực tiếp vào tài khoản này.'})

@app.get('/api/account/plans')
@require_account
def account_plans():
    with db() as con:rows=con.execute('SELECT id,name,days,price_vnd,max_devices,duration_seconds,lifetime FROM plans WHERE enabled=1 ORDER BY sort_order,id').fetchall()
    return jsonify({'plans':[dict(x) for x in rows]})

@app.get('/api/admin/accounts')
@require_admin
def admin_accounts():
    with db() as con:
        rows=con.execute('''SELECT a.id,a.username,a.email,a.balance_vnd,a.created_at,a.last_login_at,a.last_login_ip,a.enabled,
          COUNT(DISTINCT ak.key_id) key_count FROM accounts a LEFT JOIN account_keys ak ON ak.account_id=a.id GROUP BY a.id ORDER BY a.id DESC LIMIT 100''').fetchall()
    return jsonify({'accounts':[dict(x) for x in rows]})

@app.get('/api/account/transactions')
@require_account
def account_transactions():
    uid=request.account['id']
    try: limit=max(1,min(100,int(request.args.get('limit','40'))))
    except Exception: limit=40
    with db() as con:
        tx=[dict(x) for x in con.execute("""SELECT id,kind,amount,balance_after,ref_type,ref_id,note,created_at
          FROM wallet_transactions WHERE account_id=? ORDER BY id DESC LIMIT ?""",(uid,limit)).fetchall()]
        deps=[dict(x) for x in con.execute("""SELECT id,request_code,amount,transfer_content,status,created_at,expires_at,user_sent_at,reviewed_at
          FROM deposits WHERE account_id=? ORDER BY id DESC LIMIT ?""",(uid,limit)).fetchall()]
    return jsonify({'transactions':tx,'deposits':deps})

@app.get('/api/public/live-stats')
def public_live_stats():
    now=datetime.now(timezone.utc);start=now-timedelta(hours=24);online_cutoff=now-timedelta(minutes=10)
    with db() as con:
        try:
            online=int(con.execute("SELECT COUNT(DISTINCT account_id) c FROM account_devices WHERE last_seen>=?",(online_cutoff.isoformat(),)).fetchone()['c'] or 0)
        except Exception: online=0
        row=con.execute("""SELECT COUNT(*) total,
          SUM(CASE WHEN actual IN ('T','X') AND side IN ('T','X') THEN 1 ELSE 0 END) settled,
          SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) wins
          FROM global_history WHERE created_at>=?""",(start.isoformat(),)).fetchone()
        total=int(row['total'] or 0);settled=int(row['settled'] or 0);wins=int(row['wins'] or 0)
        accounts=int(con.execute("SELECT COUNT(*) c FROM accounts WHERE enabled=1").fetchone()['c'] or 0)
    accuracy=round(wins*100/settled,1) if settled else None
    sources={}
    for t in ('hu','md5','sunwin','max789_hu','max789_md5'):
        st=_SOURCE_STATE.get(t) or {}
        age=max(0,int(time.time()-float(st.get('changed') or time.time()))) if st else None
        sources[t]={'latest_session':st.get('sid'),'age_seconds':age,'state':'online' if age is not None and age<120 else ('waiting' if st else 'starting')}
    return jsonify({'ok':True,'online_now':online,'accounts_active':accounts,'sessions_24h':total,
                    'settled_24h':settled,'wins_24h':wins,'accuracy_24h':accuracy,'sources':sources,
                    'server_time':now.isoformat()})

@app.get('/api/admin/accounts/<int:account_id>')
@require_admin
def admin_account_detail(account_id):
    with db() as con:
        a=con.execute("""SELECT id,username,email,balance_vnd,created_at,signup_ip,signup_device_hash,last_login_at,last_login_ip,enabled
                         FROM accounts WHERE id=?""",(account_id,)).fetchone()
        if not a:return jsonify({'detail':'Không tìm thấy tài khoản'}),404
        devices=[dict(x) for x in con.execute("""SELECT device_hash,first_seen,last_seen,ip_address,user_agent FROM account_devices
                                                WHERE account_id=? ORDER BY last_seen DESC""",(account_id,)).fetchall()]
        tx=[dict(x) for x in con.execute("""SELECT id,kind,amount,balance_after,ref_type,ref_id,note,created_at FROM wallet_transactions
                                           WHERE account_id=? ORDER BY id DESC LIMIT 50""",(account_id,)).fetchall()]
        deps=[dict(x) for x in con.execute("""SELECT id,request_code,amount,transfer_content,status,created_at,expires_at,user_sent_at,reviewed_at
                                             FROM deposits WHERE account_id=? ORDER BY id DESC LIMIT 50""",(account_id,)).fetchall()]
    return jsonify({'account':dict(a),'devices':devices,'transactions':tx,'deposits':deps,
                    'password_note':'Mật khẩu được hash một chiều và không thể xem lại. Admin chỉ có thể đặt mật khẩu mới.'})

@app.patch('/api/admin/accounts/<int:account_id>/status')
@require_admin
def admin_account_status(account_id):
    d=request.get_json(silent=True) or {};enabled=1 if bool(d.get('enabled',True)) else 0
    with db() as con:
        a=con.execute('SELECT id,username FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not a:return jsonify({'detail':'Không tìm thấy tài khoản'}),404
        con.execute('UPDATE accounts SET enabled=? WHERE id=?',(enabled,account_id))
    _account_event('account_status_changed',account_id,username=a['username'],enabled=enabled)
    return jsonify({'ok':True,'enabled':bool(enabled),'username':a['username']})

@app.post('/api/admin/accounts/<int:account_id>/reset-password')
@require_admin
def admin_account_reset_password(account_id):
    d=request.get_json(silent=True) or {};password=str(d.get('password') or '')
    if len(password)<6 or len(password)>128:return jsonify({'detail':'Mật khẩu mới phải từ 6-128 ký tự'}),400
    with db() as con:
        a=con.execute('SELECT id,username FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not a:return jsonify({'detail':'Không tìm thấy tài khoản'}),404
        ph,salt=_password_hash(password);con.execute('UPDATE accounts SET password_hash=?,password_salt=? WHERE id=?',(ph,salt,account_id))
    _account_event('admin_password_reset',account_id,username=a['username'])
    return jsonify({'ok':True,'username':a['username']})

@app.delete('/api/admin/accounts/<int:account_id>')
@require_admin
def admin_delete_account(account_id):
    with db() as con:
        a=con.execute('SELECT id,username FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not a:return jsonify({'detail':'Không tìm thấy tài khoản'}),404
        con.execute('UPDATE keys SET owner_account_id=NULL WHERE owner_account_id=?',(account_id,))
        con.execute('DELETE FROM account_keys WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM account_devices WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM password_resets WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM wallet_transactions WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM deposits WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM account_events WHERE account_id=?',(account_id,))
        con.execute('DELETE FROM accounts WHERE id=?',(account_id,))
    return jsonify({'ok':True,'username':a['username']})

@app.get('/api/admin/deposits')
@require_admin
def admin_deposits():
    with db() as con:
        rows=con.execute('''SELECT d.*,a.username FROM deposits d JOIN accounts a ON a.id=d.account_id ORDER BY d.id DESC LIMIT 100''').fetchall()
    return jsonify({'deposits':[dict(x) for x in rows]})

@app.post('/api/admin/deposits/<int:deposit_id>/approve')
@require_admin
def admin_approve_deposit(deposit_id):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        r=con.execute("SELECT d.*,a.username,a.balance_vnd FROM deposits d JOIN accounts a ON a.id=d.account_id WHERE d.id=?",(deposit_id,)).fetchone()
        if not r:return jsonify({'detail':'Không tìm thấy yêu cầu nạp'}),404
        if r['status']=='approved':return jsonify({'ok':True,'already':True,'balance_vnd':r['balance_vnd']})
        if r['status']!='sent':return jsonify({'detail':'Yêu cầu chưa ở trạng thái chờ duyệt'}),409
        if datetime.fromisoformat(r['expires_at'])<=datetime.now(timezone.utc):
            con.execute("UPDATE deposits SET status='expired',reviewed_at=? WHERE id=?",(now_iso(),deposit_id))
            return jsonify({'detail':'Mã nạp đã hết hiệu lực'}),410
        newbal=int(r['balance_vnd'])+int(r['amount']);now=now_iso()
        con.execute('UPDATE accounts SET balance_vnd=? WHERE id=?',(newbal,r['account_id']))
        con.execute("UPDATE deposits SET status='approved',reviewed_at=? WHERE id=?",(now,deposit_id))
        con.execute("INSERT INTO wallet_transactions(account_id,kind,amount,balance_after,ref_type,ref_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (r['account_id'],'deposit',int(r['amount']),newbal,'deposit',deposit_id,'Nạp tiền đã duyệt',now))
    _account_event('deposit_approved',r['account_id'],deposit_id=deposit_id,amount=r['amount'],username=r['username'])
    return jsonify({'ok':True,'balance_vnd':newbal,'username':r['username'],'amount':r['amount']})

@app.post('/api/admin/deposits/<int:deposit_id>/reject')
@require_admin
def admin_reject_deposit(deposit_id):
    with db() as con:
        r=con.execute('SELECT * FROM deposits WHERE id=?',(deposit_id,)).fetchone()
        if not r:return jsonify({'detail':'Không tìm thấy yêu cầu nạp'}),404
        if r['status']=='approved':return jsonify({'detail':'Giao dịch đã duyệt, không thể từ chối'}),409
        con.execute("UPDATE deposits SET status='rejected',reviewed_at=? WHERE id=?",(now_iso(),deposit_id))
    _account_event('deposit_rejected',r['account_id'],deposit_id=deposit_id,amount=r['amount'])
    return jsonify({'ok':True})

@app.post('/api/admin/accounts/<int:account_id>/balance')
@require_admin
def admin_adjust_balance(account_id):
    d=request.get_json(silent=True) or {}
    try:delta=int(d.get('delta') or 0)
    except Exception:return jsonify({'detail':'Số tiền không hợp lệ'}),400
    note=str(d.get('note') or 'Admin điều chỉnh')[:160]
    with db() as con:
        a=con.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not a:return jsonify({'detail':'Không tìm thấy tài khoản'}),404
        newbal=max(0,int(a['balance_vnd'])+delta)
        actual=newbal-int(a['balance_vnd']);con.execute('UPDATE accounts SET balance_vnd=? WHERE id=?',(newbal,account_id))
        con.execute("INSERT INTO wallet_transactions(account_id,kind,amount,balance_after,ref_type,note,created_at) VALUES(?,?,?,?,?,?,?)",
                    (account_id,'admin_adjust',actual,newbal,'admin',note,now_iso()))
    _account_event('balance_adjusted',account_id,delta=actual,balance=newbal,username=a['username'])
    return jsonify({'ok':True,'balance_vnd':newbal,'delta':actual})

@app.get('/api/admin/account-events')
@require_admin
def admin_account_events():
    try:after=max(0,int(request.args.get('after_id','0')));limit=max(1,min(100,int(request.args.get('limit','50'))))
    except Exception:return jsonify({'detail':'Query không hợp lệ'}),400
    with db() as con:
        rows=con.execute('''SELECT e.id,e.event,e.account_id,e.detail_json,e.created_at,a.username FROM account_events e
          LEFT JOIN accounts a ON a.id=e.account_id WHERE e.id>? ORDER BY e.id ASC LIMIT ?''',(after,limit)).fetchall()
        latest=con.execute('SELECT COALESCE(MAX(id),0) m FROM account_events').fetchone()['m']
    out=[]
    for r in rows:
        x=dict(r)
        try:x['detail']=json.loads(x.pop('detail_json') or '{}')
        except Exception:x['detail']={}
        out.append(x)
    return jsonify({'events':out,'latest_id':latest})

@app.patch('/api/admin/portal-settings')
@require_admin
def admin_portal_settings():
    d=request.get_json(silent=True) or {};allowed={'site_announcement':600,'bank_code':30,'bank_account':40,'bank_account_name':100,'support_report_text':120,'tagline':120,'start_button_text':30,'login_title':80,'maintenance_message':240,'notice_title':80,'notice_body':1200,'notice_telegram_url':300,'notice_zalo_url':300,'notice_support_phone':40,'notice_enabled':8,'notice_remind_minutes':5}
    changed={}
    for k,maxlen in allowed.items():
        if k in d:
            v=str(d[k]).strip()[:maxlen];set_setting(k,v);changed[k]=v
    return jsonify({'ok':True,'changed':changed})

# =============================================================
# DYNAMIC GAME CATALOG — admin-extensible T/X sources
# =============================================================
_CUSTOM_GAME_CACHE={}

def _game_slug(raw):
    slug=re.sub(r'[^a-z0-9_-]+','-',str(raw or '').strip().lower()).strip('-_')
    return slug[:40]

def _custom_table(slug):
    return "custom__"+_game_slug(slug)

def _custom_slug_from_table(table):
    t=str(table or '')
    return t[len("custom__"):] if t.startswith("custom__") else ""

def _custom_games_rows(enabled_only=False):
    q="SELECT * FROM custom_games"
    if enabled_only:q+=" WHERE enabled=1"
    q+=" ORDER BY sort_order ASC,name COLLATE NOCASE ASC"
    with db() as con:rows=con.execute(q).fetchall()
    return [dict(r) for r in rows]

def _custom_game_by_slug(slug, enabled_only=False):
    slug=_game_slug(slug)
    q="SELECT * FROM custom_games WHERE slug=?"+(" AND enabled=1" if enabled_only else "")
    with db() as con:r=con.execute(q,(slug,)).fetchone()
    return dict(r) if r else None

def _custom_game_public(row):
    return {
      "slug":row["slug"],"name":row["name"],"description":row.get("description") or "",
      "game_url":row["game_url"],"image_url":row.get("image_url") or "",
      "enabled":bool(row.get("enabled",1)),"ready":bool((row.get("api_url") or "").strip()),
      "algo_mode":int(row.get("algo_mode") or 2),"poll_seconds":int(row.get("poll_seconds") or 4),
      "table":_custom_table(row["slug"])
    }

def _custom_api_url(table):
    slug=_custom_slug_from_table(table)
    row=_custom_game_by_slug(slug,enabled_only=True) if slug else None
    return row,(row.get("api_url") or "").strip() if row else ""

def get_custom_upstream(table):
    row,url=_custom_api_url(table)
    if not row:raise RuntimeError("Game tùy chỉnh không tồn tại hoặc đang tắt")
    if not url:raise RuntimeError(f"{row['name']} chưa cấu hình API")
    slot=_CUSTOM_GAME_CACHE.setdefault(table,{"ts":0.0,"data":None})
    lock=_UPSTREAM_LOCKS.setdefault(table,threading.Lock())
    with lock:
        current=_fetch_json_source(url,table,slot,f"TAIXIUTOOL-CUSTOM/{row['slug']}/1.0")
        hist_url=(row.get('history_api_url') or '').strip()
        if hist_url and hist_url!=url:
            hslot=_CUSTOM_GAME_CACHE.setdefault(table+'__history',{"ts":0.0,"data":None})
            history=_fetch_json_source(hist_url,table,hslot,f"TAIXIUTOOL-CUSTOM-HISTORY/{row['slug']}/1.0")
        else:history=current
        return current,history

def _custom_table_exists(table, enabled_only=False):
    slug=_custom_slug_from_table(table)
    return bool(slug and _custom_game_by_slug(slug,enabled_only=enabled_only))

def _is_allowed_history_table(table):
    return table in ("hu","md5","sunwin","max789_hu","max789_md5") or _custom_table_exists(table,False)

def _all_prediction_tables():
    out=["hu","md5","sunwin","max789_hu","max789_md5"]
    for row in _custom_games_rows(enabled_only=True):
        if (row.get("api_url") or "").strip():out.append(_custom_table(row["slug"]))
    return out

# =============================================================
# ROUTES
# =============================================================
@app.get("/api/game-config")
def game_config():
    return jsonify({
      "lc79_game_url":get_setting("lc79_game_url",LC79_GAME_URL),
      "lc79_enabled":setting_bool("lc79_enabled",True),
      "lc79_hu_ready":bool(get_setting("lc79_hu_api_url",UPSTREAM_HU).strip()),
      "lc79_md5_ready":bool(get_setting("lc79_md5_api_url",UPSTREAM_MD5).strip()),
      "sunwin_game_url":get_setting("sunwin_game_url",SUNWIN_GAME_URL),
      "sunwin_enabled":setting_bool("sunwin_enabled",True) and bool(get_setting("sunwin_api_url",SUNWIN_API).strip()),
      "sunwin_history_ready":bool((get_setting("sunwin_history_api_url","").strip() or get_setting("sunwin_api_url",SUNWIN_API).strip())),
      "max789_game_url":get_setting("max789_game_url",MAX789_GAME_URL),
      "max789_enabled":setting_bool("max789_enabled",True) and bool(get_setting("max789_hu_api_url",MAX789_HU_API).strip() and get_setting("max789_md5_api_url",MAX789_MD5_API).strip()),
      "game_open_mode":get_setting("game_open_mode","auto"),
      "custom_games":[_custom_game_public(x) for x in _custom_games_rows(enabled_only=True)]
    })

@app.get("/api/admin/games")
@require_admin
def admin_games_catalog():
    return jsonify({"games":[_custom_game_public(x)|{
      "api_url":x.get("api_url") or "","history_api_url":x.get("history_api_url") or "",
      "sort_order":int(x.get("sort_order") or 100)
    } for x in _custom_games_rows(False)]})

def _valid_http(v, optional=False):
    v=str(v or "").strip()
    if optional and not v:return ""
    if not re.match(r"^https?://[^\s]+$",v,re.I):raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")
    return v[:700]

@app.post("/api/admin/games")
@require_admin
def admin_add_game():
    d=request.get_json(silent=True) or {}
    slug=_game_slug(d.get("slug"))
    name=str(d.get("name") or "").strip()[:60]
    if not slug or len(slug)<2:return jsonify({"detail":"Slug game không hợp lệ"}),400
    if not name:return jsonify({"detail":"Thiếu tên game"}),400
    try:
        game_url=_valid_http(d.get("game_url"))
        image_url=_valid_http(d.get("image_url"),True)
        api_url=_valid_http(d.get("api_url"),True)
        history_url=_valid_http(d.get("history_api_url"),True)
        algo=max(1,min(3,int(d.get("algo_mode",2))))
        poll=max(2,min(60,int(d.get("poll_seconds",4))))
        order=max(1,min(999,int(d.get("sort_order",100))))
    except (ValueError,TypeError) as e:return jsonify({"detail":str(e)}),400
    stamp=now_iso()
    try:
        with db() as con:
            con.execute("""INSERT INTO custom_games(slug,name,description,game_url,image_url,api_url,history_api_url,algo_mode,poll_seconds,enabled,sort_order,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (slug,name,str(d.get("description") or "")[:160],game_url,image_url,api_url,history_url,algo,poll,1 if d.get("enabled",True) else 0,order,stamp,stamp))
    except sqlite3.IntegrityError:return jsonify({"detail":"Slug game đã tồn tại"}),409
    return jsonify({"ok":True,"game":_custom_game_public(_custom_game_by_slug(slug))})

@app.patch("/api/admin/games/<slug>")
@require_admin
def admin_edit_game(slug):
    row=_custom_game_by_slug(slug)
    if not row:return jsonify({"detail":"Không tìm thấy game"}),404
    d=request.get_json(silent=True) or {};updates={}
    try:
        if "name" in d:updates["name"]=str(d["name"]).strip()[:60]
        if "description" in d:updates["description"]=str(d["description"]).strip()[:160]
        if "game_url" in d:updates["game_url"]=_valid_http(d["game_url"])
        if "image_url" in d:updates["image_url"]=_valid_http(d["image_url"],True)
        if "api_url" in d:updates["api_url"]=_valid_http(d["api_url"],True)
        if "history_api_url" in d:updates["history_api_url"]=_valid_http(d["history_api_url"],True)
        if "algo_mode" in d:updates["algo_mode"]=max(1,min(3,int(d["algo_mode"])))
        if "poll_seconds" in d:updates["poll_seconds"]=max(2,min(60,int(d["poll_seconds"])))
        if "enabled" in d:updates["enabled"]=1 if bool(d["enabled"]) else 0
        if "sort_order" in d:updates["sort_order"]=max(1,min(999,int(d["sort_order"])))
    except (ValueError,TypeError) as e:return jsonify({"detail":str(e)}),400
    if not updates:return jsonify({"ok":True,"game":_custom_game_public(row)})
    updates["updated_at"]=now_iso()
    sql="UPDATE custom_games SET "+",".join(f"{k}=?" for k in updates)+" WHERE slug=?"
    with db() as con:con.execute(sql,tuple(updates.values())+(_game_slug(slug),))
    _CUSTOM_GAME_CACHE.pop(_custom_table(slug),None)
    return jsonify({"ok":True,"game":_custom_game_public(_custom_game_by_slug(slug))})

@app.delete("/api/admin/games/<slug>")
@require_admin
def admin_delete_game(slug):
    row=_custom_game_by_slug(slug)
    if not row:return jsonify({"detail":"Không tìm thấy game"}),404
    table=_custom_table(slug)
    with db() as con:
        con.execute("DELETE FROM custom_games WHERE slug=?",(_game_slug(slug),))
        con.execute("DELETE FROM learned_patterns WHERE table_name=?",(table,))
    _CUSTOM_GAME_CACHE.pop(table,None);_SOURCE_STATE.pop(table,None);_SOURCE_ERRORS.pop(table,None)
    return jsonify({"ok":True,"deleted":_game_slug(slug)})

@app.get("/api/config")
def public_config():
    return jsonify({
      "brand":get_setting("brand","TAIXIUTOOL"),
      "admin_contact":get_setting("admin_contact","@huanhoahong11111"),
      "free_key_hours":setting_int("free_key_hours",1,1,72),
      "free_daily_limit":setting_int("free_daily_limit",2,1,20),
      "lc79_poll_seconds":setting_int("lc79_poll_seconds",3,2,60),
      "sunwin_poll_seconds":setting_int("sunwin_poll_seconds",4,2,60),
      "max789_poll_seconds":setting_int("max789_poll_seconds",3,2,60),
      "history_refresh_seconds":setting_int("history_refresh_seconds",24,10,120),
      "history_limit":setting_int("history_limit",60,20,200),
      "lc79_algo_mode":setting_int("lc79_algo_mode",2,1,3),
      "sunwin_algo_mode":setting_int("sunwin_algo_mode",2,1,3),
      "max789_algo_mode":setting_int("max789_algo_mode",3,1,3),
      "gps_prompt":setting_bool("gps_prompt",True),
      "lc79_game_url":get_setting("lc79_game_url",LC79_GAME_URL),
      "lc79_hu_ready":bool(get_setting("lc79_hu_api_url",UPSTREAM_HU).strip()),
      "lc79_md5_ready":bool(get_setting("lc79_md5_api_url",UPSTREAM_MD5).strip()),
      "sunwin_game_url":get_setting("sunwin_game_url",SUNWIN_GAME_URL),
      "sunwin_source_ready":bool(get_setting("sunwin_api_url",SUNWIN_API).strip()),
      "max789_game_url":get_setting("max789_game_url",MAX789_GAME_URL),
      "site_announcement":get_setting("site_announcement",""),
      "notice_enabled":setting_bool("notice_enabled",True),
      "notice_title":get_setting("notice_title","Thông báo"),
      "notice_body":get_setting("notice_body",""),
      "notice_telegram_url":get_setting("notice_telegram_url",""),
      "notice_zalo_url":get_setting("notice_zalo_url",""),
      "notice_support_phone":get_setting("notice_support_phone",""),
      "notice_remind_minutes":setting_int("notice_remind_minutes",60,5,1440),
      "support_report_text":get_setting("support_report_text","Hỗ trợ / báo lỗi"),
      "tagline":get_setting("tagline","Gọn · nhanh · đồng bộ realtime"),
      "start_button_text":get_setting("start_button_text","BẮT ĐẦU"),
      "login_title":get_setting("login_title","Đăng nhập TAIXIUTOOL"),
      "ui_primary":get_setting("ui_primary","#49e8ff"),
      "ui_secondary":get_setting("ui_secondary","#766bff"),
      "ui_accent":get_setting("ui_accent","#ff66b8"),
      "ui_surface":get_setting("ui_surface","#07111b"),
      "ui_font_scale":setting_int("ui_font_scale",100,85,115),
      "ui_compact":setting_bool("ui_compact",True),
      "telegram_floating":setting_bool("telegram_floating",True),
      "maintenance_mode":setting_bool("maintenance_mode",False),
      "maintenance_message":get_setting("maintenance_message","Hệ thống đang bảo trì, vui lòng quay lại sau."),
      "deposit_min_vnd":setting_int("deposit_min_vnd",10000,1000,100000000),
      "deposit_max_vnd":setting_int("deposit_max_vnd",100000000,1000,1000000000),
      "deposit_ttl_minutes":setting_int("deposit_ttl_minutes",10,3,60),
      "account_device_limit":setting_int("account_device_limit",3,1,20),
      "account_ip_limit":setting_int("account_ip_limit",3,1,50),
    })


@app.get("/")
def root(): return send_from_directory(BASE,"index.html")
@app.get("/lc79-theme.mp3")
def theme_audio(): return send_from_directory(BASE,"lc79-theme.mp3")

@app.get('/assets/<path:name>')
def portal_asset(name):
    return send_from_directory(os.path.join(BASE,'assets'),name,max_age=86400)



def _report_tables(game):
    game=(game or '').lower().strip()
    if game=='lc79': return ('hu','md5')
    if game=='sunwin': return ('sunwin',)
    if game=='max789': return ('max789_hu','max789_md5')
    return ()

@app.get('/api/admin/daily-report')
@require_admin
def admin_daily_report():
    game=(request.args.get('game') or '').lower().strip()
    tables=_report_tables(game)
    if not tables:return jsonify({'detail':'game phải là lc79, sunwin hoặc max789'}),400
    try: hours=max(1,min(168,int(request.args.get('hours','24'))))
    except Exception:hours=24
    end=datetime.now(timezone.utc);start=end-timedelta(hours=hours)
    qmarks=','.join('?'*len(tables))
    params=[*tables,start.isoformat(),end.isoformat()]
    with db() as con:
        rows=con.execute(f'''SELECT table_name,session_id,side,confidence,reason,actual,correct,created_at,settled_at
                             FROM global_history WHERE table_name IN ({qmarks}) AND created_at>=? AND created_at<?
                             ORDER BY created_at ASC,id ASC''',params).fetchall()
    data=[dict(r) for r in rows]
    settled=[r for r in data if r.get('actual') in ('T','X') and r.get('side') in ('T','X')]
    wins=sum(1 for r in settled if int(r.get('correct') or 0)==1);losses=len(settled)-wins
    skips=sum(1 for r in data if r.get('side') not in ('T','X'))
    breakdown={}
    for t in tables:
        rr=[x for x in data if x['table_name']==t];ss=[x for x in rr if x.get('actual') in ('T','X') and x.get('side') in ('T','X')]
        ww=sum(1 for x in ss if int(x.get('correct') or 0)==1)
        breakdown[t]={'rows':len(rr),'settled':len(ss),'wins':ww,'losses':len(ss)-ww,'accuracy':round(ww*100/len(ss),2) if ss else 0.0}
    return jsonify({
        'game':game,'hours':hours,'period_start':start.isoformat(),'period_end':end.isoformat(),
        'summary':{'rows':len(data),'settled':len(settled),'wins':wins,'losses':losses,'skips':skips,
                   'accuracy':round(wins*100/len(settled),2) if settled else 0.0},
        'breakdown':breakdown,'rows':data
    })

@app.get('/api/admin/analysis-report')
@require_admin
def admin_analysis_report():
    try: hours=max(1,min(336,int(request.args.get('hours','48'))))
    except Exception: hours=48
    end=datetime.now(timezone.utc);start=end-timedelta(hours=hours)
    with db() as con:
        rows=[dict(x) for x in con.execute("""SELECT table_name,COUNT(*) rows,
          SUM(CASE WHEN actual IN ('T','X') AND side IN ('T','X') THEN 1 ELSE 0 END) settled,
          SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) wins,
          SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) losses
          FROM global_history WHERE created_at>=? GROUP BY table_name ORDER BY table_name""",(start.isoformat(),)).fetchall()]
        pats=[dict(x) for x in con.execute("""SELECT table_name,context_key,t_weight,x_weight,samples,updated_at
          FROM learned_patterns WHERE updated_at>=? ORDER BY samples DESC,updated_at DESC LIMIT 150""",(start.isoformat(),)).fetchall()]
    sources={}
    for t in ('hu','md5','sunwin','max789_hu','max789_md5'):
        st=_SOURCE_STATE.get(t) or {};age=None
        if st: age=max(0,int(time.time()-float(st.get('changed') or time.time())))
        sources[t]={'latest_session':st.get('sid'),'age_seconds':age,'state':'online' if age is not None and age<120 else ('waiting' if st else 'starting')}
    for r in rows:
        settled=int(r.get('settled') or 0);r['accuracy']=round(int(r.get('wins') or 0)*100/settled,2) if settled else 0.0
    return jsonify({'hours':hours,'period_start':start.isoformat(),'period_end':end.isoformat(),'tables':rows,
                    'learned_patterns':pats,'sources':sources})

@app.get('/api/admin/analysis-report-state')
@require_admin
def admin_analysis_report_state():
    return jsonify({'last_sent_at':get_setting('analysis_report_last_sent_at','') or ''})

@app.post('/api/admin/analysis-report-state')
@require_admin
def admin_analysis_report_mark():
    d=request.get_json(silent=True) or {};value=str(d.get('last_sent_at') or '')[:80]
    if not value:return jsonify({'detail':'Thiếu last_sent_at'}),400
    set_setting('analysis_report_last_sent_at',value)
    return jsonify({'ok':True,'last_sent_at':value})

@app.get('/api/admin/daily-report-state')
@require_admin
def admin_daily_report_state():
    return jsonify({'last_sent':get_setting('daily_report_last_sent','') or ''})

@app.post('/api/admin/daily-report-state')
@require_admin
def admin_daily_report_mark():
    d=request.get_json(silent=True) or {};value=str(d.get('last_sent') or '')[:40]
    if not value:return jsonify({'detail':'Thiếu last_sent'}),400
    set_setting('daily_report_last_sent',value)
    return jsonify({'ok':True,'last_sent':value})

@app.get("/health")
def health(): return jsonify({"ok":True,"service":"prediction-core","background":True,"engine":"htungvip-max-stable"})

def client_ip():
    # Railway/Cloudflare/reverse proxy: first forwarded address is the original client.
    xff=request.headers.get("X-Forwarded-For","").split(",")[0].strip()
    return xff or request.headers.get("CF-Connecting-IP","") or request.remote_addr or "unknown"

def detect_os(ua):
    u=(ua or "").lower()
    if "iphone" in u or "ipad" in u:return "iOS/iPadOS"
    if "android" in u:return "Android"
    if "windows" in u:return "Windows"
    if "mac os" in u or "macintosh" in u:return "macOS"
    if "linux" in u:return "Linux"
    return "Unknown"

def detect_browser(ua):
    u=(ua or "").lower()
    if "edg/" in u:return "Edge"
    if "opr/" in u or "opera" in u:return "Opera"
    if "crios/" in u:return "Chrome iOS"
    if "fxios/" in u:return "Firefox iOS"
    if "chrome/" in u and "safari/" in u:return "Chrome"
    if "safari/" in u and "version/" in u:return "Safari"
    if "firefox/" in u:return "Firefox"
    return "Unknown"

def approximate_location(ip):
    # Optional IP geolocation. This is approximate, not GPS. Disable with IP_GEO_ENABLED=0.
    if os.getenv("IP_GEO_ENABLED","1") != "1" or ip in ("unknown","127.0.0.1","::1"):
        return "Không xác định"
    try:
        r=requests.get(f"https://ipwho.is/{ip}",timeout=3)
        d=r.json()
        if not d.get("success",True):return "Không xác định"
        parts=[d.get("city"),d.get("region"),d.get("country")]
        return ", ".join(str(x) for x in parts if x)[:180] or "Không xác định"
    except Exception:return "Không xác định"

def log_event(event, key_id=None, dev_hash=None):
    try:
        ip=client_ip(); ua=request.headers.get("User-Agent","")[:500]
        with db() as con:
            con.execute("INSERT INTO analytics(event,key_id,device_hash,ip_address,os_name,user_agent,created_at) VALUES(?,?,?,?,?,?,?)",
                        (event,key_id,dev_hash,ip,detect_os(ua),ua,now_iso()))
    except Exception:
        pass


def _public_base():
    return PUBLIC_BASE_URL or request.host_url.rstrip("/")

def _sig(raw,purpose="free"):
    return hmac.new(TOKEN_SECRET.encode(),(purpose+"|"+raw).encode(),hashlib.sha256).hexdigest()

def _signed(raw,purpose): return raw+"."+_sig(raw,purpose)

def _unsign(token,purpose):
    raw,sig=token.split(".",1)
    if not hmac.compare_digest(sig,_sig(raw,purpose)):raise ValueError("bad signature")
    return raw

def _shorten(destination):
    """Create a Link4M URL with small retries for transient network/API failures."""
    if not LINK4M_API_TOKEN:
        raise RuntimeError("Chưa cấu hình LINK4M_API_TOKEN")
    last="Link4M không phản hồi"
    for attempt in range(3):
        try:
            r=requests.get(
                "https://link4m.co/api-shorten/v2",
                params={"api":LINK4M_API_TOKEN,"url":destination},
                headers={"Accept":"application/json","User-Agent":"TAIXIUTOOL"},
                timeout=9,
            )
            if r.status_code>=500:
                last=f"Link4M HTTP {r.status_code}"
                time.sleep(.35*(attempt+1));continue
            try:d=r.json()
            except Exception:
                last=f"Link4M trả dữ liệu không hợp lệ (HTTP {r.status_code})"
                time.sleep(.35*(attempt+1));continue
            short=d.get("shortenedUrl") or d.get("shortened_url") or d.get("url")
            status=str(d.get("status","")).lower()
            if short and str(short).startswith(("http://","https://")) and status in ("success","ok","1","true",""):
                return str(short)
            last=str(d.get("message") or d.get("error") or "Link4M không trả shortenedUrl")[:180]
        except Exception as e:
            last=str(e)[:180]
        time.sleep(.35*(attempt+1))
    raise RuntimeError(last)

def _vn_day_start(now):
    vn=now+timedelta(hours=7)
    return vn.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(hours=7)

def _new_verify_code():
    alpha="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alpha) for _ in range(6))

def _make_flow_token(flow_id,device_hash_value,expires_at):
    exp=int(datetime.fromisoformat(expires_at).timestamp())
    raw=f"{int(flow_id)}:{device_hash_value}:{exp}"
    return _signed(raw,"free-flow-v2")

def _resolve_flow_token(con,token,dh,now):
    # V51 stateless signed token: reopening the web no longer invalidates another tab/session.
    try:
        raw=_unsign(token,"free-flow-v2")
        fid_s,token_dh,exp_s=raw.split(":",2)
        if token_dh!=dh or int(exp_s)<int(now.timestamp()):raise ValueError("expired")
        flow=con.execute("SELECT * FROM free_flows WHERE id=?",(int(fid_s),)).fetchone()
        if not flow or flow["device_hash"]!=dh:raise ValueError("device")
        return flow
    except Exception:
        # Backward compatibility with V48-V50 flow tokens already stored on devices.
        try:legacy_raw=_unsign(token,"free-flow")
        except Exception:return None
        fh=hashlib.sha256(legacy_raw.encode()).hexdigest()
        flow=con.execute("SELECT * FROM free_flows WHERE flow_token_hash=?",(fh,)).fetchone()
        return flow if flow and flow["device_hash"]==dh else None

def _create_free_step(flow_id,step,now):
    raw=secrets.token_urlsafe(24);code=_new_verify_code();exp=now+timedelta(minutes=setting_int("free_step_ttl_minutes",12,2,60))
    destination=f"{_public_base()}/free/code?t={_signed(raw,'free-step')}"
    short=_shorten(destination)
    try:
        with db() as con:
            con.execute("""INSERT INTO free_steps(flow_id,step,token_hash,code_text,code_hash,short_url,created_at,expires_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (flow_id,step,hashlib.sha256(raw.encode()).hexdigest(),code,
                         hashlib.sha256(code.encode()).hexdigest(),short,now.isoformat(),exp.isoformat()))
    except sqlite3.IntegrityError:
        # Another request may have created the same step while Link4M was responding.
        with db() as con:
            st=con.execute("SELECT * FROM free_steps WHERE flow_id=? AND step=?",(flow_id,step)).fetchone()
            if st and st["short_url"]:return st["short_url"]
        raise
    return short

def _ensure_free_step(flow_id,step,now):
    with db() as con:
        st=con.execute("SELECT * FROM free_steps WHERE flow_id=? AND step=?",(flow_id,step)).fetchone()
        if st:
            try:alive=datetime.fromisoformat(st["expires_at"])>now
            except Exception:alive=False
            if st["short_url"] and alive and not st["verified_at"]:
                return st["short_url"]
            if st["verified_at"] and st["short_url"]:
                return st["short_url"]
            if not st["verified_at"]:
                con.execute("DELETE FROM free_steps WHERE id=?",(st["id"],))
    return _create_free_step(flow_id,step,now)

@app.get("/api/plans")
def public_plans():
    with db() as con:
        rows=con.execute("SELECT id,name,days,price_vnd,max_devices,duration_seconds,lifetime FROM plans WHERE enabled=1 ORDER BY sort_order,id").fetchall()
    return jsonify({"plans":[dict(r) for r in rows]})

@app.post("/api/free/start")
def free_start():
    if not LINK4M_API_TOKEN:return jsonify({"detail":"Chưa cấu hình LINK4M_API_TOKEN"}),503
    d=request.get_json(silent=True) or {};device=str(d.get("device_id","")).strip()
    if not device:return jsonify({"detail":"Không nhận diện được thiết bị"}),400
    dh=device_hash(device);ip=client_ip();log_event("free_start",dev_hash=dh)
    now=datetime.now(timezone.utc);day=_vn_day_start(now)
    flow=None;used=0
    with db() as con:
        used=con.execute("SELECT COUNT(*) c FROM free_flows WHERE device_hash=? AND completed_at>=?",(dh,day.isoformat())).fetchone()["c"]
        free_limit=setting_int("free_daily_limit",2,1,20)
        if used>=free_limit:return jsonify({"detail":f"ĐÃ HẾT {free_limit}/{free_limit} LƯỢT FREE HÔM NAY · QUAY LẠI NGÀY MAI HOẶC MUA KEY"}),429
        ip_used=con.execute("SELECT COUNT(*) c FROM free_flows WHERE request_ip=? AND completed_at>=?",(ip,day.isoformat())).fetchone()["c"]
        ip_limit=setting_int("free_ip_daily_limit",6,1,100)
        if ip not in ("unknown","127.0.0.1","::1") and ip_used>=ip_limit:return jsonify({"detail":"MẠNG NÀY ĐÃ CÓ QUÁ NHIỀU LƯỢT FREE HÔM NAY"}),429
        flow=con.execute("SELECT * FROM free_flows WHERE device_hash=? AND completed_at IS NULL AND expires_at>? ORDER BY id DESC LIMIT 1",(dh,now.isoformat())).fetchone()

    if flow:
        fid=flow["id"]
        step=int(flow["current_step"] or 1)
        # Recover gracefully if step 1 was accepted but the Link4M #2 request failed mid-way.
        if step==1 and flow["step1_verified_at"]:
            step=2
        try:short=_ensure_free_step(fid,step,now)
        except Exception as e:return jsonify({"detail":"Không tạo/khôi phục được Link4M: "+str(e)[:160]}),502
        if step!=int(flow["current_step"] or 1):
            with db() as con:con.execute("UPDATE free_flows SET current_step=? WHERE id=?",(step,fid))
        with db() as con:flow=con.execute("SELECT * FROM free_flows WHERE id=?",(fid,)).fetchone()
        return jsonify({"ok":True,"flow_token":_make_flow_token(fid,dh,flow["expires_at"]),"step":step,"url":short,"remaining":max(0,setting_int("free_daily_limit",2,1,20)-int(used)),"resumed":True})

    legacy_seed=secrets.token_urlsafe(24);flow_exp=now+timedelta(minutes=setting_int("free_flow_ttl_minutes",30,10,180))
    with db() as con:
        cur=con.execute("INSERT INTO free_flows(flow_token_hash,device_hash,request_ip,created_at,expires_at,current_step) VALUES(?,?,?,?,?,1)",
                        (hashlib.sha256(legacy_seed.encode()).hexdigest(),dh,ip,now.isoformat(),flow_exp.isoformat()))
        fid=cur.lastrowid
    try:short=_ensure_free_step(fid,1,now)
    except Exception as e:
        with db() as con:con.execute("DELETE FROM free_flows WHERE id=?",(fid,))
        return jsonify({"detail":"Không tạo được Link4M: "+str(e)[:160]}),502
    return jsonify({"ok":True,"flow_token":_make_flow_token(fid,dh,flow_exp.isoformat()),"step":1,"url":short,"remaining":max(0,setting_int("free_daily_limit",2,1,20)-int(used)),"resumed":False})

@app.get("/free/code")
def free_code():
    token=request.args.get("t","")
    try:raw=_unsign(token,"free-step")
    except Exception:return "Liên kết xác minh không hợp lệ.",400
    th=hashlib.sha256(raw.encode()).hexdigest();now=datetime.now(timezone.utc)
    with db() as con:
        st=con.execute("SELECT s.*,f.device_hash,f.completed_at FROM free_steps s JOIN free_flows f ON f.id=s.flow_id WHERE s.token_hash=?",(th,)).fetchone()
        if not st or st["completed_at"] or datetime.fromisoformat(st["expires_at"])<=now:return "Liên kết đã dùng hoặc hết hạn.",410
        if st["verified_at"]:return "Mã của bước này đã được xác minh.",410
        con.execute("UPDATE free_steps SET visited_at=COALESCE(visited_at,?),visited_ip=? WHERE id=?",(now.isoformat(),client_ip(),st["id"]))
        code=st["code_text"];step=st["step"]
    back=_public_base()+"/"
    page="""<!doctype html><html lang="vi"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>TAIXIUTOOL VERIFY</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;background:#02050a radial-gradient(circle at 50% 0,#102f45,transparent 45%);color:#fff;font-family:system-ui,-apple-system,sans-serif}.c{width:min(440px,100%);padding:26px 20px;border:2px solid #16ddff88;border-radius:26px;background:linear-gradient(150deg,#07131f,#02070c);box-shadow:0 24px 80px #000,0 0 38px #00dbff25;text-align:center}.logo{font-size:34px;font-weight:1000;color:#73edff;text-shadow:0 0 20px #00dfff55}.step{display:inline-block;margin:12px 0;padding:7px 12px;border:1px solid #7b5cff88;border-radius:99px;color:#bfafff;font-weight:900;font-size:12px}.ok{font-size:21px;font-weight:1000;color:#51ff9a;margin:9px 0}.sub{color:#99adbb;font-weight:700;font-size:12px}.code{margin:20px 0;padding:18px;border:2px solid #ff49b588;border-radius:15px;background:#03080e;color:#ffe8f8;font:1000 29px ui-monospace,monospace;letter-spacing:5px;text-shadow:0 0 15px #ff42ad55}.copy{width:100%;padding:14px;border:0;border-radius:13px;background:linear-gradient(90deg,#00e982,#00cfff);color:#00140d;font-weight:1000;font-size:14px}.back{display:block;margin-top:12px;padding:14px;border-radius:13px;text-decoration:none;background:#101828;border:1px solid #735cff88;color:#c9beff;font-weight:900}.note{margin-top:15px;color:#667f8e;font-size:10px;line-height:1.5}</style><div class="c"><div class="logo">TAIXIUTOOL</div><div class="step">BƯỚC __STEP__ / 2</div><div class="ok">✓ VƯỢT LINK THÀNH CÔNG</div><div class="sub">Sao chép mã này rồi quay lại TAIXIUTOOL để xác minh.</div><div id="code" class="code">__CODE__</div><button id="cp" class="copy">📋 SAO CHÉP MÃ</button><a class="back" href="__BACK__">← QUAY LẠI TAIXIUTOOL</a><div class="note">Mã chỉ dùng 1 lần · hết hạn sau 12 phút · không phải key đăng nhập</div></div><script>const b=document.getElementById('cp'),c=document.getElementById('code').textContent;async function cp(){try{await navigator.clipboard.writeText(c)}catch(e){const t=document.createElement('textarea');t.value=c;t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();document.execCommand('copy');t.remove()}b.textContent='✓ ĐÃ SAO CHÉP'}b.addEventListener('click',cp);</script></html>"""
    return page.replace("__STEP__",str(step)).replace("__CODE__",code).replace("__BACK__",back)

@app.post("/api/free/verify")
def free_verify():
    d=request.get_json(silent=True) or {};device=str(d.get("device_id","")).strip();token=str(d.get("flow_token","")).strip();code=str(d.get("code","")).strip().upper()
    if not device or not token or not code:return jsonify({"detail":"Thiếu thông tin xác minh"}),400
    now=datetime.now(timezone.utc);dh=device_hash(device)
    with db() as con:
        flow=_resolve_flow_token(con,token,dh,now)
        if not flow:return jsonify({"detail":"Phiên lấy key không hợp lệ hoặc đã hết hạn"}),400
        if flow["completed_at"]:return jsonify({"detail":"Phiên này đã hoàn tất"}),409
        if datetime.fromisoformat(flow["expires_at"])<=now:return jsonify({"detail":"Phiên đã hết hạn, hãy tạo lại"}),410
        step=int(flow["current_step"]);fid=flow["id"]
        st=con.execute("SELECT * FROM free_steps WHERE flow_id=? AND step=?",(fid,step)).fetchone()
        if not st or not st["visited_at"]:return jsonify({"detail":f"Hãy vượt Link4M bước {step} trước"}),400
        if st["verified_at"]:return jsonify({"detail":"Mã này đã dùng"}),409
        if datetime.fromisoformat(st["expires_at"])<=now:return jsonify({"detail":"Mã xác minh đã hết hạn · bấm LẤY KEY NHANH để tạo lại"}),410
        if not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(),st["code_hash"]):return jsonify({"detail":f"MÃ BƯỚC {step} KHÔNG ĐÚNG"}),400

    if step==1:
        # Create Link #2 first. If Link4M is temporarily down, code #1 remains reusable.
        try:short=_ensure_free_step(fid,2,now)
        except Exception as e:return jsonify({"detail":"Mã 1 đúng nhưng Link4M #2 đang lỗi, thử XÁC MINH lại: "+str(e)[:120]}),502
        with db() as con:
            con.execute("UPDATE free_steps SET verified_at=COALESCE(verified_at,?) WHERE id=?",(now.isoformat(),st["id"]))
            con.execute("UPDATE free_flows SET current_step=2,step1_verified_at=COALESCE(step1_verified_at,?) WHERE id=?",(now.isoformat(),fid))
            flow=con.execute("SELECT * FROM free_flows WHERE id=?",(fid,)).fetchone()
        log_event("free_step1_verified",dev_hash=dh)
        return jsonify({"ok":True,"completed":False,"step":2,"url":short,"flow_token":_make_flow_token(fid,dh,flow["expires_at"]),"message":"MÃ 1 ĐÚNG · ĐÃ MỞ BƯỚC 2"})

    free_hours=setting_int("free_key_hours",1,1,72);plain=("TAIXIU-FREE-"+secrets.token_hex(5)).upper();kexp=now+timedelta(hours=free_hours)
    with db() as con:
        # Re-check in the finishing transaction to make completion idempotent.
        flow=con.execute("SELECT * FROM free_flows WHERE id=?",(fid,)).fetchone()
        if flow["completed_at"]:
            return jsonify({"detail":"Phiên này đã hoàn tất"}),409
        con.execute("UPDATE free_steps SET verified_at=COALESCE(verified_at,?) WHERE id=?",(now.isoformat(),st["id"]))
        cur=con.execute("INSERT INTO keys(key_hash,label,created_at,expires_at,enabled,max_devices,days,price_vnd,plan_id) VALUES(?,?,?,?,1,1,0,0,NULL)",(key_hash(plain),f"link4m-free-{free_hours}h",now.isoformat(),kexp.isoformat()))
        kid=cur.lastrowid
        con.execute("UPDATE free_flows SET step2_verified_at=COALESCE(step2_verified_at,?),completed_at=?,key_id=?,current_step=3 WHERE id=?",(now.isoformat(),now.isoformat(),kid,fid))
    log_event("free_step2_verified",dev_hash=dh);log_event("free_completed",key_id=kid,dev_hash=dh)
    return jsonify({"ok":True,"completed":True,"step":3,"key":plain,"expires_at":kexp.isoformat(),"message":"XÁC MINH 2/2 THÀNH CÔNG"})

@app.get("/api/captcha")
def new_captcha():
    # One-time server-side CAPTCHA. The answer is never returned as JSON/text.
    alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code="".join(secrets.choice(alphabet) for _ in range(5))
    cid=secrets.token_urlsafe(16)
    now=datetime.now(timezone.utc); captcha_ttl=setting_int("captcha_ttl_seconds",300,60,1800); exp=now+timedelta(seconds=captcha_ttl)
    ah=hashlib.sha256((cid+"|"+code).encode()).hexdigest()
    with db() as con:
        con.execute("DELETE FROM captchas WHERE expires_at<? OR used=1",((now-timedelta(minutes=10)).isoformat(),))
        con.execute("INSERT INTO captchas(id,answer_hash,created_at,expires_at,used) VALUES(?,?,?,?,0)",(cid,ah,now.isoformat(),exp.isoformat()))
    rots=[-8,5,-4,7,-6]
    xs=[28,64,100,136,172]
    colors=["#63f7ff","#ff63bd","#80ff9c","#ffd568","#a995ff"]
    chars=[]
    for i,ch in enumerate(code):
        chars.append(f'<text x="{xs[i]}" y="47" fill="{colors[i]}" font-size="30" font-weight="900" font-family="monospace" transform="rotate({rots[i]} {xs[i]} 47)">{ch}</text>')
    svg=(
        '<svg xmlns="http://www.w3.org/2000/svg" width="205" height="64" viewBox="0 0 205 64">'
        '<rect width="205" height="64" rx="10" fill="#02070c"/>'
        '<path d="M5 18 C45 3 85 35 125 13 S175 35 201 20" stroke="#00eaff" stroke-opacity=".34" stroke-width="2" fill="none"/>'
        '<path d="M2 51 C38 31 70 63 108 41 S170 55 203 39" stroke="#ff3ca6" stroke-opacity=".28" stroke-width="2" fill="none"/>'
        '<circle cx="22" cy="35" r="2" fill="#fff" opacity=".25"/>'
        '<circle cx="88" cy="17" r="2" fill="#fff" opacity=".18"/>'
        '<circle cx="155" cy="50" r="2" fill="#fff" opacity=".22"/>'
        + ''.join(chars) + '</svg>'
    )
    data="data:image/svg+xml;base64,"+base64.b64encode(svg.encode()).decode()
    return jsonify({"ok":True,"captcha_id":cid,"image":data,"expires_in":captcha_ttl})

@app.post("/api/visit")
def web_visit():
    """Register a first web visit for this browser/device, max once per 24h.

    Used only for the always-on admin live feed; it does not grant access.
    """
    d=request.get_json(silent=True) or {}
    device=str(d.get("device_id") or "").strip()[:240]
    if not device:
        return jsonify({"ok":True,"logged":False})
    dh=device_hash(device)
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
    with db() as con:
        old=con.execute("SELECT id FROM analytics WHERE event='web_visit' AND device_hash=? AND created_at>=? ORDER BY id DESC LIMIT 1",(dh,cutoff)).fetchone()
    if old:
        return jsonify({"ok":True,"logged":False})
    log_event("web_visit",dev_hash=dh)
    return jsonify({"ok":True,"logged":True})

@app.post("/api/auth/activate")
def activate():
    d=request.get_json(silent=True) or {}
    key=str(d.get("key","")).strip()
    device=str(d.get("device_id","")).strip()
    captcha_id=str(d.get("captcha_id","")).strip()
    captcha_answer=str(d.get("captcha_answer","")).strip().upper()
    if not key or not device:return jsonify({"detail":"Thiếu key/device"}),400
    if not captcha_id or not captcha_answer:return jsonify({"detail":"Vui lòng nhập CAPTCHA"}),400
    now=datetime.now(timezone.utc)
    with db() as con:
        cap=con.execute("SELECT * FROM captchas WHERE id=?",(captcha_id,)).fetchone()
        if not cap or cap["used"] or datetime.fromisoformat(cap["expires_at"])<=now:
            return jsonify({"detail":"CAPTCHA đã hết hạn · hãy lấy mã mới"}),400
        con.execute("UPDATE captchas SET used=1 WHERE id=?",(captcha_id,))
        got=hashlib.sha256((captcha_id+"|"+captcha_answer).encode()).hexdigest()
        if not hmac.compare_digest(got,cap["answer_hash"]):
            return jsonify({"detail":"CAPTCHA không đúng"}),400
    kh=key_hash(key); dh=device_hash(device)
    with db() as con:
        row=con.execute("SELECT * FROM keys WHERE key_hash=?",(kh,)).fetchone()
        if not row or not row["enabled"]:
            log_event("activate_failed",dev_hash=dh); return jsonify({"detail":"Key không hợp lệ hoặc đã bị khóa"}),401
        if "owner_account_id" in row.keys() and row["owner_account_id"] is not None:
            return jsonify({"detail":"Key này thuộc tài khoản. Hãy đăng nhập đúng tài khoản để sử dụng."}),403
        exp=datetime.fromisoformat(row["expires_at"])
        if exp<=datetime.now(timezone.utc):return jsonify({"detail":"Key đã hết hạn"}),401
        exists=con.execute("SELECT 1 FROM devices WHERE key_id=? AND device_hash=?",(row["id"],dh)).fetchone()
        is_new_device=not bool(exists)
        if not exists:
            count=con.execute("SELECT COUNT(*) c FROM devices WHERE key_id=?",(row["id"],)).fetchone()["c"]
            if count>=row["max_devices"]:return jsonify({"detail":"Key đã đạt giới hạn thiết bị"}),403
            ip=client_ip(); ua=request.headers.get("User-Agent","")[:500]; loc=approximate_location(ip); os_name=detect_os(ua); browser=detect_browser(ua)
            con.execute("INSERT INTO devices(key_id,device_hash,first_seen,last_seen,ip_address,location,os_name,user_agent,browser_name) VALUES(?,?,?,?,?,?,?,?,?)",
              (row["id"],dh,now_iso(),now_iso(),ip,loc,os_name,ua,browser))
        else:
            ip=client_ip(); ua=request.headers.get("User-Agent","")[:500]; loc=approximate_location(ip); os_name=detect_os(ua); browser=detect_browser(ua)
            con.execute("UPDATE devices SET last_seen=?,ip_address=?,location=?,os_name=?,user_agent=?,browser_name=? WHERE key_id=? AND device_hash=?",
              (now_iso(),ip,loc,os_name,ua,browser,row["id"],dh))
    log_event("activate_success",key_id=row["id"],dev_hash=dh)
    if is_new_device:
        log_event("key_first_activation",key_id=row["id"],dev_hash=dh)
    token=sign_token({"kid":row["id"],"dev":dh,"exp":int(exp.timestamp())})
    _register_background_watch(row["id"],dh,row["expires_at"])
    with db() as con:
        dev=con.execute("SELECT first_seen,last_seen,os_name,browser_name FROM devices WHERE key_id=? AND device_hash=?",(row["id"],dh)).fetchone()
    os_name=(dev["os_name"] if dev else "") or "Thiết bị"
    browser_name=(dev["browser_name"] if dev else "") or "Trình duyệt"
    return jsonify({
        "ok":True,"token":token,"key_id":row["id"],"created_at":row["created_at"],
        "activated_at":dev["first_seen"] if dev else now.isoformat(),
        "expires_at":row["expires_at"],"os_name":os_name,"browser_name":browser_name,
        "device_id":dh[:12],"device_name":f"{os_name} · {browser_name}"
    })

@app.get("/api/auth/me")
@require_auth
def me():
    kid=request.auth_payload["kid"]; dh=request.auth_payload.get("dev","")
    with db() as con:
        row=con.execute("SELECT created_at,expires_at,label,days,max_devices FROM keys WHERE id=?",(kid,)).fetchone()
        dev=con.execute("SELECT first_seen,last_seen,os_name,browser_name FROM devices WHERE key_id=? AND device_hash=?",(kid,dh)).fetchone() if dh else None
    if not row:return jsonify({"detail":"Key không còn tồn tại"}),404
    os_name=(dev["os_name"] if dev else "") or "Thiết bị"
    browser_name=(dev["browser_name"] if dev else "") or "Trình duyệt"
    return jsonify({
        "ok":True,"key_id":kid,"created_at":row["created_at"],"activated_at":dev["first_seen"] if dev else None,
        "expires_at":row["expires_at"],"os_name":os_name,"browser_name":browser_name,
        "device_id":dh[:12] if dh else "","device_name":f"{os_name} · {browser_name}"
    })

@app.post("/api/device/location")
@require_auth
def device_location():
    d=request.get_json(silent=True) or {}
    try:
        lat=float(d.get("lat")); lon=float(d.get("lon"))
        accuracy=float(d.get("accuracy",0) or 0)
    except Exception:
        return jsonify({"detail":"Tọa độ không hợp lệ"}),400
    if not (-90<=lat<=90 and -180<=lon<=180):
        return jsonify({"detail":"Tọa độ ngoài phạm vi"}),400
    accuracy=max(0,min(100000,accuracy))
    kid=request.auth_payload["kid"]; dh=request.auth_payload["dev"]
    with db() as con:
        cur=con.execute("""UPDATE devices SET gps_lat=?,gps_lon=?,gps_accuracy=?,gps_updated_at=?,last_seen=?
                           WHERE key_id=? AND device_hash=?""",
                        (lat,lon,accuracy,now_iso(),now_iso(),kid,dh))
        if cur.rowcount==0:
            return jsonify({"detail":"Thiết bị chưa được đăng ký với key này"}),404
    log_event("location_shared",key_id=kid,dev_hash=dh)
    return jsonify({"ok":True})

@app.delete("/api/device/location")
@require_auth
def clear_device_location():
    kid=request.auth_payload["kid"]; dh=request.auth_payload["dev"]
    with db() as con:
        con.execute("""UPDATE devices SET gps_lat=NULL,gps_lon=NULL,gps_accuracy=NULL,gps_updated_at=NULL
                       WHERE key_id=? AND device_hash=?""",(kid,dh))
    log_event("location_revoked",key_id=kid,dev_hash=dh)
    return jsonify({"ok":True})

@app.post("/api/predict/<table>")
@require_auth
def predict(table):
    if table not in ('hu','md5','sunwin','max789_hu','max789_md5') and not _custom_table_exists(table,True):
        return jsonify({'detail':'Game/bàn không hợp lệ'}),400
    try:
        seq,actual_map,next_sid,side,conf,reason,diag=_prediction_payload(table)
        kid=request.auth_payload['kid']
        side,conf,reason=_store_for_key(kid,table,seq,actual_map,next_sid,side,conf,reason)
        game_name=('custom' if table.startswith('custom__') else ('sunwin' if table=='sunwin' else ('max789' if table.startswith('max789_') else 'lc79')))
        return jsonify({'ok':True,'table':table,'game':game_name,
                        'session_id':next_sid,'side':side,'confidence':conf,'reason':reason,
                        'pattern':diag['pattern'],'regime':diag['regime'],'noise':diag['noise'],
                        'break_score':diag['break_score'],'clarity':diag['clarity'],
                        'source_age_seconds':diag.get('source_age_seconds',0),
                        'source_delayed':diag.get('source_delayed',False)})
    except RuntimeError as e:
        return jsonify({'detail':str(e),'source_status':'delayed'}),502
    except Exception:
        return jsonify({'detail':'Nguồn dữ liệu đang đồng bộ lại','source_status':'retrying'}),503

@app.get("/api/source-status")
def source_status():
    out={}
    now=time.time()
    for table in _all_prediction_tables():
        st=_SOURCE_STATE.get(table) or {}
        age=max(0,int(now-float(st.get('changed') or now))) if st.get('sid') else None
        last_success=int(max(0,now-float(st.get('last_success')))) if st.get('last_success') else None
        configured=(bool(get_setting('lc79_hu_api_url',UPSTREAM_HU).strip()) if table=='hu' else
                    bool(get_setting('lc79_md5_api_url',UPSTREAM_MD5).strip()) if table=='md5' else
                    bool(get_setting('sunwin_api_url',SUNWIN_API).strip()) if table=='sunwin' else
                    bool(get_setting('max789_hu_api_url',MAX789_HU_API).strip()) if table=='max789_hu' else
                    bool(get_setting('max789_md5_api_url',MAX789_MD5_API).strip()) if table=='max789_md5' else
                    bool((_custom_api_url(table)[1] if table.startswith('custom__') else '')))
        out[table]={
          'configured':configured,'latest_sid':st.get('sid'),'age_seconds':age,'seen':bool(st.get('sid')),
          'last_success_ago_seconds':last_success,'error':_SOURCE_ERRORS.get(table) or '',
          'state':'off' if not configured else ('live' if st.get('sid') and (age is None or age<=SOURCE_STALE_SECONDS) else ('slow' if st.get('sid') else 'waiting'))
        }
    return jsonify({'ok':True,'stale_after':SOURCE_STALE_SECONDS,'hard_stale_after':SOURCE_HARD_STALE_SECONDS,'sources':out})

@app.get("/api/history")
@require_auth
def history():
    kid=request.auth_payload["kid"]
    limit=min(200,max(1,int(request.args.get("limit",120))))
    table=(request.args.get("table") or "").strip()
    if table and not _is_allowed_history_table(table):
        return jsonify({"detail":"Bàn không hợp lệ"}),400
    ttl_hours=max(1,min(168,setting_int("history_ttl_hours",24,1,168)))
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=ttl_hours)).isoformat()
    with db() as con:
        con.execute("DELETE FROM history WHERE created_at<?",(cutoff,))
        if table:
            rows=con.execute("""SELECT table_name,session_id,side,confidence,reason,actual,correct,created_at
              FROM history WHERE key_id=? AND table_name=? ORDER BY id DESC LIMIT ?""",(kid,table,limit)).fetchall()
        else:
            rows=con.execute("""SELECT table_name,session_id,side,confidence,reason,actual,correct,created_at
              FROM history WHERE key_id=? ORDER BY id DESC LIMIT ?""",(kid,limit)).fetchall()
    out=[]
    for r in rows:
        out.append({"table":r["table_name"],"sessionId":r["session_id"],"side":r["side"],
          "confidence":r["confidence"],"reason":r["reason"],"actual":r["actual"],
          "correct":None if r["correct"] is None else bool(r["correct"]),
          "time":r["created_at"][11:16] if r["created_at"] else ""})
    return jsonify({"history":out,"table":table or None,"ttl_hours":ttl_hours})

@app.get("/api/admin/settings")
@require_admin
def admin_settings():
    with db() as con:rows=con.execute("SELECT key,value,updated_at FROM settings ORDER BY key").fetchall()
    return jsonify({"settings":{r["key"]:r["value"] for r in rows}})

@app.patch("/api/admin/settings")
@require_admin
def admin_update_settings():
    d=request.get_json(silent=True) or {}
    specs={
      "admin_contact":("str",1,80),"free_key_hours":("int",1,72),"free_daily_limit":("int",1,20),
      "free_ip_daily_limit":("int",1,100),"captcha_ttl_seconds":("int",60,1800),
      "free_step_ttl_minutes":("int",2,60),"free_flow_ttl_minutes":("int",10,180),
      "lc79_poll_seconds":("int",2,60),"sunwin_poll_seconds":("int",2,60),"max789_poll_seconds":("int",2,60),
      "history_refresh_seconds":("int",10,120),"history_limit":("int",20,200),"history_ttl_hours":("int",1,168),
      "lc79_algo_mode":("int",1,3),"sunwin_algo_mode":("int",1,3),"max789_algo_mode":("int",1,3),"gps_prompt":("int",0,1),
      "lc79_game_url":("url",8,300),"lc79_hu_api_url":("url",8,500),"lc79_md5_api_url":("url",8,500),
      "sunwin_game_url":("url",8,300),"sunwin_api_url":("url",8,500),"sunwin_history_api_url":("url_optional",0,500),
      "max789_game_url":("url",8,300),"max789_hu_api_url":("url",8,500),"max789_md5_api_url":("url",8,500),
      "site_announcement":("str",0,600),"notice_enabled":("int",0,1),"notice_title":("str",0,80),"notice_body":("str",0,1200),
      "notice_telegram_url":("str",0,300),"notice_zalo_url":("str",0,300),"notice_support_phone":("str",0,40),"notice_remind_minutes":("int",5,1440),
      "bank_code":("str",0,30),"bank_account":("str",0,40),
      "bank_account_name":("str",0,100),"support_report_text":("str",0,120),
      "brand":("str",1,40),"tagline":("str",0,120),"start_button_text":("str",1,30),"login_title":("str",1,80),
      "ui_primary":("color",4,20),"ui_secondary":("color",4,20),"ui_accent":("color",4,20),"ui_surface":("color",4,20),
      "ui_font_scale":("int",85,115),"ui_compact":("int",0,1),"telegram_floating":("int",0,1),
      "maintenance_mode":("int",0,1),"maintenance_message":("str",0,240),
      "lc79_enabled":("int",0,1),"sunwin_enabled":("int",0,1),"max789_enabled":("int",0,1),
      "account_device_limit":("int",1,20),"account_ip_limit":("int",1,50),
      "deposit_min_vnd":("int",1000,100000000),"deposit_max_vnd":("int",1000,1000000000),"deposit_ttl_minutes":("int",3,60),
    }
    changed={}
    for k,v in d.items():
        if k not in specs:continue
        typ,lo,hi=specs[k]
        try:
            if typ=="int":
                v=max(lo,min(hi,int(v)))
            elif typ in ("url","url_optional"):
                v=str(v).strip()
                if typ=="url_optional" and not v:
                    pass
                elif not re.match(r"^https?://[^\s]+$",v,re.I):
                    return jsonify({"detail":f"{k} phải là URL http/https hợp lệ"}),400
                if len(v)>hi:return jsonify({"detail":f"{k} quá dài"}),400
            elif typ=="color":
                v=str(v).strip()
                if not re.fullmatch(r"#[0-9a-fA-F]{6}",v):
                    return jsonify({"detail":f"{k} phải là mã màu dạng #RRGGBB"}),400
            else:
                v=str(v).strip()[:hi]
                if len(v)<lo:continue
        except Exception:return jsonify({"detail":f"Giá trị {k} không hợp lệ"}),400
        set_setting(k,v);changed[k]=str(v)
    return jsonify({"ok":True,"changed":changed})

@app.post("/api/admin/keys/<int:key_id>/enable")
@require_admin
def admin_enable(key_id):
    with db() as con:con.execute("UPDATE keys SET enabled=1 WHERE id=?",(key_id,))
    return jsonify({"ok":True})

@app.post("/api/admin/plans/<int:plan_id>/enable")
@require_admin
def admin_enable_plan(plan_id):
    with db() as con:con.execute("UPDATE plans SET enabled=1 WHERE id=?",(plan_id,))
    return jsonify({"ok":True})

@app.get("/api/admin/events")
@require_admin
def admin_events():
    try:
        after=max(0,int(request.args.get("after_id","0")))
    except Exception:
        after=0
    try:
        limit=max(1,min(100,int(request.args.get("limit","40"))))
    except Exception:
        limit=40
    wanted=("web_visit","key_first_activation")
    qmarks=",".join("?" for _ in wanted)
    with db() as con:
        rows=con.execute(f"""SELECT id,event,key_id,device_hash,ip_address,os_name,user_agent,created_at
          FROM analytics WHERE id>? AND event IN ({qmarks}) ORDER BY id ASC LIMIT ?""",(after,*wanted,limit)).fetchall()
        latest=con.execute("SELECT COALESCE(MAX(id),0) AS m FROM analytics").fetchone()["m"]
        out=[]
        for r in rows:
            x=dict(r)
            if x.get("key_id"):
                k=con.execute("SELECT label,expires_at FROM keys WHERE id=?",(x["key_id"],)).fetchone()
                if k:
                    x["key_label"]=k["label"]
                    x["key_expires_at"]=k["expires_at"]
            out.append(x)
    return jsonify({"events":out,"latest_id":int(latest or 0)})

@app.get("/api/admin/stats")
@require_admin
def admin_stats():
    now=datetime.now(timezone.utc);day=_vn_day_start(now)
    with db() as con:
        total_keys=con.execute("SELECT COUNT(*) c FROM keys").fetchone()["c"]
        active=con.execute("SELECT COUNT(*) c FROM keys WHERE enabled=1 AND expires_at>?",(now.isoformat(),)).fetchone()["c"]
        devices=con.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        free_today=con.execute("SELECT COUNT(*) c FROM free_flows WHERE completed_at>=?",(day.isoformat(),)).fetchone()["c"]
        free_step1=con.execute("SELECT COUNT(*) c FROM free_flows WHERE step1_verified_at>=?",(day.isoformat(),)).fetchone()["c"]
        free_step2=con.execute("SELECT COUNT(*) c FROM free_flows WHERE step2_verified_at>=?",(day.isoformat(),)).fetchone()["c"]
        visits=con.execute("SELECT COUNT(*) c FROM analytics WHERE created_at>=?",(day.isoformat(),)).fetchone()["c"]
        activated=con.execute("SELECT COUNT(*) c FROM analytics WHERE event='activate_success' AND created_at>=?",(day.isoformat(),)).fetchone()["c"]
        background_active=con.execute("SELECT COUNT(*) c FROM background_watches WHERE active=1 AND expires_at>?",(now.isoformat(),)).fetchone()["c"]
        accounts_total=con.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
        deposit_pending=con.execute("SELECT COUNT(*) c FROM deposits WHERE status='sent' AND expires_at>?",(now.isoformat(),)).fetchone()["c"]
        wallet_total=con.execute("SELECT COALESCE(SUM(balance_vnd),0) c FROM accounts").fetchone()["c"]
        game_rows=con.execute("""SELECT table_name,COUNT(*) total,
          SUM(CASE WHEN actual IS NOT NULL THEN 1 ELSE 0 END) settled,
          SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) wins
          FROM history GROUP BY table_name""").fetchall()
        game_stats={}
        for g in game_rows:
            settled=int(g["settled"] or 0);wins=int(g["wins"] or 0)
            game_stats[g["table_name"]]={"total":int(g["total"] or 0),"settled":settled,"wins":wins,
                "rate":round(wins*100/settled,1) if settled else 0}
    return jsonify({"total_keys":total_keys,"active_keys":active,"devices":devices,"free_today":free_today,
      "free_step1":free_step1,"free_step2":free_step2,"events_today":visits,"activations_today":activated,
      "background_active":background_active,"accounts_total":accounts_total,"deposit_pending":deposit_pending,
      "wallet_total":wallet_total,"game_stats":game_stats})

@app.get("/api/admin/users")
@require_admin
def admin_users():
    with db() as con:
        rows=con.execute("""SELECT d.key_id,d.device_hash,d.first_seen,d.last_seen,d.ip_address,d.location,d.os_name,
          d.browser_name,d.gps_lat,d.gps_lon,d.gps_accuracy,d.gps_updated_at,k.label,k.expires_at
          FROM devices d JOIN keys k ON k.id=d.key_id ORDER BY d.last_seen DESC LIMIT 40""").fetchall()
    return jsonify({"users":[dict(r) | {"device_hash":r["device_hash"][:12]} for r in rows]})

@app.get("/api/admin/free")
@require_admin
def admin_free():
    with db() as con:
        rows=con.execute("""SELECT f.id,f.created_at,f.current_step,f.step1_verified_at,f.step2_verified_at,f.completed_at,
          f.request_ip,f.device_hash,f.key_id,
          (SELECT visited_ip FROM free_steps WHERE flow_id=f.id AND step=1) step1_ip,
          (SELECT visited_ip FROM free_steps WHERE flow_id=f.id AND step=2) step2_ip
          FROM free_flows f ORDER BY f.id DESC LIMIT 50""").fetchall()
    out=[]
    for r in rows:
        d=dict(r);d["device_hash"]=(d.get("device_hash") or "")[:12];out.append(d)
    return jsonify({"claims":out})

@app.get("/api/admin/plans")
@require_admin
def admin_plans():
    with db() as con:
        rows=con.execute("SELECT id,name,days,price_vnd,max_devices,enabled,sort_order,created_at FROM plans ORDER BY sort_order,id").fetchall()
    return jsonify({"plans":[dict(r) for r in rows]})

@app.post("/api/admin/plans")
@require_admin
def admin_add_plan():
    d=request.get_json(silent=True) or {}
    try:
        days=max(1,min(3650,int(d.get("days",1))))
        price=max(0,min(100000000,int(d.get("price_vnd",0))))
        max_devices=max(1,min(20,int(d.get("max_devices",1))))
        sort_order=int(d.get("sort_order",days))
    except Exception:
        return jsonify({"detail":"Thông số gói không hợp lệ"}),400
    name=str(d.get("name") or f"{days} NGÀY").strip()[:80]
    with db() as con:
        cur=con.execute("INSERT INTO plans(name,days,price_vnd,max_devices,enabled,sort_order,created_at) VALUES(?,?,?,?,1,?,?)",
                        (name,days,price,max_devices,sort_order,now_iso()))
        pid=cur.lastrowid
    return jsonify({"ok":True,"id":pid})

@app.patch("/api/admin/plans/<int:plan_id>")
@require_admin
def admin_edit_plan(plan_id):
    d=request.get_json(silent=True) or {}
    with db() as con:
        row=con.execute("SELECT * FROM plans WHERE id=?",(plan_id,)).fetchone()
        if not row:return jsonify({"detail":"Không tìm thấy gói"}),404
        try:
            name=str(d.get("name",row["name"])).strip()[:80]
            days=max(1,min(3650,int(d.get("days",row["days"]))))
            price=max(0,min(100000000,int(d.get("price_vnd",row["price_vnd"]))))
            max_devices=max(1,min(20,int(d.get("max_devices",row["max_devices"]))))
            enabled=1 if bool(d.get("enabled",bool(row["enabled"]))) else 0
            sort_order=int(d.get("sort_order",row["sort_order"]))
        except Exception:
            return jsonify({"detail":"Thông số gói không hợp lệ"}),400
        con.execute("""UPDATE plans SET name=?,days=?,price_vnd=?,max_devices=?,enabled=?,sort_order=? WHERE id=?""",
                    (name,days,price,max_devices,enabled,sort_order,plan_id))
    return jsonify({"ok":True})

@app.delete("/api/admin/plans/<int:plan_id>")
@require_admin
def admin_delete_plan(plan_id):
    with db() as con:
        con.execute("UPDATE plans SET enabled=0 WHERE id=?",(plan_id,))
    return jsonify({"ok":True})

@app.post("/api/admin/keys")
@require_admin
def admin_create_key():
    d=request.get_json(silent=True) or {}
    plan_id=d.get("plan_id")
    plan=None
    if plan_id is not None:
        try: plan_id=int(plan_id)
        except Exception:return jsonify({"detail":"plan_id không hợp lệ"}),400
        with db() as con: plan=con.execute("SELECT * FROM plans WHERE id=? AND enabled=1",(plan_id,)).fetchone()
        if not plan:return jsonify({"detail":"Không tìm thấy gói key"}),404
    try:
        days=max(1,min(3650,int(plan["days"] if plan else d.get("days",30))))
        price=max(0,min(100000000,int(plan["price_vnd"] if plan else d.get("price_vnd",0))))
        max_devices=max(1,min(20,int(plan["max_devices"] if plan else d.get("max_devices",MAX_DEVICES_DEFAULT))))
    except Exception:
        return jsonify({"detail":"Thông số key không hợp lệ"}),400
    plain=str(d.get("key") or ("TAIXIU-"+secrets.token_urlsafe(12))).upper()
    label=str(d.get("label") or (plan["name"] if plan else f"telegram-{days}d"))[:120]
    exp=datetime.now(timezone.utc)+timedelta(days=days)
    try:
        with db() as con:
            con.execute("""INSERT INTO keys(key_hash,label,created_at,expires_at,enabled,max_devices,days,price_vnd,plan_id)
                           VALUES(?,?,?,?,1,?,?,?,?)""",
              (key_hash(plain),label,now_iso(),exp.isoformat(),max_devices,days,price,plan_id))
    except sqlite3.IntegrityError:return jsonify({"detail":"Key đã tồn tại"}),409
    return jsonify({"ok":True,"key":plain,"expires_at":exp.isoformat(),"max_devices":max_devices,
                    "days":days,"price_vnd":price,"plan_id":plan_id,"label":label})

@app.patch("/api/admin/keys/<int:key_id>")
@require_admin
def admin_edit_key(key_id):
    d=request.get_json(silent=True) or {}
    with db() as con:
        row=con.execute("SELECT * FROM keys WHERE id=?",(key_id,)).fetchone()
        if not row:return jsonify({"detail":"Không tìm thấy key"}),404
        days=row["days"] or 1
        price=row["price_vnd"] or 0
        max_devices=row["max_devices"]
        enabled=row["enabled"]
        label=row["label"]
        try:
            if "days" in d: days=max(1,min(3650,int(d["days"])))
            if "price_vnd" in d: price=max(0,min(100000000,int(d["price_vnd"])))
            if "max_devices" in d: max_devices=max(1,min(20,int(d["max_devices"])))
            if "enabled" in d: enabled=1 if bool(d["enabled"]) else 0
            if "label" in d: label=str(d["label"])[:120]
        except Exception:
            return jsonify({"detail":"Thông số key không hợp lệ"}),400
        expires=row["expires_at"]
        if "days" in d:
            expires=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat()
        con.execute("""UPDATE keys SET label=?,days=?,price_vnd=?,max_devices=?,enabled=?,expires_at=? WHERE id=?""",
                    (label,days,price,max_devices,enabled,expires,key_id))
    return jsonify({"ok":True,"expires_at":expires,"days":days,"price_vnd":price,"max_devices":max_devices})

@app.post("/api/admin/keys/<int:key_id>/disable")
@require_admin
def admin_disable(key_id):
    with db() as con:
        con.execute("UPDATE keys SET enabled=0 WHERE id=?",(key_id,))
        con.execute("UPDATE background_watches SET active=0 WHERE key_id=?",(key_id,))
    return jsonify({"ok":True})

@app.get("/api/admin/keys")
@require_admin
def admin_list():
    with db() as con:
        rows=con.execute("""SELECT k.id,k.label,k.created_at,k.expires_at,k.enabled,k.max_devices,k.days,k.price_vnd,k.plan_id,
          COUNT(d.device_hash) AS devices FROM keys k LEFT JOIN devices d ON d.key_id=k.id
          GROUP BY k.id ORDER BY k.id DESC""").fetchall()
    return jsonify({"keys":[dict(r) for r in rows]})

@app.get("/api/admin/keys/<int:key_id>")
@require_admin
def admin_key_detail(key_id):
    with db() as con:
        k=con.execute("SELECT id,label,created_at,expires_at,enabled,max_devices,days,price_vnd,plan_id FROM keys WHERE id=?",(key_id,)).fetchone()
        if not k:return jsonify({"detail":"Không tìm thấy key"}),404
        ds=con.execute("""SELECT substr(device_hash,1,12) AS device_id,first_seen,last_seen,ip_address,location,os_name,
          browser_name,user_agent,gps_lat,gps_lon,gps_accuracy,gps_updated_at
          FROM devices WHERE key_id=? ORDER BY last_seen DESC""",(key_id,)).fetchall()
    return jsonify({"key":dict(k),"devices":[dict(x) for x in ds]})

@app.delete("/api/admin/keys/<int:key_id>/devices")
@require_admin
def admin_reset_devices(key_id):
    with db() as con: con.execute("DELETE FROM devices WHERE key_id=?",(key_id,))
    return jsonify({"ok":True})

if __name__=="__main__":
    init_db()
    init_account_db()
    start_background_predictor()
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
else:
    init_db()
    init_account_db()
    start_background_predictor()