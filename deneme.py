import os
import logging
import time
from threading import Thread
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
from telegram import Update
from telegram.ext import ContextTypes
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta

# Logger ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Adım sabitleri
TITLE, DESCRIPTION, TAGS, YOUTUBE_SCHEDULE = range(4)

# Planlanmış videoları saklamak için basit bir veri yapısı
scheduled_videos = []

# YouTube API kullanarak videoyu yükle
def upload_video_to_youtube(file_path, title, description, tags, scheduled_time=None):
    """YouTube API kullanarak videoyu yükleyen fonksiyon."""
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    # Token.json olup olmadığını kontrol et (önceden yetkilendirme yapıldıysa)
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Eğer token yoksa ya da geçersizse, yeniden yetkilendirme yap
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Mutlak yol ile client_secret.json dosyasını kullan
            flow = InstalledAppFlow.from_client_secrets_file(
                r'C:\Users\Zehedisode\Desktop\telegram botu\client_secret_734143850367-7pg8mn24r7jv12ss6n7g16npaejbqdh3.apps.googleusercontent.com.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        
        # Yeni token'ı kaydet
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # YouTube API'yi yetkilendirme ile başlat
    youtube = build('youtube', 'v3', credentials=creds)

    # Video bilgileri
    request_body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags.split(',') if tags else [],  # Etiketler boş olabilir
            'categoryId': '24',  # Eğlence kategorisi (ID: 24)
            'defaultLanguage': 'en',  # Başlık ve açıklama dili: İngilizce
            'defaultAudioLanguage': 'en'  # Video dili: İngilizce
        },
        'status': {
            'privacyStatus': 'private',  # Videoyu gizli yapıyoruz, planlama varsa yayına alınana kadar gizli kalacak
        }
    }

    # Eğer planlanmış bir zaman varsa, videoyu o tarihte yayımlamak için zamanı ekle
    if scheduled_time:
        request_body['status']['publishAt'] = scheduled_time.isoformat()  # ISO formatında zaman
        request_body['status']['privacyStatus'] = 'private'  # Planlanan videolar "private" olur

    # Videoyu yükle
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    response_upload = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    ).execute()

    video_id = response_upload.get('id')
    logger.info(f"Video başarıyla yüklendi. Video ID: {video_id}")
    return video_id

