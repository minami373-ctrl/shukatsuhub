import '@testing-library/jest-dom/vitest'

// jsdom は <dialog> の showModal / close を実装していない（呼ぶと TypeError になる）。
// 開閉は open 属性で表せるので、テスト中だけ最小の実装を足す。
// 実装側（NoteDialog / TaskDialog）にテスト用の分岐を入れないための措置。
const dialog = window.HTMLDialogElement.prototype

if (typeof dialog.showModal !== 'function') {
  dialog.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true
  }
}

if (typeof dialog.close !== 'function') {
  dialog.close = function close(this: HTMLDialogElement, returnValue?: string) {
    this.open = false
    if (returnValue !== undefined) this.returnValue = returnValue
    this.dispatchEvent(new Event('close'))
  }
}
