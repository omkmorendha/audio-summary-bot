import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
from pydub import AudioSegment
import time
import logging
import ffmpeg
from celery import Celery
import smtplib
import datetime
import pytz
import ast
from markdownmail import MarkdownMail
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

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def send_email(subject, message, to_email):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT"))
    smtp_login = os.environ.get("SMTP_LOGIN")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("FROM_EMAIL")

    from_name = "SOAP Bot"
    from_addr = f"{from_name} <{from_email}>"

    email = MarkdownMail(
        from_addr=from_addr, to_addr=to_email, subject=subject, content=message
    )
    try:
        email.send(
            smtp_server, login=smtp_login, password=smtp_password, port=smtp_port
        )
        print("Email sent successfully")

    except Exception as e:
        print("Error sending email:", e)


def compress_audio(input_path, output_path):
    """Compress audio file using ffmpeg."""
    try:
        if not output_path.endswith(".mp3"):
            output_path = os.path.splitext(output_path)[0] + ".mp3"

        probe = ffmpeg.probe(input_path)
        if not any(stream["codec_type"] == "audio" for stream in probe["streams"]):
            logger.error(f"No valid audio stream found in {input_path}")
            return None

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
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "1. Turn this Parent session summary transcript into a written SOAP note in English in Markdown format. \n"
                                '2. Replace the Client\'s name with the word CLIENT for privacy and refer to the therapist as the "Clinician"\n'
                                "3. Respond in the following format: \n"
                                """
                                # SOAP NOTE
                                ## Subjective:
                                Subjective here
                                ## Objective:
                                Objective here
                                ## Assessment:
                                Assessment here
                                ## Plan:
                                Plan here
                                """
                                f"Based on the following transcription:\n {transcription}"
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "\nTherapist: Good morning, Sarah! How are you feeling today?\n"
                                "\nSarah: Good morning, Ms. Kelly! I'm feeling good.\n"
                                "\nTherapist: That's great to hear. Are you ready to start our session today?\n"
                                "\nSarah: Yes, I'm ready.\n"
                                "\nTherapist: Wonderful. Let's begin with some warm-up exercises. First, let's practice some deep breathing. Take a deep breath in through your nose and then slowly exhale through your mouth. Let's do that three times. Ready?\n"
                                "\nSarah: (Breathing in and out) One... two... three...\n"
                                "\nTherapist: Excellent, Sarah. Now, let's move on to some tongue exercises. Stick your tongue out as far as you can, then pull it back in. We'll do this five times. Ready? Go!\n"
                                "\nSarah: (Sticking tongue out and in) One... two... three... four... five...\n"
                                '\nTherapist: Great job! Now, let\'s work on some sounds. Repeat after me: "la, la, la."\n'
                                "\nSarah: La, la, la.\n"
                                '\nTherapist: Very good. Now, let\'s try "ta, ta, ta."\n'
                                "\nSarah: Ta, ta, ta.\n"
                                '\nTherapist: Excellent! Now, let\'s put some of those sounds into words. Can you say "ladder"?\n'
                                "\nSarah: Ladder.\n"
                                '\nTherapist: Good job! How about "tiger"?\n'
                                "\nSarah: Tiger.\n"
                                "\nTherapist: You're doing great, Sarah. Let's try a sentence now. Repeat after me: \"The ladder is tall.\"\n"
                                "\nSarah: The ladder is tall.\n"
                                '\nTherapist: Perfect! Now let\'s try, "The tiger is big."\n'
                                "\nSarah: The tiger is big.\n"
                                "\nTherapist: Wonderful! Now, let's play a little game. I'm going to show you some pictures, and I want you to name what you see. Ready?\n"
                                "\nSarah: Yes, I'm ready.\n"
                                "\nTherapist: (Shows a picture of a cat) What's this?\n"
                                "\nSarah: Cat.\n"
                                "\nTherapist: Very good! (Shows a picture of a car) And this?\n"
                                "\nSarah: Car.\n"
                                "\nTherapist: Excellent, Sarah. You're doing so well today. Now, let's practice some sentences using these words. Can you say, \"The cat is sleeping\"?\n"
                                "\nSarah: The cat is sleeping.\n"
                                '\nTherapist: Great! Now, "The car is red."\n'
                                "\nSarah: The car is red.\n"
                                "\nTherapist: Perfect, Sarah. You've done an amazing job today. Keep practicing these exercises at home, and I'll see you next time.\n"
                                "\nSarah: Thank you, Ms. Kelly! See you next time.\n"
                                "\nTherapist: You're welcome, Sarah. Have a great day!\n"
                            ),
                        }
                    ],
                },
            ],
            temperature=0.7,
            max_tokens=4010,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
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
        print(f"Unexpected error: {e}")

    finally:
        if input_path:
            os.remove(input_path)
        if output_path:
            os.remove(output_path)


