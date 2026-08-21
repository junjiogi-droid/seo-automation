# セットアップガイド

## 📂 ディレクトリ構成
seo-automation/
├── .github/
│ └── workflows/
│ ├── daily-error-check.yml
│ ├── weekly-ranking-check.yml
│ └── monthly-candidates.yml
├── error_monitoring.py
├── low_ranking_detector.py
├── rewrite_candidates.py
├── requirements.txt
├── README.md
├── SETUP_GUIDE.md (このファイル)
├── .gitignore
└── service-account.json (ローカルのみ)
## 🔑 GitHub Secrets の設定方法

### Step 1: GitHub リポジトリにアクセス

1. https://github.com/junjiogi-droid/seo-automation に移動
2. **Settings** タブをクリック

### Step 2: Secrets を追加

1. 左サイドバーから **Secrets and variables** → **Actions** をクリック
2. **New repository secret** をクリック

### Step 3: GOOGLE_CREDENTIALS を設定

1. **Name** フィールドに `GOOGLE_CREDENTIALS` を入力
2. **Secret** フィールドにサービスアカウント JSON の内容全体をコピペ
   - JSON ファイルを開く
   - すべての内容をコピー
   - Secret フィールドにペースト
3. **Add secret** をクリック

**注意:** JSON 全体が必要です（改行を含む）

## 🔧 Google Cloud セットアップ

### Step 1: Google Cloud プロジェクト作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. **プロジェクトを選択** → **新しいプロジェクト** をクリック
3. プロジェクト名を入力（例: "SEO-Automation"）
4. **作成** をクリック

### Step 2: API 有効化

#### Search Console API を有効化:
1. **API とサービス** → **ライブラリ** をクリック
2. 検索バーで "Search Console API" を検索
3. **有効にする** をクリック

#### Google Sheets API を有効化:
1. **API とサービス** → **ライブラリ** をクリック
2. 検索バーで "Google Sheets API" を検索
3. **有効にする** をクリック

### Step 3: サービスアカウント作成

1. **API とサービス** → **認証情報** をクリック
2. **認証情報を作成** → **サービスアカウント** をクリック
3. 以下を入力:
   - **サービスアカウント名**: seo-automation
   - **説明**: SEO Automation Service Account
4. **作成と続行** をクリック
5. **キーを作成** をクリック
6. **キーのタイプ**: JSON を選択
7. **作成** をクリック
   - JSON ファイルが自動ダウンロードされます

### Step 4: サービスアカウントに権限付与

1. 作成したサービスアカウントメールをコピー
   - 形式: `seo-automation@{project-id}.iam.gserviceaccount.com`
