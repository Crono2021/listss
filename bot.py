
import json
import os
import re
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

DATA_FILE = "/data/data.json"
MAX_LINES = 100
INDEX_URL = "https://t.me/cinehdcastellano2/2/2840"

LINE_REGEX = re.compile(
    r'^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*\((?P<url>https?://pixeldrain\.net/u/[^\s()]+)\)\s*$'
)

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"topics": {}, "entries": {}, "messages": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"topics": {}, "entries": {}, "messages": {}}

def save_data(data):
    os.makedirs("/data", exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def split_blocks(entries):
    return [entries[i:i+MAX_LINES] for i in range(0, len(entries), MAX_LINES)]

def fmt_block(block):
    return "\n".join([f'<a href="{e["url"]}">{e["title"]}</a>' for e in block])

async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /settopic A")
        return
    letra = context.args[0].upper()
    tid = update.message.message_thread_id
    if tid is None:
        await update.message.reply_text("Debes usar esto dentro del tema.")
        return
    data = load_data()
    data["topics"][letra] = tid
    save_data(data)
    await update.message.reply_text(f"Tema {letra} registrado.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /add TÍTULO URL")
        return
    url = context.args[-1]
    title = " ".join(context.args[:-1]).strip()
    letra = title[0].upper()
    if not ("A" <= letra <= "Z"):
        letra = "#"

    data = load_data()
    data["entries"].setdefault(letra, [])
    data["messages"].setdefault(letra, [])

    for e in data["entries"][letra]:
        if e["title"].lower() == title.lower():
            await update.message.reply_text("Ya existe.")
            return

    data["entries"][letra].append({"title": title, "url": url})
    data["entries"][letra].sort(key=lambda x: x["title"].lower())
    save_data(data)

    await rebuild_topic(update, context, letra)
    await update.message.reply_text("Añadido correctamente.")

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /delete TÍTULO (AÑO)")
        return

    full = " ".join(context.args).strip().lower()

    data = load_data()

    found = False
    found_letra = None

    for letra, lista in data["entries"].items():
        for e in lista:
            if e["title"].lower() == full:
                lista.remove(e)
                found = True
                found_letra = letra
                break
        if found:
            break

    if not found:
        await update.message.reply_text("No encontrado.")
        return

    data["entries"][found_letra].sort(key=lambda x: x["title"].lower())
    save_data(data)

    await update.message.reply_text(f"Eliminado de {found_letra}. Reconstruyendo…")
    await rebuild_topic(update, context, found_letra)

async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or len(context.args) != 1:
        await update.message.reply_text("Uso: /rebuild A")
        return
    letra = context.args[0].upper()
    await rebuild_topic(update, context, letra)

async def rebuild_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, letra: str):
    data = load_data()
    if letra not in data["topics"]:
        await update.message.reply_text("Tema no registrado.")
        return

    tid = data["topics"][letra]
    entries = data["entries"].get(letra, [])
    blocks = split_blocks(entries)
    chat_id = update.effective_chat.id

    for msg_id in data["messages"].get(letra, []):
        try: await context.bot.delete_message(chat_id, msg_id)
        except: pass

    data["messages"][letra] = []

    for blk in blocks:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=tid,
            text=fmt_block(blk),
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        data["messages"][letra].append(msg.message_id)

    btn = f'<a href="{INDEX_URL}">Volver al índice</a>'
    msg = await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=tid,
        text=btn,
        parse_mode=constants.ParseMode.HTML,
        disable_web_page_preview=True,
    )
    data["messages"][letra].append(msg.message_id)

    save_data(data)

async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or len(context.args) != 1:
        await update.message.reply_text("Uso: /importar A")
        return
    letra = context.args[0].upper()
    context.user_data["import"] = letra
    context.user_data["buf"] = []
    await update.message.reply_text("Modo importación. Pega todo y luego /finalizar.")

async def recv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import" not in context.user_data:
        return
    if update.message.text:
        context.user_data["buf"].append(update.message.text)

async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import" not in context.user_data:
        await update.message.reply_text("No estás importando.")
        return

    letra = context.user_data["import"]
    buffer = context.user_data["buf"]

    data = load_data()
    data["entries"].setdefault(letra, [])

    lines = []
    for msg in buffer:
        for l in msg.splitlines():
            l = l.strip()
            if l:
                lines.append(l)

    total = 0
    for line in lines:
        m = LINE_REGEX.match(line)
        if m:
            title = f'{m.group("title").strip()} ({m.group("year")})'
            url = m.group("url").strip()
            data["entries"][letra].append({"title": title, "url": url})
            total += 1

    ded = {}
    for e in data["entries"][letra]:
        key = (e["title"].lower(), e["url"])
        ded[key] = e
    data["entries"][letra] = sorted(ded.values(), key=lambda x: x["title"].lower())
    save_data(data)

    context.user_data.clear()
    await update.message.reply_text(f"Importados {total}. Reconstruyendo…")
    await rebuild_topic(update, context, letra)

def main():
    token = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recv_import))

    app.run_polling()

if __name__ == "__main__":
    main()
