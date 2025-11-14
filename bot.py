
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

DATA_FILE = os.environ.get("DATA_FILE", "/data/data.json")
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
    except Exception:
        return {"topics": {}, "entries": {}, "messages": {}}

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def split_into_blocks(entries):
    return [entries[i:i+MAX_LINES] for i in range(0, len(entries), MAX_LINES)]

def format_block(block):
    return "\n".join([f'<a href="{e["url"]}">{e["title"]}</a>' for e in block])

async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /settopic A")
        return
    letra = context.args[0].upper()
    topic_id = update.message.message_thread_id
    if topic_id is None:
        await update.message.reply_text("Este comando debe usarse dentro del TEMA de la letra.")
        return
    data = load_data()
    data["topics"][letra] = topic_id
    save_data(data)
    await update.message.reply_text(f"Tema asociado a la letra {letra} correctamente.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /add <TÍTULO> <URL>")
        return
    url = context.args[-1]
    titulo = " ".join(context.args[:-1]).strip()
    if not titulo:
        await update.message.reply_text("El título no puede estar vacío.")
        return
    first = titulo[0].upper()
    letra = first if "A" <= first <= "Z" else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])
    data["messages"].setdefault(letra, [])

    for e in data["entries"][letra]:
        if e["title"].strip().lower() == titulo.lower():
            await update.message.reply_text("⚠️ Esta película ya existe en esa letra. No se añadió.")
            return

    data["entries"][letra].append({"title": titulo, "url": url})
    data["entries"][letra] = sorted(data["entries"][letra], key=lambda x: x["title"].lower())
    save_data(data)

    await rebuild_topic(update, context, letra)
    await update.message.reply_text(f"Añadido en la letra {letra} correctamente.")

async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /rebuild A")
        return
    letra = context.args[0].upper()
    await rebuild_topic(update, context, letra)

async def rebuild_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, letra: str):
    data = load_data()
    if letra not in data["topics"]:
        if update and update.message:
            await update.message.reply_text(
                f"No tengo registrado el topic de la letra {letra}. Ve al tema y usa /settopic."
            )
        return

    topic_id = data["topics"][letra]
    entries = data["entries"].get(letra, [])
    blocks = split_into_blocks(entries)

    chat_id = update.effective_chat.id if update and update.effective_chat else None
    if chat_id is None:
        return

    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass

    data["messages"][letra] = []

    for block in blocks:
        text = format_block(block)
        msg = await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=topic_id,
            text=text,
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        data["messages"][letra].append(msg.message_id)

    btn = f'<a href="{INDEX_URL}">Volver al índice</a>'
    msg = await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=topic_id,
        text=btn,
        parse_mode=constants.ParseMode.HTML,
        disable_web_page_preview=True,
    )
    data["messages"][letra].append(msg.message_id)

    save_data(data)

async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /importar A")
        return
    letra = context.args[0].upper()
    context.user_data["import_letter"] = letra
    context.user_data["import_buffer"] = []
    await update.message.reply_text(
        f"Modo importación para {letra}. Pega el listado y luego usa /finalizar."
    )

async def recoger_texto_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        return
    if not update.message.text:
        return
    context.user_data["import_buffer"].append(update.message.text)

async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        await update.message.reply_text("No estás importando. Usa /importar A.")
        return

    letra = context.user_data["import_letter"]
    buffer = context.user_data["import_buffer"]

    data = load_data()
    data["entries"].setdefault(letra, [])

    total = 0
    lines = []
    for msg in buffer:
        for l in msg.splitlines():
            l = l.strip()
            if l:
                lines.append(l)

    for line in lines:
        m = LINE_REGEX.match(line)
        if not m:
            continue
        title = m.group("title").strip()
        year = m.group("year")
        url = m.group("url").strip()
        full_title = f"{title} ({year})"
        data["entries"][letra].append({"title": full_title, "url": url})
        total += 1

    dedup = {}
    for e in data["entries"][letra]:
        key = (e["title"].lower(), e["url"])
        dedup[key] = e
    data["entries"][letra] = sorted(dedup.values(), key=lambda x: x["title"].lower())

    save_data(data)
    context.user_data.clear()

    await update.message.reply_text(f"Importados {total} elementos. Reconstruyendo…")
    await rebuild_topic(update, context, letra)

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta BOT_TOKEN.")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), recoger_texto_import))

    app.run_polling()

if __name__ == "__main__":
    main()
