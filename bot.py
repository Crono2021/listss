
import json
import os
import re
import unicodedata
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Archivo de datos (usa un Volume montado en /data en Railway)
DATA_FILE = "/data/data.json"
MAX_LINES = 100

# Enlace del botón final
INDEX_URL = "https://t.me/cinehdcastellano2/2/2840"

# Detecta cualquier enlace válido de pixeldrain (archivos o listas)
PIXEL_URL_RE = re.compile(
    r"https?://pixeldrain\.net/(?:u|l)/[^\s)]+",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    """
    Normaliza una cadena para orden alfabético “humano”:
    - Elimina acentos (Á -> A, É -> E, etc.)
    - Pasa a minúsculas
    """
    nf = unicodedata.normalize("NFD", s)
    sin_acentos = "".join(c for c in nf if unicodedata.category(c) != "Mn")
    return sin_acentos.lower()


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


def split_blocks(entries):
    return [entries[i:i + MAX_LINES] for i in range(0, len(entries), MAX_LINES)]


def fmt_block(block):
    """
    Devuelve el texto del bloque:
    Cada línea es el título completo en azul y clicable,
    con el enlace de pixeldrain oculto.
    """
    return "\n".join(f'<a href="{e["url"]}">{e["title"]}</a>' for e in block)


async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if len(context.args) != 1:
        await message.reply_text("Uso: /settopic A")
        return

    letra = context.args[0].upper()
    topic_id = message.message_thread_id
    if topic_id is None:
        await message.reply_text("Este comando debe usarse DENTRO del tema de esa letra.")
        return

    data = load_data()
    data["topics"][letra] = topic_id
    save_data(data)
    await message.reply_text(f"Tema asociado a la letra {letra} correctamente.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if len(context.args) < 2:
        await message.reply_text("Uso: /add TÍTULO URL")
        return

    url = context.args[-1]
    title = " ".join(context.args[:-1]).strip()
    if not title:
        await message.reply_text("El título no puede estar vacío.")
        return

    first = title[0].upper()
    letra = first if "A" <= first <= "Z" else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])
    data["messages"].setdefault(letra, [])

    # Evitar duplicados por título (ignorando mayúsculas/acentos)
    normalized_new = normalize(title)
    for e in data["entries"][letra]:
        if normalize(e["title"]) == normalized_new:
            await message.reply_text("⚠️ Esa película ya existe en esa letra.")
            return

    data["entries"][letra].append({"title": title, "url": url})
    data["entries"][letra].sort(key=lambda x: normalize(x["title"]))
    save_data(data)

    await rebuild_topic(update, context, letra)
    await message.reply_text(f"Añadido en la letra {letra}.")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if len(context.args) < 2:
        await message.reply_text("Uso: /delete TÍTULO (AÑO)")
        return

    full_title = " ".join(context.args).strip().lower()

    data = load_data()
    found = False
    letra_encontrada = None

    for letra, lista in data["entries"].items():
        for e in list(lista):
            if e["title"].strip().lower() == full_title:
                lista.remove(e)
                found = True
                letra_encontrada = letra
                break
        if found:
            break

    if not found:
        await message.reply_text("❌ No he encontrado esa película en ninguna letra.")
        return

    data["entries"][letra_encontrada].sort(key=lambda x: normalize(x["title"]))
    save_data(data)

    await message.reply_text(f"✔ Película eliminada de la letra {letra_encontrada}. Reconstruyendo…")
    await rebuild_topic(update, context, letra_encontrada)


async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or len(context.args) != 1:
        if message:
            await message.reply_text("Uso: /rebuild A")
        return
    letra = context.args[0].upper()
    await rebuild_topic(update, context, letra)


