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

DATA_FILE = "/data/data.json"
MAX_LINES = 100
INDEX_URL = "https://t.me/cinehdcastellano2/2/2840"

OWNER_ID = 5540195020

PIXEL_URL_RE = re.compile(
    r"https?://pixeldrain\.net/(?:u|l)/[^\s)]+",
    re.IGNORECASE,
)


# ---------------- UTILIDADES ----------------

def normalize(s: str) -> str:
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
    except:
        data = {
            "topics": {},
            "entries": {},
            "messages": {},
            "owner_group_id": None,
            "fichas_group_id": None,
            "fichas_topic_id": None,
        }
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
    return "\n".join(f'<a href="{e["url"]}">{html.escape(e["title"])}</a>' for e in block)


def is_owner(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == OWNER_ID


# ---------------- TMDB ----------------

def get_tmdb_info(title: str, year: str | None):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return None
    try:
        params = {"api_key": api_key, "language": "es-ES", "query": title}
        if year:
            params["year"] = year
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None
        movie = results[0]
        movie_id = movie.get("id")
        if not movie_id:
            return None

        r2 = requests.get(
            f"https://api.themoviedb.org/3/movie/{movie_id}",
            params={"api_key": api_key, "language": "es-ES"},
            timeout=10,
        )
        det = r2.json()

        overview = det.get("overview") or movie.get("overview") or ""
        if len(overview) > 800:
            overview = overview[:800].rsplit(" ", 1)[0] + "…"

        genres = ", ".join(g["name"] for g in det.get("genres", []) if g.get("name"))
        runtime = det.get("runtime")
        vote = det.get("vote_average")
        poster_path = det.get("poster_path") or movie.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w780{poster_path}" if poster_path else None

        return {
            "overview": overview,
            "genres": genres,
            "runtime": runtime,
            "vote": vote,
            "poster_url": poster_url,
        }
    except:
        return None


async def create_ficha_for_movie(title: str, url: str, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    g = data.get("fichas_group_id")
    t = data.get("fichas_topic_id")
    if not g or not t:
        return

    year = None
    m = re.search(r"\((\d{4})\)", title)
    if m:
        year = m.group(1)

    title_for_tmdb = re.sub(r"\(\d{4}\)", "", title).strip()
    tmdb = get_tmdb_info(title_for_tmdb, year)

    if tmdb:
        overview = tmdb["overview"]
        genres = tmdb["genres"]
        runtime = tmdb["runtime"]
        vote = tmdb["vote"]
        poster_url = tmdb["poster_url"]
    else:
        overview = ""
        genres = ""
        runtime = None
        vote = None
        poster_url = None

    lines = [html.escape(title), ""]
    if vote is not None:
        lines.append(f"⭐ Puntuación TMDB: {vote:.1f}/10")
    if genres:
        lines.append(f"🎭 Géneros: {html.escape(genres)}")
    if runtime:
        lines.append(f"🕒 Duración: {runtime} minutos")
    if vote or genres or runtime:
        lines.append("")
    if overview:
        lines.append(html.escape(overview))
        lines.append("")
    safe_url = html.escape(url, quote=True)
    lines.append(f'<a href="{safe_url}">Ver AQUÍ</a>')

    caption = "\n".join(lines)

    try:
        if poster_url:
            await context.bot.send_photo(
                chat_id=g, message_thread_id=t, photo=poster_url,
                caption=caption, parse_mode=constants.ParseMode.HTML
            )
        else:
            await context.bot.send_message(
                chat_id=g, message_thread_id=t, text=caption,
                parse_mode=constants.ParseMode.HTML
            )
    except:
        pass


# ---------------- COMANDOS ----------------

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if update.effective_chat.type == "private":
        return await update.message.reply_text("Use este comando dentro del grupo.")
    data = load_data()
    data["owner_group_id"] = update.effective_chat.id
    save_data(data)
    await update.message.reply_text("✅ Grupo registrado correctamente.")


async def setfichas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    chat = update.effective_chat
    topic_id = update.message.message_thread_id
    if chat.type == "private":
        return await update.message.reply_text("Use este comando en grupo.")
    if topic_id is None:
        return await update.message.reply_text("Úsalo dentro del tema deseado.")
    data = load_data()
    data["fichas_group_id"] = chat.id
    data["fichas_topic_id"] = topic_id
    save_data(data)
    await update.message.reply_text("✅ Tema de fichas configurado.")


async def settopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if len(context.args) != 1:
        return await update.message.reply_text("Uso: /settopic A")
    letra = context.args[0].upper()
    topic_id = update.message.message_thread_id
    if topic_id is None:
        return await update.message.reply_text("Debe usarse dentro del tema deseado.")
    data = load_data()
    data["topics"][letra] = topic_id
    save_data(data)
    await update.message.reply_text(f"Letra {letra} configurada.")


# ---------------- ADD ----------------

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if len(context.args) < 2:
        return await update.message.reply_text("Uso: /add TÍTULO (AÑO) URL")

    url = context.args[-1]
    title = " ".join(context.args[:-1]).strip()
    if not title:
        return await update.message.reply_text("Título vacío.")

    first = title[0].upper()
    letra = first if "A" <= first <= "Z" else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])

    new_norm = normalize(title)
    for e in data["entries"][letra]:
        if normalize(e["title"]) == new_norm:
            return await update.message.reply_text("⚠️ Ya existe ese título.")

    data["entries"][letra].append({"title": title, "url": url})
    data["entries"][letra].sort(key=lambda x: normalize(x["title"]))
    save_data(data)

    await rebuild_topic(update, context, letra)
    await create_ficha_for_movie(title, url, context)

    await update.message.reply_text(f"Añadido en {letra}.")


