import os,sys,subprocess,signal,time

children=[]
def stop(*_):
    for p in children:
        try:p.terminate()
        except Exception:pass

signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
port=os.getenv("PORT","8080")
env=os.environ.copy()
env.setdefault("BACKEND_URL",f"http://127.0.0.1:{port}")
if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_ADMIN_ID") and env.get("ADMIN_SECRET"):
    children.append(subprocess.Popen([sys.executable,"admin_bot.py"],env=env))
else:
    print("[start_all] Telegram admin bot skipped: missing TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_ID / ADMIN_SECRET",flush=True)
cmd=["gunicorn","server:app","--bind",f"0.0.0.0:{port}","--workers","1","--threads","4","--timeout","120","--access-logfile","-","--error-logfile","-"]
web=subprocess.Popen(cmd,env=env);children.append(web)
code=web.wait();stop();sys.exit(code)
