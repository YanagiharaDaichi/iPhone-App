/**
 * 長辺が maxDimension ピクセル以下になるよう縮小して JPEG にし、base64 で返す。
 * Vision API のリクエストサイズ上限に収め、通信量も抑えるため。
 * @param {Blob} file
 */
export async function toJpegBase64(file, { maxDimension = 1600, quality = 0.8 } = {}) {
  const url = URL.createObjectURL(file);
  try {
    const image = await loadImage(url);
    // naturalWidth / naturalHeight と drawImage は写真の向き(EXIF)を反映済み。
    const ratio = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * ratio));
    const height = Math.max(1, Math.round(image.naturalHeight * ratio));

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    // 透過 PNG が黒くならないよう白で塗ってから描く。
    context.fillStyle = '#fff';
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);

    const dataUrl = canvas.toDataURL('image/jpeg', quality);
    return dataUrl.slice(dataUrl.indexOf(',') + 1);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () =>
      reject(new Error('画像を読み込めませんでした。JPEG や PNG などの画像でお試しください。'));
    image.src = src;
  });
}