2. [Google Search Console](https://search.google.com/search-console) にアクセス
3. junjiogiso.com のプロパティを選択
4. **設定** → **ユーザーと権限** をクリック
5. **ユーザーを追加** をクリック
6. サービスアカウントメールを入力
7. **Restricted Service Account** または **Full** を選択
8. **招待を送信** をクリック

## 📊 Google Sheets 設定

### Step 1: スプレッドシート作成

1. [Google Sheets](https://docs.google.com/spreadsheets) にアクセス
2. **空白のスプレッドシート** をクリック
3. タイトルを "SEO Automation" に変更

### Step 2: シートの GID を取得

1. スプレッドシートを開く
2. URL から ID を取得:
https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit
例: `1WR8YGvvnOpRBxEgwEGbjCTPkk8kbu67Le8Xg4vrKVXU`

3. 各シートの GID を取得:
   - シートを右クリック
   - **詳細** をクリック
   - 最後の番号が GID です

### Step 3: サービスアカウントを共有

1. スプレッドシート右上の **共有** をクリック
2. サービスアカウントメールを入力:
seo-automation@{project-id}.iam.gserviceaccount.com
3. **編集者** を選択
4. **共有** をクリック

### Step 4: シートのヘッダーを設定

**シート 1: エラー監視 (GID: 0)**
A1: Timestamp
B1: Error Category
C1: Error Type
D1: Count
E1: Status
**シート 2: 低下キーワード (GID: 953824174)**
A1: Timestamp
B1: Query
C1: Previous Position
D1: Current Position
E1: Position Change
F1: Impressions
G1: Clicks
H1: CTR (%)
I1: Status
**シート 3: リライト候補 (GID: 1901160298)**
A1: Timestamp
B1: Query
C1: Page URL
D1: Current Position
E1: Impressions
F1: Clicks
G1: CTR (%)
H1: Priority Level
I1: Priority Score
J1: Reason
K1: Status
## 🚀 デプロイ手順

### Step 1: ローカルテスト（推奨）

```bash
# リポジトリをクローン
git clone https://github.com/junjiogi-droid/seo-automation.git
cd seo-automation

# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Mac/Linux
# または
venv\Scripts\activate  # Windows

# 依存パッケージをインストール
pip install -r requirements.txt

# サービスアカウント JSON を配置
cp ~/Downloads/seo-automation-*.json ./service-account.json

# テスト実行
python error_monitoring.py
python low_ranking_detector.py
python rewrite_candidates.py
```

### Step 2: GitHub にプッシュ

```bash
# ファイルをステージング
git add .

# コミット
git commit -m "Initial setup: SEO automation scripts"

# プッシュ
git push origin main
```

### Step 3: ワークフロー確認

1. GitHub リポジトリの **Actions** タブをクリック
2. ワークフローが表示されることを確認
3. 各ワークフローが「✅ Successful」と表示されるのを待つ

## ✅ 動作確認チェックリスト

- [ ] Google Cloud プロジェクトを作成
- [ ] Search Console API を有効化
- [ ] Google Sheets API を有効化
- [ ] サービスアカウントを作成
- [ ] サービスアカウントに Search Console のアクセス権限を付与
- [ ] Google Sheets スプレッドシートを作成
- [ ] サービスアカウントをスプレッドシートに共有
- [ ] GitHub Secrets に GOOGLE_CREDENTIALS を設定
- [ ] ローカルテストが成功
- [ ] GitHub にプッシュ完了
- [ ] GitHub Actions ワークフローが実行
- [ ] Google Sheets にデータが記録されたことを確認

## 🐛 トラブルシューティング

### エラー: "Permission denied"

**原因:** サービスアカウントに Search Console または Sheets へのアクセス権がない

**解決方法:**
1. サービスアカウントメールをコピー
2. Google Search Console で ユーザーを追加
3. Google Sheets スプレッドシートで 共有を設定

### エラー: "Worksheet not found"

**原因:** GID が正しくない、またはシートが削除されている

**解決方法:**
1. スクリプトの GID 設定を確認
2. Google Sheets で正しいシート数があることを確認
3. シートの右クリック → 詳細 で GID を確認

### エラー: "GOOGLE_CREDENTIALS not found"

**原因:** GitHub Secrets が設定されていない

**解決方法:**
1. GitHub リポジトリ設定を開く
2. Secrets and variables → Actions を確認
3. GOOGLE_CREDENTIALS という名前のシークレットがあるか確認
4. 改行を含む JSON 全体がコピーされているか確認

### エラー: "quota exceeded"

**原因:** API の日次リクエスト制限に達した

**解決方法:**
1. 翌日に自動的にリセット（Google API 配額）
2. 実行スケジュール（cron）を調整
3. Google Cloud Console でクォータを確認

## 📞 サポート

問題が解決しない場合:

1. **GitHub Issues** で報告
2. 以下の情報を含める:
   - エラーメッセージ全文
   - 実行したスクリプト
   - ログの最後の 20 行
   - 環境 (ローカル / GitHub Actions)
   - Python バージョン
   - OS

## 🔐 セキュリティのベストプラクティス

1. **サービスアカウント JSON をコミットしない**
   - `.gitignore` に追加済み

2. **Secrets を安全に管理**
   - GitHub Secrets の使用
   - ローカルテスト時は環境変数で管理

3. **定期的にキーをローテーション**
   - 90 日ごとに新しい JSON キーを生成
   - 古いキーを削除

4. **必要最小限の権限**
   - サービスアカウントは特定のスプレッドシートのみアクセス
   - Search Console では "Restricted Service Account" を推奨
