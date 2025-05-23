"""
Spotify認証モジュール

Spotifyの認証フローを管理するためのクラスを提供します。
- 認証URLの生成
- コールバック処理
- トークンリフレッシュ
- アカウント接続解除
- 認証状態の管理
"""

import os
import time
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from .token_manager import TokenManager
from .cache_manager import CacheManager

logger = logging.getLogger(__name__)

class SpotifyAuth:
    """Spotify認証フローを管理するクラス"""

    # Spotifyの認証に必要なスコープのリスト
    # すべての機能を使用するために必要なスコープを設定
    SCOPES = [
        "user-library-read",          # ライブラリ情報読み取り
        "playlist-read-private",      # プライベートプレイリスト読み取り
        "playlist-read-collaborative", # コラボプレイリスト読み取り
        "playlist-modify-private",    # プライベートプレイリスト変更
        "playlist-modify-public",     # 公開プレイリスト変更
        "user-read-playback-state",   # 再生状態読み取り
        "user-modify-playback-state", # 再生状態変更
        "user-read-currently-playing", # 現在再生中の曲読み取り
        "user-read-recently-played",  # 最近再生した曲読み取り
        "user-top-read",              # トップアイテム読み取り
        "user-follow-read",           # フォロー中アーティスト読み取り
        "user-follow-modify",         # アーティストフォロー/解除
    ]

    def __init__(self, client_id=None, client_secret=None, redirect_uri=None, token_path=None, cache_path=None):
        """SpotifyAuthの初期化

        Args:
            client_id (str, optional): Spotify APIのクライアントID。指定がない場合は環境変数から取得。
            client_secret (str, optional): Spotify APIのクライアントシークレット。指定がない場合は環境変数から取得。
            redirect_uri (str, optional): 認証後のリダイレクトURI。指定がない場合は環境変数から取得。
            token_path (str, optional): トークンを保存するディレクトリパス。
            cache_path (str, optional): キャッシュを保存するディレクトリパス。
        """
        # 環境変数から認証情報を取得（指定がない場合）
        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback")
        
        # 必須の認証情報が欠けている場合はエラー
        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            missing = []
            if not self.client_id:
                missing.append("SPOTIFY_CLIENT_ID")
            if not self.client_secret:
                missing.append("SPOTIFY_CLIENT_SECRET")
            if not self.redirect_uri:
                missing.append("SPOTIFY_REDIRECT_URI")
            raise ValueError(f"認証情報が不足しています: {', '.join(missing)}")
        
        # TokenManagerとCacheManagerの初期化
        self.token_manager = TokenManager(token_path)
        self.cache_manager = CacheManager(cache_path)
        
        # SpotifyOAuthオブジェクトの作成
        self.oauth = SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=" ".join(self.SCOPES),
            cache_path=None,  # 独自のトークン管理を使用するためNone
            show_dialog=True  # 常にユーザーに認証ダイアログを表示
        )
        
        # 認証状態を管理するフラグ
        self._authenticated = False
        self._token_info = None
        
        # 保存されたトークンがあれば読み込み
        self._load_saved_token()

    def _load_saved_token(self):
        """保存されたトークン情報を読み込む"""
        token_info = self.token_manager.load_token()
        if token_info:
            # トークンの有効期限をチェック
            if self._is_token_expired(token_info):
                logger.info("保存されたトークンの期限が切れています。リフレッシュを試みます。")
                try:
                    token_info = self.refresh_token(token_info)
                except Exception as e:
                    logger.error(f"トークンのリフレッシュに失敗しました: {e}")
                    token_info = None
            
            if token_info:
                self._token_info = token_info
                self._authenticated = True
                logger.info("保存されたトークンを読み込みました。認証済み状態です。")
            else:
                logger.warning("有効なトークンがありません。再認証が必要です。")
        else:
            logger.info("保存されたトークンがありません。認証が必要です。")

    def _is_token_expired(self, token_info):
        """トークンが期限切れかどうかを判断

        Args:
            token_info (dict): トークン情報

        Returns:
            bool: トークンが期限切れの場合はTrue
        """
        now = int(time.time())
        return token_info["expires_at"] - now < 60  # 残り60秒未満は期限切れと見なす

    def get_auth_url(self):
        """認証URLを生成

        Returns:
            str: ユーザーがSpotify認証を行うためのURL
        """
        auth_url = self.oauth.get_authorize_url()
        logger.info(f"認証URLを生成しました: {auth_url}")
        return auth_url

    def handle_callback(self, code):
        """認証コールバックを処理

        Args:
            code (str): Spotifyから返されたauthorization code

        Returns:
            bool: 認証成功時にTrue、失敗時にFalse
        """
        try:
            # codeからアクセストークンを取得
            token_info = self.oauth.get_access_token(code, as_dict=True)
            
            # トークン情報を保存
            self.token_manager.save_token(token_info)
            
            # 認証状態を更新
            self._token_info = token_info
            self._authenticated = True
            
            logger.info("認証コールバックを正常に処理しました。トークンを保存しました。")
            return True
        except Exception as e:
            logger.error(f"認証コールバックの処理中にエラーが発生しました: {e}")
            self._authenticated = False
            self._token_info = None
            return False

    def refresh_token(self, token_info=None):
        """アクセストークンをリフレッシュ

        Args:
            token_info (dict, optional): リフレッシュするトークン情報。
                                        指定がない場合は内部に保存されたトークンを使用。

        Returns:
            dict or None: 新しいトークン情報。失敗した場合はNone
        """
        token_to_refresh = token_info or self._token_info
        
        if not token_to_refresh or "refresh_token" not in token_to_refresh:
            logger.error("リフレッシュトークンがありません。再認証が必要です。")
            self._authenticated = False
            self._token_info = None
            return None
        
        try:
            # リフレッシュトークンを使って新しいアクセストークンを取得
            refresh_token = token_to_refresh["refresh_token"]
            new_token = self.oauth.refresh_access_token(refresh_token)
            
            # 新しいトークン情報を保存
            self.token_manager.save_token(new_token)
            
            # 認証状態を更新
            self._token_info = new_token
            self._authenticated = True
            
            logger.info("トークンを正常にリフレッシュしました。")
            return new_token
        except Exception as e:
            logger.error(f"トークンのリフレッシュ中にエラーが発生しました: {e}")
            self._authenticated = False
            self._token_info = None
            return None

    def get_token(self):
        """現在のアクセストークンを取得

        Returns:
            str or None: 有効なアクセストークン。認証されていない場合はNone
        """
        if not self._authenticated or not self._token_info:
            logger.warning("認証されていないか、トークン情報がありません。")
            return None
        
        # トークンの期限が切れていればリフレッシュ
        if self._is_token_expired(self._token_info):
            logger.info("トークンの期限が切れています。リフレッシュします。")
            try:
                self._token_info = self.refresh_token()
                if not self._token_info:
                    logger.error("トークンのリフレッシュに失敗しました。")
                    return None
            except Exception as e:
                logger.error(f"トークンのリフレッシュ中にエラーが発生しました: {e}")
                return None
        
        return self._token_info["access_token"]

    def get_spotify_client(self):
        """認証済みのSpotifyクライアントを取得

        Returns:
            spotipy.Spotify or None: 認証済みのSpotifyクライアント。認証されていない場合はNone
        """
        token = self.get_token()
        if not token:
            logger.warning("有効なトークンがありません。Spotifyクライアントを作成できません。")
            return None
        
        return spotipy.Spotify(auth=token)

    def is_authenticated(self):
        """現在の認証状態を取得

        Returns:
            bool: 認証済みの場合はTrue
        """
        # トークンがあり、期限切れでなければ認証済み
        if self._authenticated and self._token_info:
            if not self._is_token_expired(self._token_info):
                return True
            
            # トークンが期限切れならリフレッシュを試みる
            logger.info("トークンの期限が切れています。リフレッシュを試みます。")
            try:
                self._token_info = self.refresh_token()
                return self._token_info is not None
            except Exception as e:
                logger.error(f"トークンのリフレッシュ中にエラーが発生しました: {e}")
                self._authenticated = False
                return False
        
        return False

    def disconnect(self):
        """Spotifyアカウントとの接続を解除"""
        try:
            # トークンファイルを削除
            self.token_manager.delete_token()
            
            # キャッシュをクリア
            self.cache_manager.clear_all_cache()
            
            # 認証状態をリセット
            self._authenticated = False
            self._token_info = None
            
            logger.info("Spotifyアカウントとの接続を解除しました。")
            return True
        except Exception as e:
            logger.error(f"アカウント接続解除中にエラーが発生しました: {e}")
            return False

    def clear_cache(self):
        """認証関連キャッシュをクリア"""
        try:
            # キャッシュをクリア
            self.cache_manager.clear_all_cache()
            logger.info("認証関連キャッシュをクリアしました。")
            return True
        except Exception as e:
            logger.error(f"キャッシュクリア中にエラーが発生しました: {e}")
            return False 