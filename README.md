# ローカルLLM（iPhone-App）

iPhone の中だけで動く AI チャットアプリです。モデルを一度ダウンロードすれば、あとは**通信なし（機内モードでも）**で会話でき、会話内容が外部に送られることはありません。

使い方は 2 通りあります。

| | Web 版（ホーム画面に追加） | ネイティブ版（Xcode でインストール） |
| --- | --- | --- |
| 必要なもの | **iPhone だけ**（無料） | Mac + Xcode（無料の Apple ID で可） |
| インストール | Safari で開いて「ホーム画面に追加」 | Mac から iPhone に転送。無料アカウントは 7 日ごとに再インストール |
| 使えるモデル | 0.2〜0.7GB の小型モデル（Safari のメモリ制限のため） | 1〜2.3GB のモデル（より賢い）、Apple Intelligence |
| ソース | [`web/`](web/) | [`LocalLLM/`](LocalLLM/) |

## Web 版：iPhone だけで使う

**URL: https://yanagiharadaichi.github.io/iPhone-App/**

1. iPhone の **Safari** で上の URL を開きます。
2. 画面下の共有ボタン（□↑）→ **「ホーム画面に追加」** → 「追加」。
3. ホーム画面にできた **「ローカルLLM」** アイコンから開きます（全画面のアプリとして動きます）。
4. 「モデルを選ぶ」→ **Sarashina2.2 0.5B（おすすめ）** をタップしてダウンロード（約 440MB、Wi-Fi 推奨。完了までアプリを開いたままに）。
5. 準備ができたら話しかけるだけ。2 回目以降は通信なし・機内モードでも使えます。

- **iOS 26 以降を推奨**します。Safari の WebGPU で iPhone の GPU を使って高速に動きます（iOS 18 以前は CPU で動くため遅くなります）。
- Safari は 1 つのページが使えるメモリが少ないため、小型モデルのみ用意しています。アプリが落ちる場合は、設定の「会話の記憶の長さ」を「短い」にするか、**LFM2.5 350M** を選んでください。次に開いたとき、アプリが原因を案内します。
- ダウンロードしたモデルは、ホーム画面のアプリ専用の保存領域に入ります。アイコンを削除するとモデルや会話も消えます。

| モデル | サイズ | 特徴 |
| --- | --- | --- |
| Sarashina2.2 0.5B | 約 440MB | **おすすめ**。日本語特化（SB Intuitions）。正確で自然な日本語 |
| LFM2.5 1.2B JP | 約 700MB | 一番賢い日本語特化モデル。大きめなので新しい iPhone 向け（落ちる場合あり） |
| LFM2.5 350M | 約 230MB | 最軽量・最速。まず動作を試すときに |
| Qwen3 0.6B | 約 400MB | 思考モード対応。日本語の正確さは控えめ |

どれも小型のため、ネイティブ版のモデルより間違いが多めです（特に事実関係）。重要な内容は確認してください。

