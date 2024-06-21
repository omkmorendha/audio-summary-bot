import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
from pydub import AudioSegment
import time
import logging
import ffmpeg

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
URL = os.environ.get("URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

bot = TeleBot(BOT_TOKEN, threaded=False)
# bot.remove_webhook()
# time.sleep(1)
# bot.set_webhook(url=f"{URL}/{WEBHOOK_SECRET}")


def compress_audio(input_path, output_path):
    """Compress audio file using ffmpeg."""
    try:
        (
            ffmpeg.input(input_path)
            .output(
                output_path,
                ac=1,
                codec="libopus",
                audio_bitrate="12k",
                application="voip",
            )
            .run(overwrite_output=True)
        )
        return output_path
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
        prompt = f"Turn this parent session summary transcript into a written SOAP note in English. Replace the Client's name with the word CLIENT. Based on the following transcription:\n\n{transcription}"
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
        bot.send_message(chat_id, message[i : i + 4095])


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = (
        "Hi! Send me an audio file and I will transcribe it and generate a report."
    )
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")


@bot.message_handler(content_types=["document"])
def handle_document(message):
    """Handle audio files sent as documents."""
    document = message.document
    input_path = None
    output_path = None

    if document.mime_type.startswith("audio/"):
        try:
            file_info = bot.get_file(document.file_id)
            file_extension = file_info.file_path.split(".")[-1]
            input_path = f"downloads/{document.file_unique_id}.{file_extension}"

            downloaded_file = bot.download_file(file_info.file_path)
            os.makedirs(os.path.dirname(input_path), exist_ok=True)
            with open(input_path, "wb") as new_file:
                new_file.write(downloaded_file)

            bot.reply_to(message, "Please wait while we process the audio file")

            # Compress the audio file
            output_path = os.path.join(
                "downloads", "compressed_" + document.file_unique_id + ".ogg"
            )
            compressed_path = compress_audio(input_path, output_path)
            if compressed_path:
                transcription = transcribe_audio(compressed_path)
                if transcription:
                    report = generate_report(transcription)

                    if report:
                        send_long_message(message.chat.id, report)
                    else:
                        bot.reply_to(message, "Failed to generate report.")
                else:
                    bot.reply_to(message, "Failed to transcribe audio.")

        except Exception as e:
            logger.error(f"Error handling audio document: {e}")
            bot.reply_to(message, "An error occurred while processing your audio file.")

        finally:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)

    else:
        bot.reply_to(message, "Please send an audio file.")


@bot.message_handler(content_types=["audio", "voice"])
def handle_audio(message):
    """Handle audio file uploads."""
    print("received audio")

    audio_file = message.audio or message.voice
    if not audio_file:
        bot.reply_to(message, "Please send a valid audio file or voice message.")
        return

    try:
        file_info = bot.get_file(audio_file.file_id)
        file_extension = file_info.file_path.split(".")[-1]
        input_path = f"downloads/{audio_file.file_unique_id}.{file_extension}"

        downloaded_file = bot.download_file(file_info.file_path)
        with open(input_path, "wb") as new_file:
            new_file.write(downloaded_file)

        bot.reply_to(message, "Please wait while we process the audio file")
        # Compress the audio file
        output_path = os.path.join(
            "downloads", "compressed_" + audio_file.file_unique_id + ".ogg"
        )
        compressed_path = compress_audio(input_path, output_path)
        if compressed_path:
            transcription = transcribe_audio(compressed_path)
            if transcription:
                report = generate_report(transcription)

                if report:
                    send_long_message(message.chat.id, report)
                else:
                    bot.reply_to(message, "Failed to generate report.")
            else:
                bot.reply_to(message, "Failed to transcribe audio.")

    except Exception as e:
        logger.error(f"Error handling audio file: {e}")
        bot.reply_to(
            message,
            "An error occurred while processing your audio file or voice message.",
        )

    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)


@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200
