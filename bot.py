import json
import os
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

DATA_FILE = os.environ.get("DATA_FILE", "/data/data.json")
MAX_LINES = 100

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
    lines = []
    for item in block:
        t = item["title"]
        u = item["url"]
        line = f'<a href="{u}">{t}</a>'
        lines.append(line)
    return "\n".join(lines)

async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /settopic A")
        return
    letra = context.args[0].upper()
    topic_id = update.message.message_thread_id
    data["topics"][letra] = topic_id
    save_data(data)
    await update.message.reply_text(f"Tema asociado a la letra {letra} correctamente.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /add <TÍTULO> <URL>")
        return

    url = context.args[-1]
    titulo = " ".join(context.args[:-1])
    first = titulo.strip()[0].upper()
    letra = first if ("A" <= first <= "Z") else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])
    data["messages"].setdefault(letra, [])

    for e in data["entries"][letra]:
        if e["title"].strip().lower() == titulo.strip().lower():
            await update.message.reply_text("⚠️ Esta película ya existe. No se añadió.")
            return

    data["entries"][letra].append({"title": titulo, "url": url})
    data["entries"][letra] = sorted(data["entries"][letra], key=lambda x: x["title"].lower())
    save_data(data)

    await rebuild_topic(update, context, letra_override=letra)
    await update.message.reply_text(f"Añadido en la letra {letra} correctamente.")

async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /rebuild A")
        return
    letra = context.args[0].upper()
    await rebuild_topic(update, context, letra_override=letra)

async def rebuild_topic(update, context, letra_override=None):
    data = load_data()
    letra = letra_override
    if letra not in data["topics"]:
        await update.message.reply_text(f"No tengo registrado el topic de la letra {letra}. Usa /settopic {letra} en ese tema.")
        return

    topic_id = data["topics"][letra]
    entries = data["entries"].get(letra, [])
    bloques = split_into_blocks(entries)

    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(update.effective_chat.id, msg_id)
        except:
            pass

    data["messages"][letra] = []

    for block in bloques:
        txt = format_block(block)
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=txt,
            message_thread_id=topic_id,
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
        await update.message.reply_text("No tengo datos de esa letra.")
        return

    texto = "\n".join([f'{e["title"]} - {e["url"]}' for e in data["entries"][letra]])
    await update.message.reply_text(f"Listado {letra}:\n\n{texto}")

async def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("export", export_list))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
