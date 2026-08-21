# SEO Automation - Search Console Analysis System

Google Search Console の自動分析システム。エラー監視、ランキング低下検出、リライト候補の自動生成を毎日・毎週・毎月で実行します。

## 📋 機能

### 1. エラー監視 (Daily)
- **実行時間**: 毎日 09:00 JST
- **処理**: Search Console のクロールエラー・インデックスエラーを監視
- **出力先**: Google Sheets (GID: 0)
- **ファイル**: `error_monitoring.py`

**記録される情報:**
- タイムスタンプ
- エラータイプ (Crawl Error / Indexing Issue)
- エラーカテゴリ
- 発生数
- 対応状況

### 2. 低下キーワード検出 (Weekly)
- **実行時間**: 毎週金曜 18:00 JST
- **処理**: 前週比でランキングが5位以上低下したキーワードを検出
- **出力先**: Google Sheets (GID: 953824174)
- **ファイル**: `low_ranking_detector.py`

**検出条件:**
- 位置が5位以上低下
- インプレッション数が10以上
- 前週・当週の両方にデータあり

**記録される情報:**
- キーワード
- 前週の位置
- 今週の位置
- 位置の変化
- インプレッション数
- クリック数
- CTR

### 3. リライト候補生成 (Monthly)
- **実行時間**: 毎月末 18:00 JST (月初 09:00 UTC で実行)
- **処理**: リライト優先度付けリストを自動生成
- **出力先**: Google Sheets (GID: 1901160298)
- **ファイル**: `rewrite_candidates.py`

**選定基準:**
- ランキング位置: 31位以下
- インプレッション数: 10以上
- CTR: 1.0% 未満

**優先度算出:**
- 位置スコア (30位に近い = 高優先度): 30%
- インプレッションスコア (多い = 高優先度): 40%
- CTR スコア (低い = 高優先度): 30%

## 🚀 セットアップ

### 前提条件
- Python 3.10以上
- Google Cloud プロジェクト (Search Console API, Sheets API 有効)
- サービスアカウント (JSON キー)
- GitHub リポジトリ

### 1. ローカル環境設定

```bash
# リポジトリをクローン
git clone https://github.com/junjiogi-droid/seo-automation.git
cd seo-automation

# 仮想環境を作成 (オプション)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# または
venv\Scripts\activate  # Windows

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 2. Google 認証情報の設定

#### ローカル実行の場合:
```bash
# サービスアカウント JSON を配置
cp /path/to/service-account.json ./service-account.json
```

#### GitHub Actions の場合:
```bash
# GitHub リポジトリの Settings → Secrets and variables → Actions
# 新しい Secret を追加:
# Name: GOOGLE_CREDENTIALS
# Value: サービスアカウント JSON の内容全体をコピペ
```

### 3. Google Sheets の準備

必要なシートを作成してください:

#### シート1: エラー監視 (GID: 0)
