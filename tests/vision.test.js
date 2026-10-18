import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  buildRequestBody,
  detectWeb,
  ENDPOINT,
  googleImageSearchUrl,
  parseResponse,
  stripHtml,
  toHttps,
  VisionError,
} from '../js/vision.js';

const sampleResponse = {
  responses: [
    {
      webDetection: {
        webEntities: [
          { entityId: '/m/02j81', score: 1.2, description: 'Eiffel Tower' },
          { entityId: '/m/05qtj', score: 0.8 },
          { entityId: '/m/0d05w3', description: 'Paris' },
        ],
        fullMatchingImages: [{ url: 'https://example.com/full.jpg' }],
        partialMatchingImages: [
          { url: 'https://example.com/partial.jpg' },
          { url: 'https://example.com/full.jpg' },
        ],
        pagesWithMatchingImages: [
          {
            url: 'https://example.com/page',
            pageTitle: '<b>Eiffel Tower</b> &amp; Paris',
            partialMatchingImages: [{ url: 'https://example.com/partial.jpg' }],
          },
          {
            url: 'http://travel.example.jp/paris',
            pageTitle: 'パリ旅行',
            fullMatchingImages: [{ url: 'http://travel.example.jp/eiffel.jpg' }],
          },
          { url: 'https://no-image.example.net/', pageTitle: '' },
          { url: 'javascript:alert(1)', pageTitle: 'bad' },
        ],
        visuallySimilarImages: [
          { url: 'https://example.com/similar1.jpg' },
          { url: 'http://example.com/similar2.jpg' },
          { url: 'data:image/png;base64,AAAA' },
        ],
        bestGuessLabels: [{ label: 'eiffel tower', languageCode: 'en' }],
      },
    },
  ],
};

describe('buildRequestBody', () => {
  test('WEB_DETECTION で画像を送るリクエストを作る', () => {
    const body = buildRequestBody('AQID', 10);
    const [request] = body.requests;

    assert.equal(request.image.content, 'AQID');
    assert.deepEqual(request.features, [{ type: 'WEB_DETECTION', maxResults: 10 }]);
  });
});

describe('detectWeb', () => {
  test('API キーをヘッダーに付けて送信する', async () => {
    let captured;
    const fakeFetch = async (url, init) => {
      captured = { url, init };
      return new Response(JSON.stringify(sampleResponse), { status: 200 });
    };

    const result = await detectWeb('AQID', 'test-key', { fetch: fakeFetch });

    assert.equal(captured.url, ENDPOINT);
    assert.equal(captured.init.method, 'POST');
    assert.equal(captured.init.headers['X-Goog-Api-Key'], 'test-key');
    assert.equal(JSON.parse(captured.init.body).requests[0].image.content, 'AQID');
    assert.equal(result.similarImages.length, 2);
  });

  test('API キーがなければ送信せずにエラーにする', async () => {
    let called = false;
    const fakeFetch = async () => {
      called = true;
    };

    await assert.rejects(detectWeb('AQID', '', { fetch: fakeFetch }), { kind: 'missing-key' });
    assert.equal(called, false);
  });

  test('通信できなければネットワークエラーにする', async () => {
    const fakeFetch = async () => {
      throw new TypeError('Failed to fetch');
    };

    await assert.rejects(detectWeb('AQID', 'key', { fetch: fakeFetch }), { kind: 'network' });
  });
});

describe('parseResponse', () => {
  test('検索結果を表示用に整える', () => {
    const result = parseResponse(JSON.stringify(sampleResponse), 200);

    assert.deepEqual(result.keywords, ['eiffel tower', 'Paris']);
    assert.deepEqual(result.similarImages, [
      { url: 'https://example.com/similar1.jpg', thumbnail: 'https://example.com/similar1.jpg' },
      { url: 'http://example.com/similar2.jpg', thumbnail: 'https://example.com/similar2.jpg' },
    ]);
    assert.equal(result.isEmpty, false);
  });

  test('同じ画像が見つかったサイトを、完全一致を先にして並べる', () => {
    const result = parseResponse(JSON.stringify(sampleResponse), 200);

    assert.deepEqual(result.pages, [
      {
        url: 'http://travel.example.jp/paris',
        title: 'パリ旅行',
        host: 'travel.example.jp',
        thumbnail: 'https://travel.example.jp/eiffel.jpg',
        match: 'full',
      },
      {
        url: 'https://example.com/page',
        title: 'Eiffel Tower & Paris',
        host: 'example.com',
        thumbnail: 'https://example.com/partial.jpg',
        match: 'partial',
      },
      {
        url: 'https://no-image.example.net/',
        title: 'no-image.example.net',
        host: 'no-image.example.net',
        thumbnail: null,
        match: null,
      },
    ]);
  });

  test('掲載サイトが分からない同じ画像だけを別に残す', () => {
    const result = parseResponse(JSON.stringify(sampleResponse), 200);

    // partial.jpg は example.com/page に載っているので含めない。
    assert.deepEqual(
      result.otherMatchingImages.map((image) => image.url),
      ['https://example.com/full.jpg'],
    );
  });

  test('何も見つからなければ空の結果にする', () => {
    const result = parseResponse('{"responses": [{}]}', 200);

    assert.equal(result.isEmpty, true);
  });

  test('API キーが無効ならサーバーのメッセージ付きでエラーにする', () => {
    const body = JSON.stringify({
      error: { code: 400, message: 'API key not valid. Please pass a valid API key.', status: 'INVALID_ARGUMENT' },
    });

    assert.throws(() => parseResponse(body, 400), (error) => {
      assert.ok(error instanceof VisionError);
      assert.equal(error.code, 400);
      assert.match(error.message, /API key not valid/);
      return true;
    });
  });

  test('画像ごとのエラーもエラーにする', () => {
    const body = '{"responses": [{"error": {"code": 3, "message": "Bad image data."}}]}';

    assert.throws(() => parseResponse(body, 200), { code: 3, message: '検索に失敗しました(3): Bad image data.' });
  });

  test('JSON 以外のエラー応答はステータスコードでエラーにする', () => {
    assert.throws(() => parseResponse('Service Unavailable', 503), { code: 503 });
  });
});

describe('helpers', () => {
  test('stripHtml はタグと文字参照を取り除く', () => {
    assert.equal(stripHtml('<b>Mount</b> Fuji'), 'Mount Fuji');
    assert.equal(stripHtml('Tom &amp; Jerry &quot;Show&quot; &#39;99'), 'Tom & Jerry "Show" \'99');
    assert.equal(stripHtml('&amp;lt;b&amp;gt;'), '&lt;b&gt;');
  });

  test('toHttps は http を https に置き換える', () => {
    assert.equal(toHttps('http://example.com/a.jpg'), 'https://example.com/a.jpg');
    assert.equal(toHttps('https://example.com/a.jpg'), 'https://example.com/a.jpg');
  });

  test('googleImageSearchUrl はキーワードを含む画像検索 URL を作る', () => {
    const url = new URL(googleImageSearchUrl('富士山'));

    assert.equal(url.hostname, 'www.google.com');
    assert.equal(url.searchParams.get('q'), '富士山');
    assert.equal(url.searchParams.get('tbm'), 'isch');
  });
});
