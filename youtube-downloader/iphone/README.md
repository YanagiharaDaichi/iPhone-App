# iPhone だけで使う版（a-Shell ＋ ショートカット）

PC やサーバーなしで、iPhone だけで YouTube の動画・音声を保存できます。
無料アプリ **a-Shell**（iPhone の中で Python を動かせるアプリ）で、PC 版と同じ yt-dlp を動かします。

**使い方のイメージ**

1. YouTube アプリで動画の「共有」→ 作ったショートカット「YouTube保存」を選ぶ
2. 「動画」か「音声」を選ぶ
3. a-Shell が開いてダウンロード（進み具合が表示されます）
4. 終わるとプレビューが開くので、共有ボタン →「ビデオを保存」で写真アプリへ

## 1. 準備（初回だけ）

1. App Store で **a-Shell** をインストールします（無料）。
2. a-Shell を開き、次の 1 行をそのまま貼り付けて実行します。
   （この README を iPhone の Safari で開き、コードの右上のコピーボタンでコピーすると簡単です）

   ```
   cd && mkdir -p bin && curl -fsSL https://raw.githubusercontent.com/YanagiharaDaichi/iPhone-App/main/youtube-downloader/iphone/ytdl.py -o bin/ytdl && python3 bin/ytdl setup
   ```

   > まだ `main` ブランチに取り込んでいない場合は、URL の `main` を `claude/youtube-downloader` に置き換えてください。

3. 最後に「準備ができました。」と表示されれば完了です（1〜2 分かかります）。

## 2. ショートカットを作る（初回だけ）

iOS のバージョンによって、表示が少し違うことがあります。

1. 「ショートカット」アプリを開き、右上の **＋** をタップします。
2. 上部の名前をタップ →「名称変更」で **YouTube保存** にします。
3. 画面下の **ⓘ**（詳細）をタップ →「**共有シートに表示**」をオン →「完了」。
4. 先頭に「共有シートから … を受け取る」というブロックが出ます。
   - 受け取る種類をタップし、**URL** だけを選びます。
   - 「入力がない場合」は「**クリップボードを取得**」にしておくと、URL をコピーしてからホーム画面やウィジェットからも実行できます。
5. 下の検索欄で「**メニューから選択**」を追加し、項目を「**動画**」と「**音声**」の 2 つにします。
6. 「動画」の下に、a-Shell のアクション **Execute Command** を追加します（検索欄に「a-Shell」と入力すると出てきます）。
   - 「shell command(s)」の欄に次のように入力します。`"` と `"` の間には、キーボードの上に出る変数の一覧から **ショートカットの入力** を入れます。

     ```
     cd && python3 bin/ytdl video "ショートカットの入力"
     ```

   - アクションの **＞** をタップして詳細を開き、「Open the app to execute the commands?」を **yes** にします。
7. 「音声」の下にも同じアクションを追加し、`video` の部分を `audio` にします（MP3 がよければ `mp3`）。
8. 右上の「完了」で保存します。

## 3. 使い方

1. YouTube アプリで動画を開き、「共有」→「その他」→ 一覧の下のほうにある **YouTube保存** をタップします。
2. 「動画」か「音声」を選ぶと、a-Shell が開いてダウンロードが始まります。
   **終わるまで a-Shell の画面を開いたままにしてください**（他のアプリに切り替えると止まることがあります）。
3. 終わるとプレビューが開きます。共有ボタンから
   - 動画: 「**ビデオを保存**」→ 写真アプリに保存
   - 音声: 「**"ファイル"に保存**」→ 好きな場所に保存

保存したファイルは「ファイル」アプリ → **このiPhone内 → a-Shell → YouTube** にも残っています。

### a-Shell で直接使う

YouTube で URL をコピーしてから a-Shell で次のように入力しても使えます（URL を省略するとクリップボードから読みます）。
a-Shell を開いた直後の場所（`[Documents]`）で実行してください。別の場所にいるときは、先に `cd` と入力すると戻れます。

| コマンド | 内容 |
| --- | --- |
| `python3 bin/ytdl video` | 動画（MP4）を保存。1080p まで、iPhone で再生しやすい H.264 を優先 |
| `python3 bin/ytdl video --max 720` | 画質を 720p までにする（ファイルが小さくなる） |
| `python3 bin/ytdl audio` | 音声（M4A）を保存 |
| `python3 bin/ytdl mp3` | 音声（MP3）を保存 |
| `python3 bin/ytdl video URL` | URL を指定して保存 |
| `python3 bin/ytdl clean` | a-Shell に残っている保存済みファイルを削除（容量の節約） |
| `python3 bin/ytdl check` | 動作環境を確認 |
| `python3 bin/ytdl setup` | yt-dlp などを最新版に更新 |

## うまくいかないとき

- **急に保存できなくなった**: YouTube の仕様変更の可能性があります。a-Shell で `python3 bin/ytdl setup` を実行して yt-dlp を最新版にしてください。
- **「ボットと判定されました」と出る**: 時間をおくか、Wi-Fi とモバイル通信を切り替えて試してください。
- **何も起きない / コマンドが見つからない**: a-Shell で `cd` を実行してから `python3 bin/ytdl check` を実行し、足りないものを確認してください。
  「1. 準備」のコマンドをもう一度実行しても構いません。
- **`~` を含むコマンドが「Operation not permitted」などで失敗する**: a-Shell では `~/Documents/...` のような書き方が正しく扱われないことがあります。
  このページのコマンドのように、`cd` で Documents に移動してから `bin/ytdl` のような相対パスで実行してください。
- **スクリプト自体を新しくしたい**: 「1. 準備」のコマンドをもう一度実行します。

## 仕組みと注意点

- 動画の取得には [yt-dlp](https://github.com/yt-dlp/yt-dlp) を使っています。保存先は a-Shell の `Documents/YouTube` です。
- 動画は、写真アプリで確実に再生できる **H.264 ＋ AAC の MP4** を優先して選びます（4K など H.264 がない画質は選びません）。
- YouTube は動画を取り出す前に JavaScript の課題を解く仕組みになっています。iPhone では PC 版のように Deno などを動かせないため、
  `python3 bin/ytdl setup` は iPhone 内蔵の WebKit でこれを解く **非公式のプラグイン（yt-dlp-apple-webkit-jsi）** も入れます。
  - プラグインがなくても動きますが、取得できる形式が少なくなります。入れたくない場合は `python3 bin/ytdl setup --no-webkit` を使い、
    入れた後に外すには a-Shell で `pip uninstall yt-dlp-apple-webkit-jsi` を実行してください。
- 自分で投稿した動画や、権利者がダウンロードを許可している動画に限ってご利用ください。
  違法にアップロードされたものと知りながらダウンロードすることは、私的に使う目的であっても著作権法で禁止されています。
