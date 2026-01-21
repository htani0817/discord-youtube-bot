import os
import re
import sys
import signal
import asyncio
import discord
import yaml
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pickle

# =============================================================================
# 設定ファイル読み込み
# =============================================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.yaml"

def load_config():
    """設定ファイルを読み込む"""
    if not CONFIG_FILE.exists():
        print(f"エラー: 設定ファイルが見つかりません: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()

# =============================================================================
# ログ設定
# =============================================================================
def setup_logging():
    """ログシステムを初期化する"""
    log_config = config.get("logging", {})
    log_dir = SCRIPT_DIR / log_config.get("log_directory", "logs")
    bot_log_name = log_config.get("bot_log_name", "bot")
    debug_log_name = log_config.get("debug_log_name", "debug")
    retention_days = log_config.get("retention_days", 7)

    # ログディレクトリ作成
    log_dir.mkdir(parents=True, exist_ok=True)

    # ログフォーマット
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # カスタムnamer: bot.log -> bot-20250122.log 形式にする
    def log_namer(default_name):
        """ローテーション時のファイル名を変更"""
        # default_name: /path/to/logs/bot.log.2025-01-22
        base_dir = Path(default_name).parent
        parts = Path(default_name).name.split(".")
        if len(parts) >= 3:
            # bot.log.2025-01-22 -> bot-20250122.log
            name = parts[0]
            date_str = parts[2].replace("-", "")
            return str(base_dir / f"{name}-{date_str}.log")
        return default_name

    def log_rotator(source, dest):
        """ローテーション処理"""
        if os.path.exists(source):
            os.rename(source, dest)

    # ルートロガー設定
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 既存ハンドラをクリア
    root_logger.handlers.clear()

    # --- 通常ログ（INFO以上）---
    bot_log_path = log_dir / f"{bot_log_name}.log"
    bot_handler = TimedRotatingFileHandler(
        bot_log_path,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8"
    )
    bot_handler.setLevel(logging.INFO)
    bot_handler.setFormatter(formatter)
    bot_handler.namer = log_namer
    bot_handler.rotator = log_rotator
    root_logger.addHandler(bot_handler)

    # --- デバッグログ（DEBUG以上、全て）---
    debug_log_path = log_dir / f"{debug_log_name}.log"
    debug_handler = TimedRotatingFileHandler(
        debug_log_path,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)
    debug_handler.namer = log_namer
    debug_handler.rotator = log_rotator
    root_logger.addHandler(debug_handler)

    # --- コンソール出力（INFO以上）---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 古いログファイルを削除
    cleanup_old_logs(log_dir, bot_log_name, retention_days)
    cleanup_old_logs(log_dir, debug_log_name, retention_days)

    return logging.getLogger(__name__)

def cleanup_old_logs(log_dir, log_name, retention_days):
    """指定日数を超えた古いログファイルを削除する"""
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    pattern = re.compile(rf"^{re.escape(log_name)}-(\d{{8}})\.log$")
    
    for file_path in log_dir.iterdir():
        match = pattern.match(file_path.name)
        if match:
            try:
                file_date = datetime.strptime(match.group(1), "%Y%m%d")
                if file_date < cutoff_date:
                    file_path.unlink()
                    logging.debug(f"古いログファイルを削除しました: {file_path.name}")
            except ValueError:
                continue

# ログシステム初期化
logger = setup_logging()

# =============================================================================
# 設定値の取得
# =============================================================================
# Discord設定
discord_config = config.get("discord", {})
DISCORD_BOT_TOKEN = discord_config.get("bot_token")
TARGET_CHANNEL_IDS = set(discord_config.get("target_channel_ids", []))

# YouTube設定
youtube_config = config.get("youtube", {})
YOUTUBE_PLAYLIST_ID = youtube_config.get("playlist_id")
CLIENT_SECRETS_FILE = str(SCRIPT_DIR / youtube_config.get("client_secrets_file", "client_secret.json"))
TOKEN_PICKLE_FILE = str(SCRIPT_DIR / youtube_config.get("token_pickle_file", "token.pickle"))

# Bot動作設定
bot_config = config.get("bot", {})
HISTORY_SCAN_LIMIT = bot_config.get("history_scan_limit", 0)
# 0またはNoneの場合は全件スキャン（limit=None）
if not HISTORY_SCAN_LIMIT:
    HISTORY_SCAN_LIMIT = None
NOTIFY_ON_SUCCESS = bot_config.get("notify_on_success", True)
NOTIFY_ON_ERROR = bot_config.get("notify_on_error", False)
NOTIFY_ON_START = bot_config.get("notify_on_start", True)
NOTIFY_ON_STOP = bot_config.get("notify_on_stop", True)
NOTIFY_ON_SCAN_COMPLETE = bot_config.get("notify_on_scan_complete", True)

# 設定値の検証
if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
    logger.error("Discord Bot Tokenが設定されていません。config.yamlを確認してください。")
    sys.exit(1)

if not YOUTUBE_PLAYLIST_ID or YOUTUBE_PLAYLIST_ID == "YOUR_YOUTUBE_PLAYLIST_ID_HERE":
    logger.error("YouTube Playlist IDが設定されていません。config.yamlを確認してください。")
    sys.exit(1)

if not TARGET_CHANNEL_IDS:
    logger.error("監視対象のチャンネルIDが設定されていません。config.yamlを確認してください。")
    sys.exit(1)

logger.info(f"設定ファイルを読み込みました: {CONFIG_FILE}")
logger.info(f"監視対象チャンネル数: {len(TARGET_CHANNEL_IDS)}")
logger.debug(f"監視対象チャンネルID: {TARGET_CHANNEL_IDS}")

# =============================================================================
# YouTube API設定
# =============================================================================
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

def get_authenticated_service():
    """YouTube APIの認証を行い、サービスオブジェクトを返す"""
    creds = None
    # token.pickleファイルが存在すれば、そこから認証情報を読み込む
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, "rb") as token:
            creds = pickle.load(token)
        logger.debug("既存のtoken.pickleから認証情報を読み込みました")
    # 認証情報が存在しないか、無効な場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.debug("認証情報の有効期限が切れています。リフレッシュを試みます...")
            creds.refresh(Request())
            logger.info("認証情報をリフレッシュしました")
        else:
            logger.info("新規認証が必要です。ブラウザで認証してください...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            logger.info("新規認証が完了しました")
        # 新しい認証情報をtoken.pickleに保存
        with open(TOKEN_PICKLE_FILE, "wb") as token:
            pickle.dump(creds, token)
        logger.debug("認証情報をtoken.pickleに保存しました")
    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)

