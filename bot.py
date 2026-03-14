import os,json,logging,threading,schedule,time
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

# Conversation history per user (in-memory)
conversations={}

def load_cfg():
    path=D+"\\config.json"
    if not os.path.exists(path):
        cfg={"competitors":["Mediaocean","Operative","FreeWheel","Bionic Advertising Systems","Centro/Basis Technologies"]}
        save_cfg(cfg); return cfg
    with open(path) as f: return json.load(f)

def save_cfg(cfg):
    with open(D+"\\config.json","w") as f: json.dump(cfg,f,indent=2)

SYSTEM="""You are AW-Chris, a sharp competitive intelligence analyst for Guideline — a media planning and buying platform. You live in Slack.

Your personality: direct, smart, like a brilliant colleague who knows the ad-tech space deeply. No fluff. Conversational.

What you can do:
- Chat naturally about anything — strategy, competitors, market trends, prep for meetings
- Search the web for latest news (default: past 24 hours unless asked otherwise)
- Manage Tim's competitor watchlist — add or remove by understanding natural language like "keep an eye on MediaRadar" or "drop Operative from the list"
- Send daily 5am briefings automatically

Rules:
- ALWAYS use web search for any question about current news, company updates, or market info
- Remember conversation context — if Tim asks a follow-up, use prior messages
- When Tim asks to add/remove a competitor, do it and confirm naturally
- Be like a smart colleague texting back, not a formal report
- Keep responses tight — use bullets only when listing multiple things, otherwise just talk

Current context is injected each message."""

def chat(user_id, user_msg, cfg):
    competitors=cfg.get("competitors",[])
    if user_id not in conversations:
        conversations[user_id]=[]

    system=SYSTEM+f"\n\nTim's competitor watchlist: {', '.join(competitors) if competitors else 'empty — ask Tim what to track'}"
    system+=f"\nCurrent time: {datetime.now().strftime('%A %B %d, %Y %I:%M %p')}"

    conversations[user_id].append({"role":"user","content":user_msg})
    history=conversations[user_id][-20:]

    resp=ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        system=system,
        tools=[{"type":"web_search_20250305","name":"web_search"}],
        messages=history
    )
    reply="\n\n".join(b.text for b in resp.content if hasattr(b,"text"))
    conversations[user_id].append({"role":"assistant","content":reply})

    # Detect competitor list changes from the message
    msg_l=user_msg.lower()
    add_phrases=["add ","track ","start tracking","keep an eye on","watch ","monitor "]
    remove_phrases=["remove ","stop tracking","drop ","untrack ","forget "]

    for phrase in add_phrases:
        if phrase in msg_l and any(w in msg_l for w in ["competitor","company","them","list","watchlist",phrase.strip()]):
            raw=user_msg.lower().split(phrase)[-1].strip()
            name=raw.split(" to ")[0].split(" from")[0].split(" on")[0].strip().title()
            if name and len(name)>2 and name.lower() not in ["competitor","company","list","the list","my list"]:
                if name not in competitors:
                    competitors.append(name); cfg["competitors"]=competitors; save_cfg(cfg)
                    log.info(f"Added: {name}")
            break

    for phrase in remove_phrases:
        if phrase in msg_l:
            raw=user_msg.lower().split(phrase)[-1].strip()
            name=raw.split(" from")[0].split(" off")[0].strip().title()
            orig_len=len(competitors)
            cfg["competitors"]=[c for c in competitors if c.lower()!=name.lower()]
            if len(cfg["competitors"])<orig_len:
                save_cfg(cfg); log.info(f"Removed: {name}")
            break

    return reply

def post_daily_digest():
    cfg=load_cfg(); competitors=cfg.get("competitors",[])
    if not competitors: return
    log.info("Posting 5am digest...")
    resp=ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        system=SYSTEM+f"\n\nCompetitor watchlist: {', '.join(competitors)}\nTime: {datetime.now().strftime('%A %B %d, %Y')}",
        tools=[{"type":"web_search_20250305","name":"web_search"}],
        messages=[{"role":"user","content":
            f"Give Tim his morning competitor briefing. Search for news from the past 24 hours on each of these: {', '.join(competitors)}. "
            f"For each one that has actual news: what happened and why it matters for Guideline. "
            f"If nothing happened for a company, just skip them or say it was quiet. "
            f"Be direct and useful — Tim reads this over coffee."
        }]
    )
    intel="\n\n".join(b.text for b in resp.content if hasattr(b,"text"))
    msg=f"*Good morning Tim! Competitor Briefing — {datetime.now().strftime('%B %d, %Y')}*\n_Past 24 hours_\n\n{intel}\n\n_— AW-Chris_"
    try:
        app.client.chat_postMessage(channel="D0ALSF98T3K",text=msg,mrkdwn=True)
        log.info("5am digest sent!")
    except Exception as e: log.error(f"Digest error: {e}")

def run_scheduler():
    schedule.every().day.at("05:00").do(post_daily_digest)
    log.info("Scheduler: 5am daily digest active")
    while True: schedule.run_pending(); time.sleep(30)

@app.event("message")
def handle_dm(event,say):
    if event.get("channel_type")=="im" and not event.get("bot_id"):
        text=event.get("text","").strip()
        if not text: return
        user_id=event.get("user","default")
        log.info(f"DM: {text[:60]}")
        try:
            cfg=load_cfg()
            reply=chat(user_id,text,cfg)
            say(reply)
        except Exception as e:
            log.error(f"Error: {e}")
            say(f"Hit an error — {str(e)[:120]}")

@app.event("app_mention")
def handle_mention(event,say):
    text=event.get("text","")
    if "<@" in text: text=text.split(">",1)[-1].strip()
    if not text: return
    user_id=event.get("user","default")
    try:
        cfg=load_cfg()
        reply=chat(user_id,text,cfg)
        say(reply)
    except Exception as e:
        say(f"Error: {str(e)[:120]}")

if __name__=="__main__":
    threading.Thread(target=run_scheduler,daemon=True).start()
    log.info("AW-Chris (Opus) starting — conversational mode, 5am digest active")
    SocketModeHandler(app,os.environ["SLACK_APP_TOKEN"]).start()
