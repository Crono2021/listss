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

# ---------------- CONFIGURACIÓN ----------------

DATA_FILE = "/data/data.json"  # Volume montado en Railway
MAX_LINES = 100

INDEX_URL = "https://t.me/cinehdcastellano2/2/2840"

# SOLO ESTE USUARIO PUEDE USAR LOS COMANDOS (TU ID)
OWNER_ID = 5540195020

# Detectar URLs de pixeldrain (archivos y listas)
PIXEL_URL_RE = re.compile(
    r"https?://pixeldrain\.net/(?:u|l)/[^\s)]+",
    re.IGNORECASE,
)


# ---------------- UTILIDADES ----------------

def normalize(s: str) -> str:
    """Normaliza texto para orden alfabético (quita acentos y pasa a minúsculas)."""
    nf = unicodedata.normalize("NFD", s)
    sin_acentos = "".join(c for c in nf if unicodedata.category(c) != "Mn")
    return sin_acentos.lower()


def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"topics": {}, "entries": {}, "messages": {}, "owner_group_id": None}
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"topics": {}, "entries": {}, "messages": {}, "owner_group_id": None}
    # Asegurar clave nueva para compatibilidad
    if "owner_group_id" not in data:
        data["owner_group_id"] = None
    return data


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def split_blocks(entries):
    return [entries[i:i + MAX_LINES] for i in range(0, len(entries), MAX_LINES)]


def fmt_block(block):
    """Devuelve un bloque de texto con cada título como enlace HTML clicable."""
    return "\n".join(f'<a href="{e["url"]}">{e["title"]}</a>' for e in block)


def is_owner(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == OWNER_ID)


# ---------------- COMANDOS ----------------

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guardar el grupo donde se aplican los comandos cuando hablas por privado."""
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    chat = update.effective_chat
    if chat.type == "private":
        await message.reply_text("Este comando debe usarse dentro del grupo, no en privado.")
        return

    data = load_data()
    data["owner_group_id"] = chat.id
    save_data(data)
    await message.reply_text("✅ Grupo registrado. Ahora puedes usar los comandos en privado.")


async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
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

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
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

    new_norm = normalize(title)
    for e in data["entries"][letra]:
        if normalize(e["title"]) == new_norm:
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

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
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
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    if len(context.args) != 1:
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

    # Ordenar SIEMPRE con acentos normalizados
    entries.sort(key=lambda x: normalize(x["title"]))

    blocks = split_blocks(entries)

    # Determinar en qué chat publicar (grupo o el grupo guardado si estás en privado)
    chat = update.effective_chat
    chat_id = None

    if chat and chat.type != "private":
        chat_id = chat.id
    else:
        # Estamos en privado, usar grupo guardado
        owner_group_id = data.get("owner_group_id")
        if not owner_group_id:
            if update.message:
                await update.message.reply_text(
                    "❌ No tengo ningún grupo configurado.\n"
                    "Ve al grupo y usa /setgroup una vez."
                )
            return
        chat_id = owner_group_id

    # Borrar mensajes antiguos del bot (lista + botón)
    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    data["messages"][letra] = []

    # Publicar bloques
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
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    if len(context.args) != 1:
        await message.reply_text("Uso: /importar A")
        return

    letra = context.args[0].upper()
    context.user_data["import_letter"] = letra
    context.user_data["import_buffer"] = []
    await message.reply_text(
        f"Modo importación para la letra {letra}.\n\n"
        "Copia TODO el listado de esa letra (cada peli o colección en UNA sola línea, "
        "con el enlace de pixeldrain al final) y pégalo aquí (pueden ser varios mensajes).\n"
        "Cuando termines, usa /finalizar."
    )


async def recv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Recoge texto mientras el owner está en modo importación
    if "import_letter" not in context.user_data:
        return

    if not is_owner(update):
        return

    if not update.message or not update.message.text:
        return

    context.user_data["import_buffer"].append(update.message.text)


def parse_line(line: str):
    """Parsea una línea y devuelve {'title': ..., 'url': ...} o None."""
    m = PIXEL_URL_RE.search(line)
    if not m:
        return None

    url = m.group(0).strip()
    title_part = line[: m.start()].rstrip()

    if title_part.endswith("("):
        title_part = title_part[:-1].rstrip()

    if not title_part:
        return None

    title = title_part
    return {"title": title, "url": url}


async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    if "import_letter" not in context.user_data:
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

    # Eliminar duplicados y ordenar con acentos normalizados
    dedup = {}
    for e in data["entries"][letra]:
        key = (normalize(e["title"]), e["url"])
        dedup[key] = e

    data["entries"][letra] = sorted(dedup.values(), key=lambda x: normalize(x["title"]))
    save_data(data)

    context.user_data.clear()

    await message.reply_text(
        f"Importación completada para la letra {letra}. {total} entradas añadidas.\n"
        "Reconstruyendo…"
    )
    await rebuild_topic(update, context, letra)


# ---------------- MAIN ----------------

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta la variable de entorno BOT_TOKEN.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))

    # Mientras importas, cualquier texto del OWNER se añade al buffer
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recv_import))

    app.run_polling()


if __name__ == "__main__":
    main()
