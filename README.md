# 類似画像検索 (ImageSearch)

写真を選ぶ(または撮影する)と、その画像に似た画像や、同じ画像が掲載されているウェブページをネット上から探す iPhone アプリです。
検索には [Google Cloud Vision API の Web 検出](https://cloud.google.com/vision/docs/detecting-web) を使っています。

## 機能

- フォトライブラリから画像を選ぶ / カメラで撮影する → 自動で検索
- 検索結果
  - **キーワード**: 画像から推定された名前や関連語(タップすると Google 画像検索)
  - **類似画像**: 見た目が似ている画像
  - **同じ画像**: 完全一致・部分一致する画像
  - **この画像が掲載されているページ**: 同じ画像を使っているウェブページ
- 結果をタップするとアプリ内ブラウザで開く
- API キーは端末のキーチェーンに保存

## 必要なもの

- Xcode 16 以降
- iOS 17 以降
- Google Cloud のアカウントと、Cloud Vision API の API キー

## セットアップ

### 1. API キーを用意する

1. [Google Cloud コンソール](https://console.cloud.google.com/) でプロジェクトを作成し、課金を有効にする
2. [Cloud Vision API](https://console.cloud.google.com/apis/library/vision.googleapis.com) を有効にする
3. [認証情報](https://console.cloud.google.com/apis/credentials) で API キーを作成する
4. (推奨)作成したキーに制限をかける
   - **アプリケーションの制限**: 「iOS アプリ」を選び、バンドル ID `com.yanagiharadaichi.ImageSearch` を登録
   - **API の制限**: 「Cloud Vision API」のみに制限

Web 検出は毎月 1,000 回まで無料で、それを超えると有料です。詳しくは [料金ページ](https://cloud.google.com/vision/pricing) を確認してください。

### 2. アプリを実行する

1. `ImageSearch.xcodeproj` を Xcode で開く
2. 実機で動かす場合は、ターゲット「ImageSearch」の **Signing & Capabilities** で自分の Team を選ぶ
   (バンドル ID が重複してエラーになる場合は変更し、API キーの制限に登録したものも合わせて変更する)
3. 実行(⌘R)
4. 右上の歯車から API キーを貼り付けて保存する

## 構成

```
ImageSearch/
├── ImageSearchApp.swift          アプリのエントリーポイント
├── Models/WebDetection.swift     Vision API の検索結果
├── Services/
│   ├── VisionAPIClient.swift     Vision API へのリクエストと応答の解析
│   └── APIKeyStore.swift         API キーのキーチェーン保存
├── ViewModels/SearchViewModel.swift  画像の読み込みと検索の状態管理
├── Views/
│   ├── ContentView.swift         メイン画面(画像の選択・撮影)
│   ├── ResultsView.swift         検索結果
│   ├── SettingsView.swift        API キーの設定
│   ├── RemoteThumbnail.swift     ネット上の画像のサムネイル
│   ├── CameraPicker.swift        カメラ
│   └── SafariView.swift          アプリ内ブラウザ
└── Utilities/                    画像の縮小、URL・HTML の補助
ImageSearchTests/                 ユニットテスト(⌘U で実行)
```

画像は長辺 1600px の JPEG に縮小してから送信します。

## 補足

- API キーはアプリ内(キーチェーン)に保存され、端末から直接 Google に送信されます。個人利用には十分ですが、App Store で公開する場合はキーをサーバー側に置き、アプリからは自前のサーバーを経由する構成にしてください。
- App Transport Security のため、`http://` の画像サムネイルは `https://` に置き換えて読み込みます。https に対応していないサイトの画像はアイコン表示になりますが、タップすれば元の画像を開けます。