# Geri sayım fonksiyonu
def start_countdown(seconds, video_data, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verilen süreyi bekleyip video yüklemeyi başlatır."""
    logger.info(f"Geri sayım başladı: {seconds} saniye")
    while seconds > 0:
        time.sleep(1)
        seconds -= 1

    # Geri sayım tamamlanınca YouTube'a video yükle
    context.bot.send_message(chat_id=update.effective_chat.id, text=f"Hey! Süre doldu, '{video_data['title']}' başlıklı videon YouTube'a yükleniyor...")
    upload_video_to_youtube(video_data['file_path'], video_data['title'], video_data['description'], video_data.get('tags', ''), video_data['youtube_schedule'])

    # Video yüklendikten sonra listeyi güncelle
    scheduled_videos.remove(video_data)

# Videonun başlığını kullanıcıdan al
async def ask_for_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıdan video başlığı alır."""
    await update.message.reply_text("Merhaba! 🖐️ Video başlığını yazıp bana gönderir misin?")
    return TITLE

# Açıklamayı al
async def ask_for_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıdan video açıklamasını alır."""
    context.user_data['title'] = update.message.text
    await update.message.reply_text("Harika! 🎉 Şimdi de videonun açıklamasını yazar mısın?")
    return DESCRIPTION

# Etiketleri al
async def ask_for_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıdan video etiketlerini alır."""
    context.user_data['description'] = update.message.text
    await update.message.reply_text("Süper! 🏷️ Şimdi videon için birkaç etiket ekle. Lütfen etiketleri virgülle ayırarak yaz.")
    return TAGS

# YouTube'da yayımlanacağı tarihi sor (Gün Ay Yıl Saat:Dakika formatında)
async def ask_for_youtube_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıdan videonun YouTube'da yayımlanma tarihini alır."""
    context.user_data['tags'] = update.message.text  # 'tags' anahtarı burada kaydediliyor
    await update.message.reply_text("Neredeyse tamam! 🎯 Son olarak, YouTube'da videonun ne zaman yayımlanacağını gün/ay/yıl saat:dakika formatında belirtir misin?")
    return YOUTUBE_SCHEDULE

# YouTube tarihini ve saatini alıp geri sayımı başlat
async def process_youtube_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcıdan alınan YouTube tarihini işleyip, bot için geri sayım başlatır."""
    try:
        youtube_input = update.message.text
        youtube_day, youtube_month, youtube_year, youtube_time = youtube_input.split()
        youtube_hour, youtube_minute = youtube_time.split(":")
        youtube_schedule_time = datetime(int(youtube_year), int(youtube_month), int(youtube_day), int(youtube_hour), int(youtube_minute))
        context.user_data['youtube_schedule'] = youtube_schedule_time

        # Bot için planlanan zamanı hesapla (YouTube planlamasından 10 dakika önce)
        bot_schedule_time = youtube_schedule_time - timedelta(minutes=10)
        context.user_data['bot_schedule'] = bot_schedule_time

        now = datetime.now()

        video_data = {
            'file_path': context.user_data['file_path'],
            'title': context.user_data['title'],
            'description': context.user_data['description'],
            'tags': context.user_data.get('tags', ''),
            'youtube_schedule': youtube_schedule_time,
            'bot_schedule': bot_schedule_time
        }

        # Eğer bot zamanlaması şu anki zamandan önceyse (yani 10 dakikadan az süre varsa), doğrudan yükle
        if bot_schedule_time < now:
            await update.message.reply_text(f"Vay be! Yükleme zamanı çok yakın. Videoyu hemen YouTube'a gönderiyorum! 🚀")
            upload_video_to_youtube(video_data['file_path'], video_data['title'], video_data['description'], video_data.get('tags', ''), youtube_schedule_time)
        else:
            await update.message.reply_text(f"Tamamdır! Video YouTube'da {youtube_schedule_time} tarihinde yayımlanacak. Bot, {bot_schedule_time} tarihinde yüklemeye başlayacak. 📅")
            # Geri sayım süresini hesapla
            countdown_seconds = (bot_schedule_time - now).total_seconds()
            scheduled_videos.append(video_data)  # Videoyu planlananlar listesine ekle
            # Geri sayımı başlat
            countdown_thread = Thread(target=start_countdown, args=(countdown_seconds, video_data, update, context))
            countdown_thread.start()
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Hmmm, sanırım yanlış bir format girdin. 🧐 Lütfen 'Gün Ay Yıl Saat:Dakika' formatında gir.")
        return YOUTUBE_SCHEDULE

# Planlanan videoları listele
async def list_scheduled_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Planlanmış videoları listeler."""
    if not scheduled_videos:
        await update.message.reply_text("Şu anda planlanmış hiçbir video yok. 📭")
        return

    # Planlanmış videoları listele
    message = "📅 Planlanmış Videolar:\n"
    for idx, video in enumerate(scheduled_videos, 1):
        message += f"{idx}. {video['title']} - {video['youtube_schedule'].strftime('%Y-%m-%d %H:%M')}\n"
    message += "\nBir videoyu iptal etmek için /iptal [numara] komutunu kullanın."
    await update.message.reply_text(message)

# Planlanan bir videoyu iptal et
async def cancel_scheduled_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Planlanmış bir videoyu iptal eder."""
    try:
        video_idx = int(context.args[0]) - 1
        if 0 <= video_idx < len(scheduled_videos):
            canceled_video = scheduled_videos.pop(video_idx)
            await update.message.reply_text(f"'{canceled_video['title']}' başlıklı video iptal edildi. 🚫")
        else:
            await update.message.reply_text("Geçersiz video numarası. Lütfen doğru bir numara girin.")
    except (IndexError, ValueError):
        await update.message.reply_text("Lütfen iptal etmek istediğiniz videonun numarasını girin. Örneğin: /iptal 1")

# Videoyu indir ve yükle
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram üzerinden gönderilen video veya dosya olarak gönderilen video dosyasını indirip dosya yolunu kaydeder."""
    
    if update.message.video:  # Video olarak gönderildiyse
        video_file = await context.bot.get_file(update.message.video.file_id)
    elif update.message.document:  # Dosya olarak gönderildiyse
        video_file = await context.bot.get_file(update.message.document.file_id)
    else:
        await update.message.reply_text("Geçerli bir video dosyası gönderin (MP4 veya MOV formatında).")
        return ConversationHandler.END

    file_path = f"videos/{video_file.file_id}.mp4"

    # 'videos' klasörünün var olup olmadığını kontrol et, yoksa oluştur
    if not os.path.exists('videos'):
        os.makedirs('videos')

    # Dosyayı indir
    await video_file.download_to_drive(file_path)

    # Dosya yolunu kaydet
    context.user_data['file_path'] = file_path

    await update.message.reply_text("Video başarıyla alındı! 🎥 Şimdi birkaç detay isteyeceğim.")

    # Başlık adımına yönlendir
    return await ask_for_title(update, context)


# /start komutu için basit bir handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botun başlangıç mesajını gönderir ve sıfırdan başlatır."""
    # Kullanıcı verilerini sıfırla
    context.user_data.clear()
    
    # Hoş geldiniz mesajı
    welcome_message = (
        "Merhaba! 😊 Ben YouTube video yükleme botuyum! 🎥\n"
        "Aşağıdaki adımları takip ederek videolarınızı YouTube'a yükleyebilirsiniz:\n\n"
        "📌 Botun Özellikleri:\n"
        "1. Telegram üzerinden video yükleyin.\n"
        "2. Videonun başlık, açıklama ve etiket bilgilerini girin.\n"
        "3. Yayınlanma zamanını planlayın (isteğe bağlı).\n"
        "4. Videolarınızı YouTube'a yükleyin!\n\n"
        "💡 Kullanım Talimatları:\n"
        "- Bir video göndererek başlayın. Sonrasında bot, videonun başlığı, açıklaması ve etiketleri gibi bilgileri soracak.\n"
        "- Eğer yükleme için bir tarih ve saat belirtirseniz, bot videonuzu planlanan zamanda YouTube'a yükleyecektir.\n\n"
        "🔧 Komutlar:\n"
        "- /start - Botu yeniden başlatır ve sizi karşılar.\n"
        "- /liste - Planlanan videoların listesini gösterir.\n"
        "- /iptal [numara] - Planlanmış bir videoyu iptal eder.\n\n"
        "Bir video gönderin, hemen başlayalım! 🚀"
    )
    
    # Mesajı kullanıcıya gönder
    await update.message.reply_text(welcome_message)

    return ConversationHandler.END



def main():
    """Botun ana fonksiyonu ve tüm handler'ların tanımlanması."""
    # Telegram bot token'ınızı buraya ekleyin
    application = Application.builder().token('7500254811:AAGPy9JKmzJjw5rr1Dgr9-yRfCAlr8pZ06s').build()

    # Konuşma sırası
    conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start), 
                  MessageHandler(filters.VIDEO | (filters.Document.MimeType("video/mp4") | filters.Document.MimeType("video/quicktime")), handle_video)],
    states={
        TITLE: [MessageHandler(filters.TEXT, ask_for_description)],
        DESCRIPTION: [MessageHandler(filters.TEXT, ask_for_tags)],
        TAGS: [MessageHandler(filters.TEXT, ask_for_youtube_schedule)],
        YOUTUBE_SCHEDULE: [MessageHandler(filters.TEXT, process_youtube_schedule)],
    },
    fallbacks=[CommandHandler("start", start)]  # Kullanıcı ne zaman /start komutunu girerse baştan başlasın
)


    # Komutlar ekleyelim
    application.add_handler(CommandHandler("liste", list_scheduled_videos))
    application.add_handler(CommandHandler("iptal", cancel_scheduled_video))

    # Konuşma işleyicisini ekle
    application.add_handler(conv_handler)

    # Botu çalıştır
    print("Bot başlatılıyor...")
    application.run_polling()

if __name__ == '__main__':
    main()
