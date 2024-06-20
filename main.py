import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
from pydub import AudioSegment
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Retrieve environment variables
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
BOT_TOKEN = os.environ.get('BOT_TOKEN')
URL = os.environ.get('URL')

# Initialize Telegram bot
bot = TeleBot(BOT_TOKEN, threaded=False)
bot.remove_webhook()
bot.set_webhook(url=URL)


def transcribe_audio(file_path):
    """Transcribe audio file using OpenAI's Whisper model."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        with open(file_path, 'rb') as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language='en'
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
        prompt = f"Generate a detailed report based on the following transcription:\n\n{transcription}"
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        report = response.choices[0].message.content
        return report
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return None


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = 'Hi! Send me an audio file and I will transcribe it and generate a report.'
    bot.send_message(message.chat.id, message_to_send, parse_mode='Markdown')



@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Handle audio files sent as documents."""
    print('received document')

    document = message.document
    if document.mime_type.startswith('audio/'):
        try:
            file_info = bot.get_file(document.file_id)
            file_extension = file_info.file_path.split('.')[-1]
            file_path = f"downloads/{document.file_unique_id}.{file_extension}"

            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            audio = AudioSegment.from_file(file_path)
            wav_path = file_path.replace(file_extension, 'wav')
            audio.export(wav_path, format='wav')

            transcription = transcribe_audio(wav_path)
            if transcription:
                report = generate_report(transcription)
                output = transcription + "\n\n" + report

                if report:
                    bot.reply_to(message, output)
                else:
                    bot.reply_to(message, 'Failed to generate report.')
            else:
                bot.reply_to(message, 'Failed to transcribe audio.')

        except Exception as e:
            logger.error(f"Error handling audio document: {e}")
            bot.reply_to(message, 'An error occurred while processing your audio file.')

        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(wav_path):
                os.remove(wav_path)

    else:
        bot.reply_to(message, 'Please send an audio file.')


@bot.message_handler(content_types=['audio', 'voice'])
def handle_audio(message):
    """Handle audio file uploads."""
    print('received audio')

    audio_file = message.audio or message.voice
    if not audio_file:
        bot.reply_to(message, 'Please send a valid audio file or voice message.')
        return

    try:
        file_info = bot.get_file(audio_file.file_id)
        file_extension = file_info.file_path.split('.')[-1]
        file_path = f"downloads/{audio_file.file_unique_id}.{file_extension}"

        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        audio = AudioSegment.from_file(file_path)
        wav_path = file_path.replace(file_extension, 'wav')
        audio.export(wav_path, format='wav')

        transcription = transcribe_audio(wav_path)
        if transcription:
            report = generate_report(transcription)
            if report:
                bot.reply_to(message, report)
            else:
                bot.reply_to(message, 'Failed to generate report.')
        else:
            bot.reply_to(message, 'Failed to transcribe audio.')

    except Exception as e:
        logger.error(f"Error handling audio file: {e}")
        bot.reply_to(message, 'An error occurred while processing your audio file or voice message.')

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(wav_path):
            os.remove(wav_path)


@app.route('/', methods=['POST'])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode('utf8'))
    bot.process_new_updates([update])
    return 'ok', 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
