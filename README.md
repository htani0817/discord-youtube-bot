# Discord YouTube Bot

Discordの指定チャンネルに投稿されたYouTube URLを自動的にYouTubeプレイリストに追加するBotです。

## 機能

- 指定チャンネルに投稿されたYouTube/YouTube Music URLを検出
- 自動的にYouTubeプレイリストに追加
- 重複チェック（同じ動画は追加しない。同じURLが同時に届いても二重に追加しない）
- 複数チャンネルの監視に対応
- Bot起動時に過去メッセージをスキャン（再接続では再実行しない）
- 起動/停止/スキャン完了時のDiscord通知
- 追加の失敗・起動時の準備の失敗もDiscordに通知可能（`notify_on_error`）
- 起動時にYouTube APIの準備（認証・プレイリスト一覧の取得）に失敗したときは、重複追加を防ぐため過去メッセージのスキャンを行わず、URLの投稿時に再試行
- ログ出力（通常ログ + デバッグログ、日次ローテーション）

## 必要要件

- Python 3.9以上
  - Google系ライブラリの最新版はPython 3.10以上が必要です。3.9ではpipが対応する版を自動で選ぶため動作しますが、新しく構築する場合は3.10以上を推奨します
- Discord Bot Token
- Google Cloud Project（YouTube Data API v3）

## ファイル構成

```
discord-youtube-bot/
├── bot.py                      # メインスクリプト（編集不要）
├── config.yaml.example         # 設定ファイルのサンプル
├── client_secret.json.example  # Google OAuth認証情報のサンプル
├── requirements.txt            # Python依存パッケージ
├── youtube-bot.service         # systemdサービス定義
├── .gitignore
└── README.md
```

---

## セットアップ手順

### 1. Discord Botの作成

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」をクリックし、アプリケーションを作成
3. 左メニューの「Bot」を選択
4. 「Reset Token」をクリックしてBot Tokenを取得（後で使用）
5. 「MESSAGE CONTENT INTENT」を有効化
6. 左メニューの「OAuth2」→「URL Generator」を選択
7. SCOPESで「bot」を選択
8. BOT PERMISSIONSで以下を選択：
   - Read Messages/View Channels
   - Send Messages
   - Read Message History
9. 生成されたURLでBotをサーバーに招待

### 2. Google Cloud Projectの設定

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成
3. 「APIとサービス」→「ライブラリ」から「YouTube Data API v3」を有効化
4. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuthクライアントID」
5. アプリケーションの種類：「デスクトップアプリ」を選択
6. 作成後、JSONをダウンロード

### 3. DiscordチャンネルIDの取得

1. Discordの設定 → 詳細設定 → 「開発者モード」を有効化
2. 監視したいチャンネルを右クリック → 「チャンネルIDをコピー」

### 4. YouTubeプレイリストIDの取得

1. YouTubeでプレイリストを作成または開く
2. URLの `list=` 以降の文字列がプレイリストID
   - 例: `https://www.youtube.com/playlist?list=PLxxxxxxxx` → `PLxxxxxxxx`

### 5. サーバーへのデプロイ

```bash
# リポジトリをクローン
git clone https://github.com/yourusername/discord-youtube-bot.git

# 任意のディレクトリに配置（例: /opt/bot）
sudo mkdir -p /opt/bot
sudo cp -r discord-youtube-bot /opt/bot/
cd /opt/bot/discord-youtube-bot

# 依存パッケージをインストール
pip3 install -r requirements.txt
```

※ 以降の手順では `/opt/bot/discord-youtube-bot` に配置した例で説明します。  
　別のパスに配置した場合は、適宜読み替えてください。

### 6. 設定ファイルの作成

```bash
# 設定ファイルをコピー
cp config.yaml.example config.yaml
cp client_secret.json.example client_secret.json
```

**config.yaml を編集:**
```yaml
discord:
  bot_token: "実際のDiscord Bot Token"
  target_channel_ids:
    - 実際のチャンネルID

youtube:
  playlist_id: "実際のプレイリストID"
```

**client_secret.json:**
Google Cloud Consoleからダウンロードした認証情報JSONの内容で上書きしてください。

### 7. YouTube API初回認証

```bash
cd /opt/bot/discord-youtube-bot
python3 bot.py
```

初回起動時、ブラウザが開いてGoogleアカウントの認証を求められます。  
認証後、`token.pickle` が生成され、以降は自動認証されます。

※ヘッドレスサーバーの場合は、ローカルPCで認証を行い、生成された `token.pickle` をサーバーに転送してください。

※ systemdなど、ターミナルのない環境では、新規認証を待たずにログへエラーを記録します（この間、プレイリストへの追加はできません）。初回認証は、必ずターミナルで `python3 bot.py` を実行して行ってください。

### 8. systemdサービスの設定

```bash
# サービスファイルをコピー
sudo cp youtube-bot.service /etc/systemd/system/
```

**サービスファイルのパスを編集:**
```bash
sudo vi /etc/systemd/system/youtube-bot.service
```

以下の2箇所を実際のインストールパスに変更してください：
```ini
WorkingDirectory=/path/to/discord-youtube-bot
ExecStart=/usr/bin/python3 /path/to/discord-youtube-bot/bot.py
```