# =============================================================================
# Discordクライアント初期化
# =============================================================================
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
client = discord.Client(intents=intents)

# =============================================================================
# URL検出パターン
# =============================================================================
# YouTubeのURLからビデオIDを抽出する正規表現
YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})"
)

# 汎用URL検出（YouTube以外のURLをスルーするためのガード用）
URL_PATTERN = re.compile(r"https?://\S+")

# =============================================================================
# YouTube API操作
# =============================================================================
def get_playlist_video_ids(service, playlist_id):
    """プレイリスト内の既存のビデオIDを取得する"""
    video_ids = set()
    try:
        request = service.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50
        )
        while request:
            response = request.execute()
            for item in response["items"]:
                video_ids.add(item["snippet"]["resourceId"]["videoId"])
            request = service.playlistItems().list_next(request, response)
        logger.debug(f"プレイリストから{len(video_ids)}件のビデオIDを取得しました")
    except Exception as e:
        logger.error(f"プレイリストの取得中にエラーが発生しました: {e}")
    return video_ids

async def add_video_to_playlist(video_id, channel):
    """動画をプレイリストに追加する"""
    global existing_video_ids
    
    if video_id in existing_video_ids:
        logger.info(f"ビデオID {video_id} は既にプレイリストに存在します。")
        return

    try:
        logger.debug(f"ビデオID {video_id} をプレイリストに追加中...")
        request = youtube_service.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": YOUTUBE_PLAYLIST_ID,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )
        response = request.execute()
        title = response['snippet']['title']
        logger.info(f"動画がプレイリストに追加されました: {title} (ID: {video_id})")
        
        if NOTIFY_ON_SUCCESS:
            await channel.send(
                f"動画「{title}」をプレイリストに追加しました！\n"
                f"URL: https://www.youtube.com/playlist?list={YOUTUBE_PLAYLIST_ID}"
            )
        existing_video_ids.add(video_id)
        
    except Exception as e:
        if "video already in playlist" in str(e):
            logger.debug(f"ビデオID {video_id} はAPI側で重複と判断されました。")
            existing_video_ids.add(video_id)
        else:
            logger.error(f"プレイリストへの追加中にエラーが発生しました: {e}")
            if NOTIFY_ON_ERROR:
                await channel.send("エラーが発生したため、動画をプレイリストに追加できませんでした。")

# =============================================================================
# Discordイベントハンドラ
# =============================================================================
async def send_to_all_channels(message_text):
    """全ての監視対象チャンネルにメッセージを送信する"""
    for channel_id in TARGET_CHANNEL_IDS:
        channel = client.get_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(message_text)
                logger.debug(f"チャンネル「{channel.name}」にメッセージを送信しました")
            except Exception as e:
                logger.error(f"チャンネル「{channel.name}」へのメッセージ送信に失敗: {e}")

