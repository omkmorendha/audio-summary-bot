import os
import openai
import pyshorteners
from flask import Flask, request
from telebot import TeleBot, types
from telegram.constants import ParseMode
from pydub import AudioSegment
import urllib.parse
import time
import logging
import ffmpeg
from celery import Celery
import datetime
import pytz
import ast
import uuid
import redis

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["CELERY_BROKER_URL"] = os.environ.get(
    "REDIS_URL", "redis://localhost:6379/0"
)
app.config["CELERY_RESULT_BACKEND"] = os.environ.get(
    "REDIS_URL", "redis://localhost:6379/0"
)

celery = Celery(app.name, broker=app.config["CELERY_BROKER_URL"])
celery.conf.update(app.config)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
URL = os.environ.get("URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
TO_EMAIL = ast.literal_eval(os.environ.get("TO_EMAIL"))

bot = TeleBot(BOT_TOKEN, threaded=True)
# bot.remove_webhook()
# time.sleep(1)
# bot.set_webhook(url=f"{URL}/{WEBHOOK_SECRET}")

# Connect to Redis
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

def compress_audio(input_path, output_path):
    """Compress audio file using ffmpeg."""
    try:
        if not output_path.endswith(".mp3"):
            output_path = os.path.splitext(output_path)[0] + ".mp3"

        probe = ffmpeg.probe(input_path)
        if not any(stream["codec_type"] == "audio" for stream in probe["streams"]):
            logger.error(f"No valid audio stream found in {input_path}")
            return None

        # Perform compression
        (
            ffmpeg.input(input_path)
            .output(
                output_path,
                ac=1,
                codec="libmp3lame",
                audio_bitrate="12k",
                application="voip",
            )
            .run(overwrite_output=True)
        )
        return output_path
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"Error compressing audio: {error_message}")
        return None
    except Exception as e:
        logger.error(f"Error compressing audio: {e}")
        return None

def transcribe_audio(file_path):
    """Transcribe audio file using OpenAI's Whisper model."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", file=f, language="en"
            )
        return transcription.text
    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        return None

def generate_report(transcription):
    """Generate a report based on the transcription using GPT-3.5."""
    try:
        openai_client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
        prompt = f"Turn this Parent session summary transcript into a written SOAP note in English in Markdown format. Strictly replace the Client's name with the word CLIENT for privacy. Based on the following transcription:\n\n{transcription}"
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
        )
        report = response.choices[0].message.content
        return report
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return None

def send_long_message(chat_id, message):
    """Send long message in chunks."""
    for i in range(0, len(message), 4095):
        bot.send_message(chat_id, message[i : i + 4095], parse_mode="Markdown")

@bot.message_handler(content_types=["document", "audio", "voice"])
def handle_files(message):
    """Handle audio files sent as documents or directly."""
    if message.content_type == "document":
        document = message.document
        if document.mime_type.startswith("audio/"):
            file_info = bot.get_file(document.file_id)
            file_path = f"downloads/{document.file_unique_id}.{file_info.file_path.split('.')[-1]}"
            bot.reply_to(message, "Please wait while we process the file")
            download_and_process.delay(file_info.file_path, file_path, message.chat.id)
        else:
            bot.reply_to(message, "Please send an audio file.")
    elif message.content_type in ["audio", "voice"]:
        audio_file = message.audio or message.voice
        file_info = bot.get_file(audio_file.file_id)
        file_path = f"downloads/{audio_file.file_unique_id}.{file_info.file_path.split('.')[-1]}"
        bot.reply_to(message, "Please wait while we process the file")
        download_and_process.delay(file_info.file_path, file_path, message.chat.id)
    else:
        bot.reply_to(message, "Unsupported file format.")

@celery.task
def download_and_process(remote_path, local_path, chat_id):
    """Download file from Telegram and process."""
    downloaded_file = bot.download_file(remote_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as new_file:
        new_file.write(downloaded_file)
    process_audio.delay(local_path, chat_id)

@celery.task
def process_audio(input_path, chat_id):
    """Process audio file."""
    output_path = os.path.join(
        "downloads", "compressed_" + os.path.basename(input_path)
    )
    
    try:
        compressed_path = compress_audio(input_path, output_path)
        if compressed_path:
            transcription = transcribe_audio(compressed_path)
            if transcription:
                report = generate_report(transcription)
                if report:
                    send_long_message(chat_id, report)
                    prompt_for_email_option(chat_id, report)
                else:
                    bot.send_message(chat_id, "Failed to generate report.")
            else:
                bot.send_message(chat_id, "Failed to transcribe audio.")
        else:
            bot.send_message(chat_id, "Failed to compress audio.")
    except Exception as e:
        print(f'Unexpected error: {e}')

    finally:
        if input_path:
            os.remove(input_path)
        if output_path:
            os.remove(output_path)

def prompt_for_email_option(chat_id, report):
    """Prompt the user for email options."""
    report_id = str(uuid.uuid4())
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    redis_client.set(report_id, report)
    redis_client.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Mail Report", callback_data=f"mail_report:{report_id}"))
    bot.send_message(chat_id, "The report has been generated. You can mail it by clicking the button below:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("mail_report"))
def handle_mail_report(call):
    """Handle the 'Mail Report' button click."""
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    action, report_id = call.data.split(":", 1)
    report = redis_client.get(report_id)

    if not report:
        bot.send_message(call.message.chat.id, "Report not found.")
        return

    current_datetime = datetime.datetime.now(tz=pytz.utc)
    formatted_date = current_datetime.strftime("%d/%m/%Y")
    subject = f"Notes {formatted_date}"
    body = report.rstrip().replace("\n", "%0D%0A").replace(" ", "+")
    to_email = ",".join(TO_EMAIL)
    
    mailto_link = f"mailto:{to_email}?subject={urllib.parse.quote(subject)}&body={body}"
    print(mailto_link[:2000])  

    try:
        shortener = pyshorteners.Shortener()
        tinyurl_link = shortener.tinyurl.short(mailto_link[:2000])
        
        # bot.send_message(call.message.chat.id, f"Click {tinyurl_link} to open your email client, or copy and paste the link below:\n\n{tinyurl_link}")
        bot.send_message(call.message.chat.id, text=f"Click <a href='{tinyurl_link}'>here</a> to open your email client", parse_mode=ParseMode.HTML)
    except Exception as e:
        bot.send_message(call.message.chat.id, "Failed to shorten the URL. Please try again later.")
        logger.error(f"Error shortening URL: {e}")
    
    redis_client.delete(report_id)
    redis_client.close()

@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = (
        "Hi! Send me an audio file and I will generate a written SOAP note in English."
    )
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")

@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200