async def rebuild_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, letra: str):
    data = load_data()
    if letra not in data["topics"]:
        if update.message:
            await update.message.reply_text(
                f"No tengo registrado el tema de la letra {letra}. "
                f"Ve a ese tema y usa /settopic {letra}."
            )
        return

    topic_id = data["topics"][letra]
    entries = data["entries"].get(letra, [])
    blocks = split_blocks(entries)

    chat_id = update.effective_chat.id

    # Borrar mensajes antiguos del bot (lista + botón)
    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    data["messages"][letra] = []

    # Publicar bloques de la letra
    for block in blocks:
        if not block:
            continue
        text = fmt_block(block)
        msg = await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=topic_id,
            text=text,
            parse_mode=constants.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        data["messages"][letra].append(msg.message_id)

    # Botón final "Volver al índice"
    btn_text = f'<a href="{INDEX_URL}">Volver al índice</a>'
    msg = await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=topic_id,
        text=btn_text,
        parse_mode=constants.ParseMode.HTML,
        disable_web_page_preview=True,
    )
    data["messages"][letra].append(msg.message_id)

    save_data(data)


async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or len(context.args) != 1:
        if message:
            await message.reply_text("Uso: /importar A")
        return
    letra = context.args[0].upper()
    context.user_data["import_letter"] = letra
    context.user_data["import_buffer"] = []
    await message.reply_text(
        f"Modo importación para la letra {letra}.\n\n"
        "Copia TODO el listado de esa letra (cada peli o colección en UNA línea, "
        "con el enlace de pixeldrain al final) y pégalo aquí (puede ser en varios mensajes).\n"
        "Cuando termines, usa /finalizar."
    )


async def recv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Recoge texto mientras estamos en modo importar
    if "import_letter" not in context.user_data:
        return
    if not update.message or not update.message.text:
        return
    context.user_data["import_buffer"].append(update.message.text)


def parse_line(line: str):
    """
    Línea de ejemplo:
      - 'X (2022) (https://pixeldrain.net/u/abc123)'
      - 'Batman - El Caballero Oscuro (TRILOGÍA COMPLETA) (https://pixeldrain.net/l/1o2QU1w4)'
      - 'Colección Pixar (https://pixeldrain.net/l/xxxxxx)'

    Estrategia:
      1. Buscar la primera URL de pixeldrain.
      2. El título es TODO lo que hay antes de la URL (limpiando el paréntesis que abra).
    """
    m = PIXEL_URL_RE.search(line)
    if not m:
        return None

    url = m.group(0).strip()
    title_part = line[: m.start()].rstrip()

    # Si acaba en '(' por cosas del formato: 'Título (...) ( URL'
    if title_part.endswith("("):
        title_part = title_part[:-1].rstrip()

    if not title_part:
        return None

    title = title_part
    return {"title": title, "url": url}


async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if "import_letter" not in context.user_data:
        if message:
            await message.reply_text("No estás importando nada. Usa /importar A primero.")
        return

    letra = context.user_data["import_letter"]
    buffer = context.user_data.get("import_buffer", [])

    data = load_data()
    data["entries"].setdefault(letra, [])

    total = 0
    for msg in buffer:
        for raw_line in msg.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parsed = parse_line(line)
            if not parsed:
                continue
            data["entries"][letra].append(parsed)
            total += 1

    # Eliminar duplicados y ordenar con soporte de acentos
    dedup = {}
    for e in data["entries"][letra]:
        key = (normalize(e["title"]), e["url"])
        dedup[key] = e
    data["entries"][letra] = sorted(dedup.values(), key=lambda x: normalize(x["title"]))
    save_data(data)

    context.user_data.clear()

    if message:
        await message.reply_text(
            f"Importación completada para la letra {letra}. {total} entradas añadidas. "
            "Reconstruyendo…"
        )
    await rebuild_topic(update, context, letra)


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta la variable de entorno BOT_TOKEN.")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))

    # Mientras estamos en importación, cualquier texto se añade al buffer
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recv_import))

    app.run_polling()


if __name__ == "__main__":
    main()