@client.event
async def on_ready():
    """Bot起動時の処理"""
    logger.info(f"{client.user} としてログインしました")

    # 起動メッセージを送信
    if NOTIFY_ON_START:
        await send_to_all_channels("🟢 YouTube Playlist Bot が起動しました。")

    # YouTube APIサービスの認証と既存動画の取得
    global youtube_service, existing_video_ids
    youtube_service = get_authenticated_service()
    logger.info("YouTube APIの認証が完了しました")

    logger.info("既存のプレイリスト内容を取得しています...")
    existing_video_ids = get_playlist_video_ids(youtube_service, YOUTUBE_PLAYLIST_ID)
    logger.info(f"{len(existing_video_ids)} 件の動画が既にプレイリストに存在します。")

    # 各監視対象チャンネルの履歴をスキャン
    logger.info("過去のメッセージをスキャンしています...")
    total_added = 0
    for channel_id in TARGET_CHANNEL_IDS:
        channel = client.get_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            if channel.permissions_for(channel.guild.me).read_message_history:
                logger.info(f"チャンネル「{channel.name}」(ID: {channel_id}) の履歴をスキャン中...")
                try:
                    message_count = 0
                    added_count = 0
                    async for message in channel.history(limit=HISTORY_SCAN_LIMIT):
                        if message.author == client.user:
                            continue
                        match = YOUTUBE_URL_PATTERN.search(message.content)
                        if match:
                            video_id = match.group(1)
                            before_count = len(existing_video_ids)
                            await add_video_to_playlist(video_id, channel)
                            if len(existing_video_ids) > before_count:
                                added_count += 1
                        message_count += 1
                    logger.debug(f"チャンネル「{channel.name}」: {message_count}件のメッセージをスキャンしました")
                    total_added += added_count
                except discord.Forbidden:
                    logger.warning(f"チャンネル「{channel.name}」へのアクセスが禁止されています。")
                except Exception as e:
                    logger.error(f"チャンネル「{channel.name}」のスキャン中にエラーが発生しました: {e}")
            else:
                logger.warning(f"チャンネル「{channel.name}」(ID: {channel_id}) の履歴読み取り権限がありません。")
        else:
            logger.warning(f"チャンネルID {channel_id} が見つからないか、テキストチャンネルではありません。")
    
    logger.info("過去のメッセージのスキャンが完了しました。")
    logger.info("メッセージの監視を開始します。")

    # スキャン完了メッセージを送信
    if NOTIFY_ON_SCAN_COMPLETE:
        await send_to_all_channels(
            f"✅ 過去メッセージのスキャンが完了しました。\n"
            f"プレイリスト内の動画数: {len(existing_video_ids)}件"
        )

@client.event
async def on_message(message):
    """メッセージ受信時の処理"""
    # ボット自身のメッセージは無視
    if message.author == client.user:
        return

    # 監視対象チャンネル以外は無視
    if message.channel.id not in TARGET_CHANNEL_IDS:
        return

    logger.debug(f"メッセージを受信: チャンネル={message.channel.name}, 投稿者={message.author}")

    # 非YouTube URLは完全スルー
    if URL_PATTERN.search(message.content) and not YOUTUBE_URL_PATTERN.search(message.content):
        logger.debug("YouTube以外のURLを検出しました。スキップします。")
        return

    # メッセージからYouTubeのURLを検索
    match = YOUTUBE_URL_PATTERN.search(message.content)
    if match:
        video_id = match.group(1)
        logger.info(f"YouTubeのビデオIDを検出しました: {video_id}")
        await add_video_to_playlist(video_id, message.channel)

# =============================================================================
# シャットダウン処理
# =============================================================================
async def shutdown():
    """Bot停止時の処理"""
    logger.info("シャットダウン処理を開始します...")
    
    # 停止メッセージを送信
    if NOTIFY_ON_STOP and client.is_ready():
        await send_to_all_channels("🔴 YouTube Playlist Bot を停止します。")
    
    # Discordクライアントを閉じる
    await client.close()
    logger.info("シャットダウン処理が完了しました。")

def signal_handler(sig, frame):
    """シグナルハンドラ"""
    logger.info(f"シグナル {sig} を受信しました。停止処理を開始します...")
    # 非同期のシャットダウン処理を実行
    asyncio.ensure_future(shutdown())

# =============================================================================
# メイン処理
# =============================================================================
if __name__ == "__main__":
    logger.info("Discord YouTube Botを起動しています...")
    logger.debug(f"Pythonバージョン: {sys.version}")
    logger.debug(f"スクリプトディレクトリ: {SCRIPT_DIR}")
    
    # シグナルハンドラを設定
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        client.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logger.critical("Discord Botのログインに失敗しました。Tokenを確認してください。")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"予期しないエラーが発生しました: {e}")
        sys.exit(1)
