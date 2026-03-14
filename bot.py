import os,json,logging,threading,schedule,time,smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
load_dotenv(dotenv_path=r'C:\Users\tim.peters\competitor-monitor\.env')
from datetime import datetime
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic
logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)
D=r'C:\Users\tim.peters\competitor-monitor'
app=App(token=os.environ["SLACK_BOT_TOKEN"])
ai=anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def fetch(c, hours=720):
    days = hours // 24
    r=ai.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        tools=[{"type":"web_search_20250305","name":"web_search"}],
        messages=[{"role":"user","content":
            f"You are a competitive intelligence analyst for Guideline, a media planning & buying platform. "
            f"Search for news from the PAST {days} DAYS ONLY about: {', '.join(c)}. "
            f"Only include stories published in the last {days} days - ignore anything older. "
            f"For each company: top 2-3 recent developments and why it matters for Guideline. "
            f"Use *bold* and bullets. Max 150 words each. Today: {datetime.now().strftime('%B %d, %Y')}."
        }]
    )
    return "\n\n".join(b.text for b in r.content if hasattr(b,"text"))

def load_cfg():
    with open(D+"\\config.json") as f: return json.load(f)
def save_cfg(cfg):
    with open(D+"\\config.json","w") as f: json.dump(cfg,f,indent=2)

def send_email(subject, body):
    try:
        smtp_user = os.environ.get("SMTP_USER","")
        smtp_pass = os.environ.get("SMTP_PASS","")
        if not smtp_user or not smtp_pass:
            log.warning("No SMTP credentials - skipping email")
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = "tim.peters@guideline.ai"
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, "tim.peters@guideline.ai", msg.as_string())
        log.info("Email sent to tim.peters@guideline.ai")
    except Exception as e:
        log.error(f"Email failed: {e}")

def post_daily_digest():
    cfg=load_cfg()
    c=cfg.get("competitors",[])
    if not c: return
    log.info("Running 5am daily digest...")
    intel = fetch(c, hours=24)
    header = f"*🕵️ Daily Competitor Intel — {datetime.now().strftime('%B %d, %Y')}*\n_Past 24 hours | Tracking: {', '.join(c)}_\n{'─'*40}\n\n"
    footer = f"\n{'─'*40}\n_Powered by AW-Chris · Daily 5am digest_"
    full = header + intel + footer
    # Post to Slack
    try:
        app.client.chat_postMessage(channel="D0ALSF98T3K", text=full, mrkdwn=True)
        log.info("Daily digest posted to Slack")
    except Exception as e:
        log.error(f"Slack post failed: {e}")
    # Send email
    send_email(f"Daily Competitor Intel — {datetime.now().strftime('%B %d, %Y')}", full.replace("*","").replace("_",""))

def run_scheduler():
    schedule.every().day.at("05:00").do(post_daily_digest)
    log.info("Scheduler: daily digest at 5:00am")
    while True:
        schedule.run_pending()
        time.sleep(60)

HELP = ("Hi! I'm *AW-Chris*, your competitor intel bot (past 30 days only).\n\n"
        "`get intel` — all competitors, past 30 days\n"
        "`get intel on <company>` — one company, past 30 days\n"
        "`list competitors` — show watchlist\n"
        "`add competitor <n>` — add company\n"
        "`remove competitor <n>` — remove company\n"
        "`next digest` — when is next daily digest\n\n"
        "_Daily digest sent at 5am to Slack + tim.peters@guideline.ai_")

def respond(text, say, dm=False):
    t=text.lower().strip(); cfg=load_cfg(); c=cfg.get("competitors",[])
    if "list competitor" in t:
        say("Tracking:\n"+ "\n".join(f"• {x}" for x in c) if c else "None yet."); return
    if t.startswith("add competitor "):
        n=text[15:].strip()
        if n and n not in c: c.append(n); cfg["competitors"]=c; save_cfg(cfg); say(f"✅ Added *{n}*")
        return
    if t.startswith("remove competitor "):
        n=text[18:].strip(); cfg["competitors"]=[x for x in c if x.lower()!=n.lower()]; save_cfg(cfg); say(f"🗑️ Removed *{n}*"); return
    if "next digest" in t:
        say("📅 Next digest: *daily at 5:00am* → Slack + tim.peters@guideline.ai"); return
    if "get intel on " in t:
        target=text[t.index("get intel on ")+13:].strip()
        say(f"🔍 Researching *{target}* (past 30 days)...")
        say(fetch([target], hours=720)); return
    if "get intel" in t or "intel" in t or "news" in t or "competitor" in t:
        if not c: say("No competitors yet."); return
        say(f"🔍 Fetching past 30 days of intel on: {', '.join(c)}...")
        say(header := f"*Intel Report — {datetime.now().strftime('%B %d, %Y')}*\n_Past 30 days_\n\n")
        say(fetch(c, hours=720)); return
    if dm: say(HELP)

@app.event("message")
def handle_dm(event, say):
    if event.get("channel_type")=="im" and not event.get("bot_id"):
        respond(event.get("text",""), say, dm=True)

@app.event("app_mention")
def handle_mention(event, say):
    text=event.get("text","")
    if "<@" in text: text=text.split(">",1)[-1].strip()
    respond(text, say)

if __name__=="__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info("AW-Chris starting! Daily digest at 5am.")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