エンジンは [wllama](https://github.com/ngxson/wllama)（llama.cpp の WebAssembly/WebGPU 版）です。`web/vendor/` に同梱しているため、外部の CDN には依存しません（変更点は `web/vendor/wllama-3.8.1/PATCHES.md`）。

#### 公開の仕組み

`web/` フォルダがそのまま Web アプリです（ビルド不要の静的ファイル）。その中身だけを `gh-pages` ブランチに置き、GitHub Pages（**Settings → Pages → Deploy from a branch → `gh-pages` / `(root)`**）で配信しています。`web/` を変更したら、次のコマンドで公開内容を更新します。

```sh
git subtree split --prefix web -b gh-pages && git push origin gh-pages
```

手元で試すには `python3 -m http.server -d web 8000` を実行し、http://localhost:8000 を開きます。

---

## ネイティブ版（Mac がある場合）

- **MLX（Apple 製の機械学習フレームワーク）**で、Hugging Face の量子化モデル（Qwen3、Gemma 3 など）を iPhone の GPU で実行
- **Apple Intelligence**（iOS 26 以降の対応機種）の内蔵モデルにも切り替え可能（ダウンロード不要）
- 応答のストリーミング表示、停止、思考モード（Qwen 系）、システムプロンプト・温度などの設定
- 好きな MLX モデルを Hugging Face の ID で追加可能

### 動作環境

| 項目 | 要件 |
| --- | --- |
| ビルド | Mac + **Xcode 26 以降** |
| 実行 | **iOS 17 以降の実機 iPhone**（シミュレーターは MLX が GPU を使えないため非対応） |
| 推奨機種 | iPhone 12 以降。4B クラスのモデルは iPhone 15 Pro 以降（メモリ 8GB）推奨 |
| Apple Intelligence | iOS 26 以降 + Apple Intelligence 対応機種（iPhone 15 Pro 以降）で、設定から有効化が必要 |

### iPhone へのインストール手順

1. このリポジトリを Mac にクローンし、`LocalLLM.xcodeproj` を Xcode で開きます。
   初回は Swift パッケージ（mlx-swift-lm など）の取得に数分かかります。
2. 左のナビゲーターで **LocalLLM** プロジェクト → ターゲット **LocalLLM** → **Signing & Capabilities** を開き、
   - **Team** に自分の Apple ID（無料の Personal Team でも可）を選択
   - 必要なら **Bundle Identifier** を自分だけの値（例: `com.あなたの名前.LocalLLM`）に変更
3. iPhone を Mac に接続し、iPhone 側で **設定 → プライバシーとセキュリティ → デベロッパモード** をオンにします。
4. Xcode 上部の実行先で自分の iPhone を選び、**▶︎（Run）** を押します。
   - 実行スキームは高速化のため **Release** ビルドに設定済みです（Debug だと推論がかなり遅くなります）。
5. 初回起動時に iPhone で「信頼されていないデベロッパ」と出た場合は、
   **設定 → 一般 → VPN とデバイス管理** で自分の Apple ID を信頼してください。

> 無料の Apple ID で署名したアプリは 7 日間で期限切れになります。期限が切れたら Xcode から再度 Run してください。

### 使い方

1. 画面上部の「モデルを選択」をタップし、モデルを選びます（初回はダウンロード。Wi-Fi 推奨、完了までアプリを開いたままに）。
2. ダウンロード後は自動で読み込まれ、メッセージを送ると端末内で応答が生成されます。
3. 一度使ったモデルは次回起動時に自動で読み込まれます（通信不要）。
4. 右上の設定から、システムプロンプト・温度・最大応答長・思考モードを変更できます。
5. 不要になったモデルは、モデル一覧で左スワイプして削除できます。

#### 収録モデル

| モデル | サイズ | 目安メモリ | 特徴 |
| --- | --- | --- | --- |
| Qwen3 1.7B（4bit） | 約 1.0GB | 6GB〜 | **おすすめ**。日本語が自然で速さと品質のバランスが良い。思考モード対応 |
| Qwen3.5 2B（4bit） | 約 1.7GB | 6GB〜 | 新しい世代の小型モデル。思考モード対応 |
| Qwen3 4B（4bit） | 約 2.3GB | 8GB〜 | 高品質。iPhone 15 Pro 以降向け |
| Gemma 3 1B（QAT 4bit） | 約 0.8GB | 4GB〜 | 軽量・高速 |
| Qwen3 0.6B（4bit） | 約 0.35GB | 4GB〜 | 最軽量。動作確認や古い機種向け |

「その他のモデル」欄に `mlx-community/Llama-3.2-3B-Instruct-4bit` のような Hugging Face の MLX 形式モデル ID を入力すると、ほかのモデルも試せます（テキストモデルのみ。4bit で 3B 以下が目安）。

### トラブルシューティング

- **署名エラーで「Increased Memory Limit」が使えないと表示される**
  大きめのモデルを動かすために `Config/LocalLLM.entitlements` で
  `com.apple.developer.kernel.increased-memory-limit` を有効にしています。お使いのアカウントで使えない場合は、
  Signing & Capabilities から **Increased Memory Limit** を削除してください（1〜2B クラスのモデルなら動作します）。
- **モデル読み込み中や生成中にアプリが落ちる**
  メモリ不足です。より小さいモデル（Gemma 3 1B / Qwen3 0.6B）を選ぶか、ほかのアプリを終了してから試してください。
- **ダウンロードが進まない・失敗する**
  通信環境を確認し、モデル一覧から同じモデルをもう一度選んで再試行してください。

### 構成

```
LocalLLM/
├── App/LocalLLMApp.swift          # エントリポイント
├── Models/                        # メッセージ・設定・モデル一覧（ModelCatalog）
├── Services/
│   ├── MLXEngine.swift            # MLX でモデルを読み込み・生成（mlx-swift-lm の ChatSession）
│   ├── AppleIntelligenceEngine.swift  # FoundationModels（iOS 26+）
│   ├── HubIntegration.swift       # Hugging Face ダウンローダ／トークナイザの接続
│   └── ModelStorage.swift         # 保存先（Application Support、iCloud バックアップ対象外）と削除
├── ViewModels/ChatStore.swift     # 画面の状態管理（読み込み・会話・停止）
└── Views/                         # SwiftUI 画面（チャット・モデル一覧・設定）
```

主な依存パッケージ: [mlx-swift-lm](https://github.com/ml-explore/mlx-swift-lm)、[mlx-swift](https://github.com/ml-explore/mlx-swift)、
[swift-huggingface](https://github.com/huggingface/swift-huggingface)、[swift-transformers](https://github.com/huggingface/swift-transformers)

GitHub Actions（`.github/workflows/build.yml`）で、push ごとに署名なしの iOS ビルドが通ることを確認しています。
