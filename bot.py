
import json
import os
import re
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

DATA_FILE = os.environ.get("DATA_FILE", "/data/data.json")
MAX_LINES = 100

YEAR_REGEX = re.compile(r"\((\d{4})\)")
URL_REGEX = re.compile(r"https://pixeldrain\.net/u/[A-Za-z0-9]+")

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"topics": {}, "entries": {}, "messages": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def split_into_blocks(entries):
    return [entries[i:i+MAX_LINES] for i in range(0, len(entries), MAX_LINES)]

def format_block(block):
    return "\n".join([f'<a href="{e["url"]}">{e["title"]}</a>' for e in block])

async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /settopic A")
        return
    letra = context.args[0].upper()
    topic_id = update.message.message_thread_id
    data = load_data()
    data["topics"][letra] = topic_id
    save_data(data)
    await update.message.reply_text(f"Tema asociado a la letra {letra} correctamente.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /add <TÍTULO> <URL>")
        return
    titulo = " ".join(context.args[:-1])
    url = context.args[-1]

    first = titulo.strip()[0].upper()
    letra = first if "A" <= first <= "Z" else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])
    data["messages"].setdefault(letra, [])

    for e in data["entries"][letra]:
        if e["title"].lower() == titulo.lower():
            await update.message.reply_text("⚠️ Ya existe esa película.")
            return

    data["entries"][letra].append({"title": titulo, "url": url})
    data["entries"][letra] = sorted(data["entries"][letra], key=lambda x: x["title"].lower())
    save_data(data)

    await rebuild_topic(update, context, letra)
    await update.message.reply_text(f"Añadido en la letra {letra}.")

async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /rebuild A")
        return
    await rebuild_topic(update, context, context.args[0].upper())

async def rebuild_topic(update, context, letra):
    data = load_data()
    if letra not in data["topics"]:
        await update.message.reply_text("No tengo ese topic. Usa /settopic.")
        return

    topic_id = data["topics"][letra]
    entries = data["entries"].get(letra, [])
    blocks = split_into_blocks(entries)

    # Borrar mensajes anteriores del bot
    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(update.effective_chat.id, msg_id)
        except:
            pass

    data["messages"][letra] = []

    for block in blocks:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=topic_id,
            text=format_block(block),
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=True
        )
        data["messages"][letra].append(msg.message_id)

    save_data(data)

async def export_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /export A")
        return
    letra = context.args[0].upper()
    data = load_data()
    if letra not in data["entries"]:
        await update.message.reply_text("Esa letra no tiene datos.")
        return
    texto = "\n".join([f'{e["title"]} - {e["url"]}' for e in data["entries"][letra]])
    await update.message.reply_text(texto)

# ---------------- UNIVERSAL IMPORTER ----------------

async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /importar A")
        return
    letra = context.args[0].upper()
    context.user_data["import_letter"] = letra
    context.user_data["import_buffer"] = []
    await update.message.reply_text(f"Modo importación para {letra}. Ahora reenvíame o pégame los bloques. Luego usa /finalizar.")

async def recoger_reenviado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        return
    if not update.message or not update.message.text:
        return
    context.user_data["import_buffer"].append(update.message.text)

async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        await update.message.reply_text("No estabas importando nada.")
        return

    letra = context.user_data["import_letter"]
    textos = context.user_data["import_buffer"]

    data = load_data()
    data["entries"].setdefault(letra, [])

    total = 0

    lines = []
    for msg in textos:
        for l in msg.split("\n"):
            lines.append(l.strip())

    pending_title = None

    for line in lines:
        url_match = URL_REGEX.search(line)

        if url_match:
            url = url_match.group()
            if pending_title:
                data["entries"][letra].append({"title": pending_title, "url": url})
                total += 1
                pending_title = None
            continue

        year_match = YEAR_REGEX.search(line)
        if year_match:
            pending_title = line.strip()

    data["entries"][letra] = sorted(
        { (e["title"], e["url"]) for e in data["entries"][letra] },
        key=lambda x: x[0].lower()
    )
    data["entries"][letra] = [{"title": t, "url": u} for t, u in data["entries"][letra]]
    save_data(data)

    context.user_data.clear()

    await update.message.reply_text(f"Importación completada. {total} entradas añadidas. Reconstruyendo…")
    await rebuild_topic(update, context, letra)

def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("export", export_list))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))
    app.add_handler(MessageHandler(filters.ALL & filters.FORWARDED, recoger_reenviado))

    app.run_polling()

if __name__ == "__main__":
    main()
