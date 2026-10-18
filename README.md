# 類似画像検索

画像をアップロードすると、その画像に似た画像や、同じ画像が掲載されているウェブページをネット上から探す Web アプリです。
検索には [Google Cloud Vision API の Web 検出](https://cloud.google.com/vision/docs/detecting-web) を使っています。

サーバーは不要で、HTML / CSS / JavaScript だけで動きます(ビルドも不要)。iPhone の Safari でも PC のブラウザでも使えます。

## 機能

- 画像の入力: 写真を選ぶ / 撮影する(スマートフォン) / ドラッグ&ドロップ / 貼り付け(Ctrl+V・⌘V)
- 検索結果
  - **同じ画像が見つかったサイト**: 同じ画像が載っているページの一覧。タップするとそのページが開く。
    「完全一致」(同じ画像)のサイトを先に、「一部一致」(切り抜き・加工された画像)をその後に並べる
  - **キーワード**: 画像から推定された名前や関連語(クリックで Google 画像検索)
  - **類似画像**: 見た目が似ている画像
  - **その他の同じ画像**: 掲載ページが分からなかった同じ画像
- ダークモード対応

## 使い方

1. ページを開く
2. 右上の歯車から Google Cloud Vision API の API キーを貼り付けて保存する
3. 「写真を選ぶ」で画像を選ぶと、自動で検索される

## API キーを用意する

1. [Google Cloud コンソール](https://console.cloud.google.com/) でプロジェクトを作成し、課金を有効にする
2. [Cloud Vision API](https://console.cloud.google.com/apis/library/vision.googleapis.com) を有効にする
3. [認証情報](https://console.cloud.google.com/apis/credentials) で「API キー」を作成する
4. (推奨)作成したキーに制限をかける
   - **アプリケーションの制限**: 「ウェブサイト」を選び、公開するページのアドレスを登録する
     (例: `https://yanagiharadaichi.github.io/*`。手元で試すなら `http://localhost:8000/*` も)
   - **API の制限**: 「Cloud Vision API」のみに制限

Web 検出は毎月 1,000 回まで無料で、それを超えると有料です。詳しくは [料金ページ](https://cloud.google.com/vision/pricing) を確認してください。

## 公開する(GitHub Pages)

1. GitHub のリポジトリで **Settings → Pages** を開く
2. **Source** を「Deploy from a branch」にし、ブランチ(例: `main`)と `/ (root)` を選んで保存する
3. 数分後に `https://yanagiharadaichi.github.io/iPhone-App/` で開けるようになる

非公開リポジトリで GitHub Pages を使うには有料プランが必要です。Netlify や Cloudflare Pages など、静的サイトを置ける場所ならどこでも動きます。

## 手元で動かす

```sh
npm start   # = python3 -m http.server 8000
```

ブラウザで http://localhost:8000 を開きます。
JavaScript モジュールを使っているため、`index.html` をファイルとして直接開くと動きません。

## テスト

```sh
npm test
```

Node.js 18 以降が必要です(追加のパッケージは不要)。

## 構成

```
index.html        画面
css/style.css     見た目
js/app.js         画面の操作(画像の入力・結果の表示・設定)
js/vision.js      Vision API へのリクエストと応答の解析
js/image.js       送信前の画像の縮小(長辺 1600px の JPEG)
tests/            ユニットテスト
```

## 補足

- API キーはそのブラウザ内(localStorage)にだけ保存され、検索のときにブラウザから Google へ直接送られます。キーをページのコードに書き込むことはありません。
- 検索結果のサムネイルは各サイトから直接読み込みます。直リンク対策で表示されない画像もありますが、クリックすれば元の画像を開けます。