例（`/opt/bot/discord-youtube-bot` に配置した場合）：
```ini
WorkingDirectory=/opt/bot/discord-youtube-bot
ExecStart=/usr/bin/python3 /opt/bot/discord-youtube-bot/bot.py
```

※ 同梱のサービス定義は root で実行する設定です。専用ユーザーで動かす場合は `User=` / `Group=` を書き換え、そのユーザーが `config.yaml` などを読め、`logs/` と `token.pickle` に書き込める権限を付けてください。

```bash
# サービスを有効化・起動
sudo systemctl daemon-reload
sudo systemctl enable youtube-bot.service
sudo systemctl start youtube-bot.service
```

### 9. 動作確認

```bash
# サービスステータス確認
sudo systemctl status youtube-bot.service

# ログ確認
tail -f /opt/bot/discord-youtube-bot/logs/bot.log
tail -f /opt/bot/discord-youtube-bot/logs/debug.log
```

Discordチャンネルに以下のメッセージが表示されれば成功です：
- 🟢 YouTube Playlist Bot が起動しました。
- ✅ 過去メッセージのスキャンが完了しました。

※ 起動メッセージは、YouTube APIの認証とプレイリスト一覧の取得が済んでから送られます。

---

## 設定項目一覧

| セクション | キー | 説明 | デフォルト |
|-----------|------|------|-----------|
| discord | bot_token | Discord Bot Token | - |
| discord | target_channel_ids | 監視対象チャンネルID（配列） | - |
| youtube | playlist_id | 追加先プレイリストID | - |
| youtube | client_secrets_file | OAuth認証ファイル | client_secret.json |
| youtube | token_pickle_file | トークン保存ファイル | token.pickle |
| bot | history_scan_limit | 起動時スキャン件数（0で全件） | 0 |
| bot | notify_on_success | 成功時Discord通知 | true |
| bot | notify_on_error | 追加失敗時・起動時の準備失敗時のDiscord通知（運用ではtrue推奨） | false |
| bot | notify_on_start | Bot起動時Discord通知 | true |
| bot | notify_on_stop | Bot停止時Discord通知 | true |
| bot | notify_on_scan_complete | スキャン完了時Discord通知 | true |
| logging | log_directory | ログディレクトリ | logs |
| logging | bot_log_name | 通常ログファイル名 | bot |
| logging | debug_log_name | デバッグログファイル名 | debug |
| logging | retention_days | ログ保持日数 | 7 |

---

## ログについて

ログは `logs/` ディレクトリに出力されます（起動時に自動作成）。

| ファイル | 内容 |
|----------|------|
| bot.log | 通常ログ（INFO以上） |
| debug.log | デバッグログ（DEBUG以上、全て） |
| bot-YYYYMMDD.log | ローテーション済み通常ログ |
| debug-YYYYMMDD.log | ローテーション済みデバッグログ |

設定した保持日数を超えた古いログは自動削除されます。

---

## トラブルシューティング

### 設定エラーで起動しない

```bash
cat /opt/bot/discord-youtube-bot/logs/bot.log
```

エラーメッセージを確認し、`config.yaml` の設定を見直してください。

### 起動メッセージが出ない／動画が追加されない

`logs/bot.log` に `YouTube APIの準備に失敗しました` などのエラーが出ていないか確認してください。

```bash
grep -E "\[(ERROR|CRITICAL)\]" /opt/bot/discord-youtube-bot/logs/bot.log | tail
```

認証かプレイリスト一覧の取得に失敗すると、Botは接続したまま、過去メッセージのスキャンと追加を行いません（一覧がないと、すでに入っている動画を重複して追加してしまうため）。
URLが投稿されると、前回の失敗から60秒以上あけて準備を再試行します。サービスの再起動でも再試行されます。
`notify_on_error: true` にしておくと、準備の失敗や追加の失敗がチャンネルに通知されます。

### token.pickleの有効期限切れ

```bash
rm /opt/bot/discord-youtube-bot/token.pickle
sudo systemctl restart youtube-bot.service
# ブラウザで再認証（初回のみ必要）
```

※ ターミナルのない環境（systemdなど）では再認証できません。`rm` のあと、サービスを止めて、ターミナルで `python3 bot.py` を実行して認証してください。

Google Cloud Consoleの「Google Auth Platform」→「対象」で、公開ステータスが「テスト」のままだと、リフレッシュトークンは7日で失効します。「本番環境」にしてください。

### チャンネルIDが見つからない

- Botがそのサーバーに参加しているか確認
- チャンネルIDが正しいか確認（開発者モードで再取得）
- Botにチャンネルへのアクセス権限があるか確認

### YouTube APIエラー

- Google Cloud ConsoleでYouTube Data API v3が有効か確認
- APIの割り当て（quota）を超えていないか確認
  - 動画の追加（`playlistItems.insert`）は1回あたり50ユニット消費し、既定の上限は1日10,000ユニット（約200本）です。過去メッセージが多い初回起動では、上限に達することがあります。上限は太平洋時間の0時にリセットされます
  - 初回起動では、追加できた動画ごとに通知が出ます。多いときは `notify_on_success: false` にしてください
- `client_secret.json` の内容が正しいか確認

---

## ライセンス

MIT License