def prompt_for_email_option(chat_id, report):
    """Prompt the user for email options."""
    report_id = str(uuid.uuid4())
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    redis_client.set(f"message:{report_id}", report)

    current_datetime = datetime.datetime.now(tz=pytz.utc)
    formatted_date = current_datetime.strftime("%d/%m/%Y")
    redis_client.set(f"subject:{report_id}", f"Notes {formatted_date}")
    redis_client.close()

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            f"Edit Subject (Default is 'Notes {formatted_date}')",
            callback_data=f"edit_subject:{report_id}",
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "Edit Body", callback_data=f"edit_message:{report_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "Send Email", callback_data=f"send_email:{report_id}"
        )
    )

    bot.send_message(
        chat_id,
        "Report ready. You can edit the subject and message, or send the email directly.",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_subject"))
def handle_edit_subject(call):
    """Handle subject editing."""
    report_id = call.data.split(":", 1)[1]
    bot.send_message(call.message.chat.id, "Please enter the new subject:")
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id, save_subject, report_id
    )


def save_subject(message, report_id):
    """Save the new subject."""
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    redis_client.set(f"subject:{report_id}", message.text)
    redis_client.close()

    display_report(message.chat.id, report_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_message"))
def handle_edit_message(call):
    """Handle message editing."""
    report_id = call.data.split(":", 1)[1]
    bot.send_message(call.message.chat.id, "Please enter the new message:")
    bot.register_next_step_handler_by_chat_id(
        call.message.chat.id, save_message, report_id
    )


def save_message(message, report_id):
    """Save the new message."""
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    redis_client.set(f"message:{report_id}", message.text)
    redis_client.close()

    display_report(message.chat.id, report_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("send_email"))
def handle_send_email(call):
    """Handle sending the email."""
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    report_id = call.data.split(":", 1)[1]

    subject = redis_client.get(f"subject:{report_id}")
    message = redis_client.get(f"message:{report_id}")

    if not subject:
        current_datetime = datetime.datetime.now(tz=pytz.utc)
        formatted_date = current_datetime.strftime("%d/%m/%Y")

        subject = f"Notes {formatted_date}"

    if not message:
        bot.send_message(call.message.chat.id, "Report not found.")
        redis_client.close()
        return

    if TO_EMAIL:
        for email in TO_EMAIL:
            send_email(subject, message, email)

    redis_client.delete(report_id)
    redis_client.delete(f"subject:{report_id}")
    redis_client.delete(f"message:{report_id}")
    bot.send_message(call.message.chat.id, "Email sent successfully.")
    redis_client.close()


def display_report(chat_id, report_id):
    """Display the report with options to edit or send."""
    redis_client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    subject = redis_client.get(f"subject:{report_id}")
    message = redis_client.get(f"message:{report_id}")

    redis_client.close()

    subject = subject or "(No Subject)"
    message = message or "(No Message)"

    response = f"""
Subject: 
{subject}
    
Body:
{message}
    """

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "Edit Subject", callback_data=f"edit_subject:{report_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "Edit Body", callback_data=f"edit_message:{report_id}"
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "Send Email", callback_data=f"send_email:{report_id}"
        )
    )

    bot.send_message(chat_id, response, reply_markup=markup)


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = (
        "Hi! Send me an audio file and I will generate a written SOAP note in English."
    )
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")


# @bot.message_handler(func=lambda message: True)
# def handle_random_message(message):
#     """Handle random text messages."""
#     default_message = (
#         "I'm sorry, I can only process audio files. Please send me an audio file and I will generate a written SOAP note in English."
#     )
#     bot.send_message(message.chat.id, default_message, parse_mode="Markdown")


@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200
