import os
import time
import json
import base64
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.exceptions import RefreshError

# 必要な権限
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl'  # コメント投稿に必要
]
TOKEN_FILE = 'token.json'

class YouTubeUploader:
    def __init__(self, client_secrets_file='client_secrets.json'):
        self.client_secrets_file = client_secrets_file
        self.youtube = self._get_authenticated_service()

    def _log(self, level, message):
        """統一されたログ出力"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = {
            'INFO': '[INFO]',
            'SUCCESS': '[OK]',
            'WARNING': '[WARN]',
            'ERROR': '[ERR]',
            'DEBUG': '[DBG]'
        }.get(level, '[LOG]')
        print(f"[{timestamp}] {prefix} {message}")

    def _save_token(self, creds):
        """トークンを安全に保存しGitHub Secrets用のBase64も出力"""
        try:
            # JSON形式で保存
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

            self._log('SUCCESS', f'トークンを保存: {TOKEN_FILE}')

            # GitHub Actions環境の場合Base64エンコードを出力
            if os.getenv('GITHUB_ACTIONS') == 'true':
                token_json = creds.to_json()
                token_base64 = base64.b64encode(token_json.encode()).decode()
                self._log('INFO', '=== GitHub Secrets更新用 ===')
                self._log('INFO', f'YOUTUBE_TOKEN_BASE64={token_base64[:50]}...')
                self._log('WARNING', '上記のトークンをGitHub Secretsに手動更新してください')

            return True
        except Exception as e:
            self._log('ERROR', f'トークン保存失敗: {e}')
            return False

    def _check_token_expiry(self, creds):
        """トークンの有効期限をチェックし情報を表示"""
        try:
            if hasattr(creds, 'expiry') and creds.expiry:
                expiry_time = creds.expiry
                now = datetime.utcnow()
                remaining = (expiry_time - now).total_seconds()

                if remaining > 0:
                    hours = int(remaining / 3600)
                    minutes = int((remaining % 3600) / 60)
                    self._log('DEBUG', f'アクセストークン有効期限: あと{hours}時間{minutes}分')
                else:
                    self._log('WARNING', 'アクセストークンは期限切れです（リフレッシュが必要）')

            # refresh_tokenの確認
            if hasattr(creds, 'refresh_token') and creds.refresh_token:
                self._log('DEBUG', 'リフレッシュトークン: 有効')
            else:
                self._log('WARNING', 'リフレッシュトークンが存在しません（再認証が必要）')
        except Exception as e:
            self._log('WARNING', f'トークン有効期限チェック失敗: {e}')

    def _refresh_token_with_retry(self, creds, max_retries=3, retry_delay=5):
        """リトライ機能付きでトークンをリフレッシュ"""
        for attempt in range(1, max_retries + 1):
            try:
                self._log('INFO', f'トークンリフレッシュ試行 ({attempt}/{max_retries})')
                creds.refresh(Request())
                self._log('SUCCESS', 'トークンリフレッシュ成功')

                # リフレッシュ後の有効期限チェック
                self._check_token_expiry(creds)

                # トークンを保存
                self._save_token(creds)

                return True

            except RefreshError as e:
                self._log('ERROR', f'リフレッシュトークンエラー: {e}')
                self._log('ERROR', '原因の可能性:')
                self._log('ERROR', '  1. ユーザーがhttps://myaccount.google.com/permissionsで認証を取り消した')
                self._log('ERROR', '  2. リフレッシュトークンの有効期限切れ（通常6ヶ月）')
                self._log('ERROR', '  3. client_secrets.jsonが変更された')
                self._log('ERROR', '対処法: ローカルで再認証してtoken.jsonを再生成してください')
                return False

            except Exception as e:
                self._log('WARNING', f'リフレッシュ失敗 ({attempt}/{max_retries}): {e}')

                if attempt < max_retries:
                    self._log('INFO', f'{retry_delay}秒後にリトライします...')
                    time.sleep(retry_delay)
                else:
                    self._log('ERROR', 'リトライ回数上限に達しました')
                    return False

        return False

    def _get_authenticated_service(self):
        """OAuth2認証を行いYouTube APIサービスを返す（完璧版）"""
        try:
            creds = None

            # === STEP 0: 環境変数から直接認証（D/E/F群対応） ===
            env_client_id = os.environ.get('YOUTUBE_CLIENT_ID')
            env_client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')
            env_refresh_token = os.environ.get('YOUTUBE_REFRESH_TOKEN')

            if env_client_id and env_client_secret and env_refresh_token:
                self._log('INFO', '環境変数からOAuth認証情報を取得')
                try:
                    creds = Credentials(
                        token=None,
                        refresh_token=env_refresh_token,
                        token_uri='https://oauth2.googleapis.com/token',
                        client_id=env_client_id,
                        client_secret=env_client_secret,
                        scopes=SCOPES
                    )
                    creds.refresh(Request())
                    self._log('SUCCESS', '環境変数からの認証成功')
                    self._check_token_expiry(creds)
                except Exception as e:
                    self._log('ERROR', f'環境変数からの認証失敗: {e}')
                    self._log('INFO', 'ファイルベース認証にフォールバック')
                    creds = None

            # === STEP 1: token.jsonの読み込み（フォールバック） ===
            if not creds and os.path.exists(TOKEN_FILE):
                self._log('INFO', f'既存のトークンを読み込み: {TOKEN_FILE}')
                try:
                    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
                    self._log('SUCCESS', 'トークン読み込み成功')
                    self._check_token_expiry(creds)
                except Exception as e:
                    self._log('ERROR', f'トークン読み込み失敗: {e}')
                    self._log('WARNING', 'token.jsonが破損している可能性があります')
                    creds = None
            else:
                self._log('WARNING', f'{TOKEN_FILE}が見つかりません（初回認証が必要）')

            # === STEP 2: 認証情報の検証と更新 ===
            if not creds:
                self._log('INFO', '認証情報がありません → 新規認証を開始')
            elif creds.valid:
                self._log('SUCCESS', '認証情報は有効です（リフレッシュ不要）')
            elif creds.expired:
                self._log('WARNING', 'アクセストークンが期限切れです')

                if creds.refresh_token:
                    self._log('INFO', 'リフレッシュトークンで更新を試みます')

                    # リトライ機能付きリフレッシュ
                    if not self._refresh_token_with_retry(creds):
                        self._log('ERROR', 'トークンリフレッシュ失敗 → 再認証が必要')
                        creds = None  # 再認証フローへ
                else:
                    self._log('ERROR', 'リフレッシュトークンがありません → 再認証が必要')
                    creds = None
            else:
                self._log('WARNING', '認証情報が無効です → 再認証が必要')
                creds = None

            # === STEP 3: 新規認証（必要な場合のみ） ===
            if not creds or not creds.valid:
                if not os.path.exists(self.client_secrets_file):
                    self._log('ERROR', f'{self.client_secrets_file}が見つかりません')
                    self._log('ERROR', 'Google Cloud Consoleから client_secrets.json をダウンロードしてください')
                    return None

                self._log('INFO', '新規OAuth2認証を開始します')
                self._log('INFO', 'ブラウザで認証画面が開きます...')

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.client_secrets_file,
                        SCOPES
                    )
                    creds = flow.run_local_server(port=0, open_browser=True)
                    self._log('SUCCESS', '新規認証成功')

                    # トークンを保存
                    self._save_token(creds)

                except Exception as e:
                    self._log('ERROR', f'新規認証失敗: {e}')
                    return None

            # === STEP 4: YouTube APIサービスの構築 ===
            try:
                youtube = build('youtube', 'v3', credentials=creds)
                self._log('SUCCESS', 'YouTube APIサービス初期化成功')
                return youtube
            except Exception as e:
                self._log('ERROR', f'YouTube APIサービス構築失敗: {e}')
                return None

        except Exception as e:
            self._log('ERROR', f'予期しないエラー: {e}')
            import traceback
            traceback.print_exc()
            return None

    def upload_video(self, file_path, title, description, category_id="27", tags=None):
        """動画をYouTubeにアップロードする"""
        if not self.youtube:
            self._log('ERROR', 'YouTubeサービスが初期化されていません')
            return None

        try:
            # ファイル存在チェック
            if not os.path.exists(file_path):
                self._log('ERROR', f'動画ファイルが存在しません: {file_path}')
                return None

            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags or ["年金", "ニュース", "自動生成"],
                    'categoryId': category_id
                },
                'status': {
                    'privacyStatus': 'public',
                    'selfDeclaredMadeForKids': False,
                }
            }

            media = MediaFileUpload(file_path, chunksize=-1, resumable=True)

            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )

            self._log('INFO', f'YouTubeアップロード開始: {title}')
            response = None
            retry_count = 0
            max_retries = 3

            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        self._log('INFO', f'アップロード進行中: {progress}%')
                except Exception as chunk_error:
                    retry_count += 1
                    if retry_count > max_retries:
                        raise
                    self._log('WARNING', f'アップロード中断 (リトライ {retry_count}/{max_retries}): {chunk_error}')
                    time.sleep(5 * retry_count)

            video_id = response.get('id')
            self._log('SUCCESS', f'アップロード完了 | 動画ID: {video_id}')
            return video_id

        except Exception as e:
            self._log('ERROR', f'アップロード失敗: {type(e).__name__} - {e}')
            return None

    def post_comment(self, video_id, text):
        """動画にコメントを投稿する"""
        if not self.youtube:
            self._log('ERROR', 'YouTubeサービスが初期化されていません')
            return None

        try:
            body = {
                'snippet': {
                    'videoId': video_id,
                    'topLevelComment': {
                        'snippet': {
                            'textOriginal': text
                        }
                    }
                }
            }
            request = self.youtube.commentThreads().insert(
                part='snippet',
                body=body
            )
            response = request.execute()
            comment_id = response['id']
            self._log('SUCCESS', f'初コメント投稿成功 | コメントID: {comment_id}')
            return comment_id
        except Exception as e:
            self._log('ERROR', f'コメント投稿失敗: {e}')
            return None

    def add_video_to_playlist(self, playlist_id, video_id):
        """再生リストに動画を追加"""
        if not self.youtube:
            self._log('ERROR', 'YouTubeサービスが初期化されていません')
            return None

        try:
            request = self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id
                        }
                    }
                }
            )
            response = request.execute()
            self._log('SUCCESS', f'再生リスト追加成功: {playlist_id}')
            return response
        except Exception as e:
            self._log('ERROR', f'再生リスト追加失敗 ({playlist_id}): {e}')
            return None

    def set_thumbnail(self, video_id, thumbnail_path):
        """動画にサムネイルを設定する"""
        if not self.youtube:
            self._log('ERROR', 'YouTubeサービスが初期化されていません')
            return None

        try:
            media = MediaFileUpload(thumbnail_path, mimetype='image/png', resumable=True)
            request = self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=media
            )
            response = request.execute()
            self._log('SUCCESS', f'サムネイル設定成功: {video_id}')
            return response
        except Exception as e:
            self._log('ERROR', f'サムネイル設定失敗: {e}')
            return None

    def get_video_count(self):
        """チャンネルの公開動画数を取得してエピソード番号に使う"""
        if not self.youtube:
            self._log('WARNING', 'YouTubeサービス未初期化のため動画数取得スキップ')
            return 0
        try:
            response = self.youtube.channels().list(
                part="statistics",
                mine=True
            ).execute()
            if response.get('items'):
                count = int(response['items'][0]['statistics'].get('videoCount', 0))
                self._log('INFO', f'チャンネル動画数: {count}本')
                return count
            self._log('WARNING', 'チャンネル情報取得失敗')
            return 0
        except Exception as e:
            self._log('WARNING', f'動画数取得失敗: {e}')
            return 0

if __name__ == "__main__":
    # テスト実行
    print("=== YouTube Uploader 完璧版 テスト ===")
    uploader = YouTubeUploader()
    if uploader.youtube:
        print("\n[OK] 認証成功！YouTubeサービスが利用可能です")
    else:
        print("\n[ERR] 認証失敗")
