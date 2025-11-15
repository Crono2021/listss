import os
import json
import html
import aiohttp
import unicodedata
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

DATA_FILE = "/data/botdb.json"
OWNER_ID = 5540195020  # ← TU ID
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "1f8cdf0007b2df2c1e11920cb50cfccf")

INDEX_URL = "https://t.me/cinehdcastellano2/2/2840"   # botón volver índice
GROUP_ID = -1000000000000  # ← cambia por el grupo donde se crean fichas
TOPIC_ID = 123456          # ← cambia por el ID del tema donde van fichas


# ----------------------------------------------
#        CARGA Y SALVADO DE BASE DE DATOS
# ----------------------------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"entries": {}, "messages": {}, "import": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ----------------------------------------------
#         PERMISOS SOLO PARA EL OWNER
# ----------------------------------------------

def is_owner(update: Update):
    user = update.effective_user
    return user and user.id == OWNER_ID


# ----------------------------------------------
#      NORMALIZAR TEXTO PARA ORDEN ALFABÉTICO
# ----------------------------------------------

def normalize(text: str):
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# -------------------------------------------------
#    OBTENER DATOS DE TMDB PARA LA FICHA
# -------------------------------------------------

async def tmdb_search(title):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            data = await r.json()
            return data["results"][0] if data["results"] else None


async def tmdb_details(movie_id):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=es-ES"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            return await r.json()


# -------------------------------------------------
#         CREAR FICHA AUTOMÁTICA
# -------------------------------------------------

async def create_ficha_for_movie(title, url, context: ContextTypes.DEFAULT_TYPE):

    search = await tmdb_search(title)
    if not search:
        return

    details = await tmdb_details(search["id"])
    if not details:
        return

    poster_path = details.get("poster_path")
    poster_url = (
        f"https://image.tmdb.org/t/p/original{poster_path}" if poster_path else None
    )

    puntuacion = details.get("vote_average", "N/D")
    duracion = details.get("runtime", "N/D")
    generos = ", ".join(g["name"] for g in details.get("genres", []))

    descripcion = details.get("overview", "Sin descripción disponible.")

    safe_url = html.escape(url, quote=True)

    texto = (
        f"<b>{details['title']} ({details.get('release_date','')[:4]})</b>\n\n"
        f"⭐ <b>Puntuación TMDB:</b> {puntuacion}\n"
        f"🎭 <b>Géneros:</b> {generos}\n"
        f"⏳ <b>Duración:</b> {duracion} min\n\n"
        f"{descripcion}\n\n"
        f'Para ver la película pulsa <a href="{safe_url}">AQUÍ</a>'
    )

    await context.bot.send_photo(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ID,
        photo=poster_url,
        caption=texto,
        parse_mode=ParseMode.HTML,
    )


# -------------------------------------------------
#             RECONSTRUIR LISTADO
# -------------------------------------------------

async def rebuild_topic(update, context, letra):
    data = load_data()
    entries = data["entries"].get(letra, [])

    # borrar mensajes antiguos
    if data["messages"].get(letra):
        for msg_id in data["messages"][letra]:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=msg_id
                )
            except:
                pass

    data["messages"][letra] = []

    # dividir en bloques de 100 líneas
    bloque = []
    mensajes = []

    for e in entries:
        bloque.append(f'<a href="{e["url"]}">{e["title"]}</a>')
        if len(bloque) == 100:
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                message_thread_id=update.message.message_thread_id,
                text="\n".join(bloque),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            mensajes.append(msg.message_id)
            bloque = []

    if bloque:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=update.message.message_thread_id,
            text="\n".join(bloque),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        mensajes.append(msg.message_id)

    # botón volver índice
    boton = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VOLVER ATRÁS", url=INDEX_URL)]]
    )
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        message_thread_id=update.message.message_thread_id,
        text=" ",
        reply_markup=boton,
    )
    mensajes.append(msg.message_id)

    data["messages"][letra] = mensajes
    save_data(data)


# -------------------------------------------------
#                    COMANDO /ADD
# -------------------------------------------------

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not is_owner(update):
        return

    if len(context.args) < 2:
        await message.reply_text("Uso: /add TITULO (AÑO) URL")
        return

    url = context.args[-1]
    title = " ".join(context.args[:-1])

    first = title[0].upper()
    letra = first if "A" <= first <= "Z" else "#"

    data = load_data()
    data["entries"].setdefault(letra, [])

    new_norm = normalize(title)

    # evitar duplicado en listado *Y FICHA*
    for e in data["entries"][letra]:
        if normalize(e["title"]) == new_norm:
            await message.reply_text("⚠️ Esa película ya existe. No se añadirá ni se creará ficha.")
            return

    # añadir
    data["entries"][letra].append({"title": title, "url": url})
    data["entries"][letra].sort(key=lambda x: normalize(x["title"]))
    save_data(data)

    await rebuild_topic(update, context, letra)

    # crear ficha
    await create_ficha_for_movie(title, url, context)

    await message.reply_text("Película añadida.")


# -------------------------------------------------
#                  COMANDO /REMOVE
# -------------------------------------------------

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    if len(context.args) == 0:
        await update.message.reply_text("Uso: /remove TÍTULO")
        return

    titulo = " ".join(context.args)
    letra = titulo[0].upper()
    if not ("A" <= letra <= "Z"):
        letra = "#"

    data = load_data()
    if letra not in data["entries"]:
        await update.message.reply_text("Esa letra no existe.")
        return

    antes = len(data["entries"][letra])
    data["entries"][letra] = [e for e in data["entries"][letra] if normalize(e["title"]) != normalize(titulo)]
    despues = len(data["entries"][letra])

    if antes == despues:
        await update.message.reply_text("No se encontró esa película.")
        return

    save_data(data)
    await rebuild_topic(update, context, letra)
    await update.message.reply_text("Película eliminada.")


# -------------------------------------------------
#                 IMPORTAR BLOQUES
# -------------------------------------------------

async def importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Uso: /importar A")
        return

    letra = context.args[0].upper()
    if not ("A" <= letra <= "Z"):
        letra = "#"

    data = load_data()
    data["import"][update.effective_user.id] = letra
    save_data(data)

    await update.message.reply_text(f"Modo importación activado para {letra}. Reenvíame los bloques.")


async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    data = load_data()
    letra = data["import"].pop(update.effective_user.id, None)
    if not letra:
        await update.message.reply_text("No estás importando nada.")
        return

    save_data(data)
    await rebuild_topic(update, context, letra)
    await update.message.reply_text("Importación completada.")


# ----------------------------------------------
#          CAPTURA TEXTO DURANTE IMPORTACIÓN
# ----------------------------------------------

async def texto_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    data = load_data()
    letra = data["import"].get(msg.from_user.id)
    if not letra:
        return

    lineas = msg.text.split("\n")
    for l in lineas:
        l = l.strip()
        if not l:
            continue

        # detectar formato "Título (AÑO) (URL)" o sin año
        if "(" in l and ")" in l and "http" in l:
            try:
                partes = l.rsplit("(", 1)
                titulo = partes[0].strip()
                url = partes[1].replace(")", "").strip()
            except:
                continue

            data["entries"].setdefault(letra, [])
            data["entries"][letra].append({"title": titulo, "url": url})

    save_data(data)


# -------------------------------------------------
#                  INICIO DEL BOT
# -------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot operativo.")


def main():
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("rebuild", rebuild_topic))
    app.add_handler(CommandHandler("importar", importar))
    app.add_handler(CommandHandler("finalizar", finalizar))

    # captura texto de importación
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto_import))

    app.run_polling()


if __name__ == "__main__":
    main()