# ----------------------------------------------------
# DELETE SIN CONFIRMACION (Funciona 100%)
# ----------------------------------------------------

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")

    if len(context.args) < 1:
        return await update.message.reply_text("Uso: /delete título")

    query = " ".join(context.args).strip().lower()
    data = load_data()

    coincidencias = []

    for letra, lista in data["entries"].items():
        for idx, e in enumerate(lista):
            if query in e["title"].lower():
                coincidencias.append((letra, idx, e))

    if not coincidencias:
        return await update.message.reply_text("❌ No se encontraron coincidencias.")

    if len(coincidencias) == 1:
        letra, idx, entry = coincidencias[0]
        data["entries"][letra].pop(idx)
        save_data(data)
        await update.message.reply_text(f"✔ Eliminado: {entry['title']}")
        await rebuild_topic(update, context, letra)
        return

    botones = []
    for letra, idx, entry in coincidencias:
        botones.append([
            InlineKeyboardButton(entry["title"], callback_data=f"del:{letra}:{idx}")
        ])

    await update.message.reply_text(
        "Selecciona cuál eliminar:",
        reply_markup=InlineKeyboardMarkup(botones),
    )


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return await query.edit_message_text("❌ No autorizado.")

    _, letra, idx = query.data.split(":")
    idx = int(idx)

    data = load_data()
    lista = data["entries"].get(letra, [])

    if idx < 0 or idx >= len(lista):
        return await query.edit_message_text("❌ Ya no existe.")

    entry = lista.pop(idx)
    save_data(data)

    await query.edit_message_text(f"✔ Eliminado: {entry['title']}")

    await rebuild_topic(update, context, letra)


# ---------------- REBUILD ----------------

async def rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if len(context.args) != 1:
        return await update.message.reply_text("Uso: /rebuild A")
    letra = context.args[0].upper()
    await rebuild_topic(update, context, letra)


async def rebuild_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, letra: str):
    data = load_data()
    if letra not in data["topics"]:
        if update.message:
            await update.message.reply_text(
                f"No está configurada la letra {letra}. Usa /settopic {letra}"
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
        group = data.get("owner_group_id")
        if not group:
            return await update.message.reply_text("❌ Usa /setgroup primero.")
        chat_id = group

    # Borrar mensajes antiguos
    for msg_id in data["messages"].get(letra, []):
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass

    data["messages"][letra] = []

    # Publicar bloques nuevos
    for block in blocks:
        text = fmt_block(block)
        msg = await context.bot.send_message(
            chat_id, message_thread_id=topic_id, text=text,
            parse_mode=constants.ParseMode.HTML, disable_web_page_preview=True
        )
        data["messages"][letra].append(msg.message_id)

    # Botón índice
    msg = await context.bot.send_message(
        chat_id, message_thread_id=topic_id,
        text=f'<a href="{INDEX_URL}">Volver al índice</a>',
        parse_mode=constants.ParseMode.HTML,
    )
    data["messages"][letra].append(msg.message_id)

    save_data(data)


# ---------------- IMPORTACIÓN ----------------

async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if len(context.args) != 1:
        return await update.message.reply_text("Uso: /importar A")
    letra = context.args[0].upper()
    context.user_data["import_letter"] = letra
    context.user_data["import_buffer"] = []
    await update.message.reply_text(
        f"Modo importación para {letra}. Pegue el listado y luego /finalizar"
    )


async def recv_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "import_letter" not in context.user_data:
        return
    if not is_owner(update):
        return
    if not update.message.text:
        return
    context.user_data["import_buffer"].append(update.message.text)


def parse_line(line: str):
    m = PIXEL_URL_RE.search(line)
    if not m:
        return None
    url = m.group(0)
    title = line[: m.start()].strip()
    return {"title": title, "url": url}


async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return await update.message.reply_text("❌ No autorizado.")
    if "import_letter" not in context.user_data:
        return await update.message.reply_text("No estás importando nada.")

    letra = context.user_data["import_letter"]
    buffer = context.user_data["import_buffer"]

    data = load_data()
    data["entries"].setdefault(letra, [])

    total = 0
    for msg in buffer:
        for line in msg.splitlines():
            line = line.strip()
            if not line:
                continue
            p = parse_line(line)
            if p:
                data["entries"][letra].append(p)
                total += 1

    dedup = {}
    for e in data["entries"][letra]:
        key = (normalize(e["title"]), e["url"])
        dedup[key] = e

    data["entries"][letra] = sorted(dedup.values(), key=lambda x: normalize(x["title"]))
    save_data(data)

    context.user_data.clear()

    await update.message.reply_text(f"Importados {total} elementos.\nReconstruyendo…")
    await rebuild_topic(update, context, letra)


# ---------------- MAIN ----------------

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Falta BOT_TOKEN")

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
