import json
import os
import re
import unicodedata
import html
import requests
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
        return {
            "topics": {},
            "entries": {},
            "messages": {},
            "owner_group_id": None,
            "fichas_group_id": None,
            "fichas_topic_id": None,
        }
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {
            "topics": {},
            "entries": {},
            "messages": {},
            "owner_group_id": None,
            "fichas_group_id": None,
            "fichas_topic_id": None,
        }
    # Añadir claves nuevas si faltan
    if "owner_group_id" not in data:
        data["owner_group_id"] = None
    if "fichas_group_id" not in data:
        data["fichas_group_id"] = None
    if "fichas_topic_id" not in data:
        data["fichas_topic_id"] = None
    return data


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def split_blocks(entries):
    return [entries[i:i + MAX_LINES] for i in range(0, len(entries), MAX_LINES)]


def fmt_block(block):
    """Devuelve un bloque de texto con cada título como enlace HTML clicable."""
    return "\n".join(f'<a href="{e["url"]}">{html.escape(e["title"])}</a>' for e in block)


def is_owner(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == OWNER_ID)


# ---------------- TMDB ----------------

def get_tmdb_info(title: str, year: str | None):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return None

    try:
        # Buscar película
        params = {
            "api_key": api_key,
            "language": "es-ES",
            "query": title,
        }
        if year:
            params["year"] = year

        r = requests.get(
            "https://api.themoviedb.org/3/search/movie",
            params=params,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None

        movie = results[0]
        movie_id = movie.get("id")
        if not movie_id:
            return None

        # Detalles de la película
        r2 = requests.get(
            f"https://api.themoviedb.org/3/movie/{movie_id}",
            params={"api_key": api_key, "language": "es-ES"},
            timeout=10,
        )
        r2.raise_for_status()
        det = r2.json()

        overview = det.get("overview") or movie.get("overview") or ""
        if len(overview) > 800:
            overview = overview[:800].rsplit(" ", 1)[0] + "…"

        genres = ", ".join(g.get("name") for g in det.get("genres", []) if g.get("name"))
        runtime = det.get("runtime")
        vote = det.get("vote_average")

        poster_path = det.get("poster_path") or movie.get("poster_path")
        poster_url = None
        if poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w780{poster_path}"

        return {
            "overview": overview,
            "genres": genres,
            "runtime": runtime,
            "vote": vote,
            "poster_url": poster_url,
        }
    except Exception:
        return None


async def create_ficha_for_movie(title: str, url: str, context: ContextTypes.DEFAULT_TYPE):
    """Crea ficha en el grupo/tema configurado con /setfichas."""
    data = load_data()
    fichas_group_id = data.get("fichas_group_id")
    fichas_topic_id = data.get("fichas_topic_id")

    if not fichas_group_id or not fichas_topic_id:
        return

    # Extraer año
    year = None
    m = re.search(r"\((\d{4})\)", title)
    if m:
        year = m.group(1)

    # Título para búsqueda TMDB
    title_for_tmdb = re.sub(r"\(\d{4}\)", "", title).strip()

    tmdb = get_tmdb_info(title_for_tmdb, year)
    if tmdb:
        overview = tmdb.get("overview") or ""
        genres = tmdb.get("genres") or ""
        runtime = tmdb.get("runtime")
        vote = tmdb.get("vote")
        poster_url = tmdb.get("poster_url")
    else:
        overview = ""
        genres = ""
        runtime = None
        vote = None
        poster_url = None

    # Construcción de ficha
    lines = []
    lines.append(html.escape(title))
    lines.append("")

    info_lines = []
    if vote is not None:
        info_lines.append(f"⭐ Puntuación TMDB: {vote:.1f}/10")
    if genres:
        info_lines.append(f"🎭 Géneros: {html.escape(genres)}")
    if runtime:
        info_lines.append(f"🕒 Duración: {runtime} minutos")

    if info_lines:
        lines.extend(info_lines)
        lines.append("")

    if overview:
        lines.append(html.escape(overview))
        lines.append("")

    safe_url = html.escape(url, quote=True)
    lines.append(f'Para ver la película pulsa <a href="{safe_url}">AQUÍ</a>')

    caption = "\n".join(lines)

    try:
        if poster_url:
            await context.bot.send_photo(
                chat_id=fichas_group_id,
                message_thread_id=fichas_topic_id,
                photo=poster_url,
                caption=caption,
                parse_mode=constants.ParseMode.HTML,
            )
        else:
            await context.bot.send_message(
                chat_id=fichas_group_id,
                message_thread_id=fichas_topic_id,
                text=caption,
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=False,
            )
    except Exception:
        pass


# ---------------- COMANDOS ----------------

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    chat = update.effective_chat
    if chat.type == "private":
        await message.reply_text("Este comando debe usarse dentro del grupo de listados, no en privado.")
        return

    data = load_data()
    data["owner_group_id"] = chat.id
    save_data(data)
    await message.reply_text("✅ Grupo de listados registrado. Ahora puedes usar los comandos en privado.")


async def setfichas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    chat = update.effective_chat
    topic_id = message.message_thread_id

    if chat.type == "private":
        await message.reply_text("Este comando debe usarse en el grupo de fichas, dentro del tema deseado.")
        return
    if topic_id is None:
        await message.reply_text("Este comando debe usarse dentro del TEMA donde quieres las fichas.")
        return

    data = load_data()
    data["fichas_group_id"] = chat.id
    data["fichas_topic_id"] = topic_id
    save_data(data)
    await message.reply_text("✅ Tema de fichas configurado correctamente.")


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
        await message.reply_text("Uso: /add TÍTULO (AÑO) URL")
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

    # Reconstruir listado
    await rebuild_topic(update, context, letra)

    # Crear ficha automáticamente
    await create_ficha_for_movie(title, url, context)

    await message.reply_text(f"Añadido en la letra {letra}.")


# ----------------------------------------------------
#   DELETE MEJORADO (búsqueda parcial + botones)
# ----------------------------------------------------

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    if not is_owner(update):
        await message.reply_text("❌ No tienes permiso para usar este comando.")
        return

    if len(context.args) < 1:
        await message.reply_text("Uso: /delete título")
        return

    query = " ".join(context.args).strip().lower()
    data = load_data()

    coincidencias = []

    # Buscar coincidencias parciales en todas las letras
    for letra, lista in data["entries"].items():
        for e in lista:
            if query in e["title"].lower():
                coincidencias.append((letra, e))

    if not coincidencias:
        await message.reply_text("❌ No se encontraron coincidencias.")
        return

    # Guardamos las coincidencias en user_data para usarlas al pulsar el botón
    context.user_data["delete_matches"] = coincidencias

    # Si solo hay una coincidencia, borramos directamente
    if len(coincidencias) == 1:
        letra, entry = coincidencias[0]
        data["entries"][letra].remove(entry)
        save_data(data)
        await message.reply_text(f"✔ Eliminado: {entry['title']}\nReconstruyendo…")
        await rebuild_topic(update, context, letra)
        context.user_data.pop("delete_matches", None)
        return

    # Varias coincidencias: mostramos botones
    botones = []
    for idx, (letra, entry) in enumerate(coincidencias):
        botones.append([
            InlineKeyboardButton(entry["title"], callback_data=f"del:{idx}")
        ])

    await message.reply_text(
        "🎯 Varias coincidencias encontradas. Selecciona cuál eliminar:",
        reply_markup=InlineKeyboardMarkup(botones)
    )


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        await query.edit_message_text("❌ No tienes permiso para eliminar.")
        return

    try:
        idx = int(query.data.replace("del:", ""))
    except ValueError:
        await query.edit_message_text("❌ Selección no válida.")
        return

    matches = context.user_data.get("delete_matches")
    if not matches or idx < 0 or idx >= len(matches):
        await query.edit_message_text("❌ No se encontró la coincidencia seleccionada.")
        return

    letra, entry = matches[idx]

    data = load_data()
    lista = data["entries"].get(letra, [])

    # Eliminar la entrada exacta
    lista[:] = [e for e in lista if not (e["title"] == entry["title"] and e["url"] == entry["url"])]
    save_data(data)

    # Limpiar buffer
    context.user_data.pop("delete_matches", None)

    await query.edit_message_text(f"✔ Eliminado: {entry['title']}\nReconstruyendo…")

    # Reconstruir el topic usando el mismo update (callback_query)
    await rebuild_topic(update, context, letra)


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

    entries.sort(key=lambda x: normalize(x["title"]))

    blocks = split_blocks(entries)

    chat = update.effective_chat
    if chat.type != "private":
        chat_id = chat.id
    else:
        owner_group_id = data.get("owner_group_id")
        if not owner_group_id:
            if update.message:
                await update.message.reply_text(
                    "❌ No tengo ningún grupo de listados configurado.\n"
                    "Ve al grupo y usa /setgroup una vez."
                )
            return
        chat_id = owner_group_id

    # Borrar lista anterior
    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    data["messages"][letra] = []

    # Enviar bloques
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

    # Botón final
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
        "Copia TODO el listado de esa letra y pégalo aquí (pueden ser varios mensajes).\n"
        "Cuando termines, usa /finalizar."
    )


async def recv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        return
    if not is_owner(update):
        return
    if not update.message or not update.message.text:
        return

    context.user_data["import_buffer"].append(update.message.text)


def parse_line(line: str):
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
    app.add_handler(CommandHandler("setfichas", setfichas))
    app.add_handler(CommandHandler("settopic", settopic))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("rebuild", rebuild))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))

    app.add_handler(CallbackQueryHandler(confirm_delete, pattern="^del:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recv_import))

    app.run_polling()


if __name__ == "__main__":
    main()
