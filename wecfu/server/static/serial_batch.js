/*
MIT License

Copyright (c) 2026 WeCFU QA collaborators

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
/*
 * serial_batch.js — sequential queue helper (pure UI orchestration).
 *
 * MIT licensed (see LICENSE).  Original implementation; no third-party code.
 *
 * UMD: CommonJS (`module.exports`) and browser global `WECFU_SERIAL_BATCH`.
 * The only export is `run(items, hooks)`.
 *
 * No imports, DOM, network, file access, timers, eval, global mutable state or
 * model logic.  The helper never mutates its arguments.
 *
 * Contract
 * --------
 * `items`  array of arbitrary values; a shallow snapshot is taken at entry, so
 *          later mutation of the caller's array cannot change the run.
 * `hooks`  object with a callable `runItem(item, index)`; optional
 *          `shouldStop()` (sync) and `onProgress({index, total, item})`
 *          (sync or async, always awaited *before* `runItem`).
 *
 * Items are processed strictly one at a time: at most one `runItem` is ever in
 * flight.  `shouldStop()` is consulted before each item and again after an
 * awaited `onProgress`.  Once cancellation is observed no further item is
 * started and nothing is retried; an item already in flight is allowed to
 * settle and its result is kept.
 *
 * `runItem` may return any value; it is appended to `results` unchanged.  A
 * returned value whose `stop` property is exactly `true` stops the queue after
 * that item.  A throw or rejection from `runItem` or `onProgress` rejects the
 * whole call — no partial or invented results are returned.
 *
 * Resolves to `{ results, stopped, processed, total }` where `processed` equals
 * `results.length` and `total` is the snapshot length.  An empty `items` array
 * resolves to empty results with `stopped: false` and does not touch the hooks.
 */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module !== null && typeof module.exports === 'object') {
    module.exports = factory();
  } else {
    root.WECFU_SERIAL_BATCH = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Run `items` one at a time through `hooks.runItem`.
   *
   * @param {Array<*>} items
   * @param {{runItem: Function, shouldStop?: Function, onProgress?: Function}} hooks
   * @returns {Promise<{results: Array<*>, stopped: boolean, processed: number, total: number}>}
   */
  async function run(items, hooks) {
    if (!Array.isArray(items)) {
      throw new TypeError('items must be an array');
    }
    if (hooks === null || typeof hooks !== 'object') {
      throw new TypeError('hooks must be an object');
    }
    if (typeof hooks.runItem !== 'function') {
      throw new TypeError('hooks.runItem must be a function');
    }
    if (hooks.shouldStop !== undefined && typeof hooks.shouldStop !== 'function') {
      throw new TypeError('hooks.shouldStop must be a function when supplied');
    }
    if (hooks.onProgress !== undefined && typeof hooks.onProgress !== 'function') {
      throw new TypeError('hooks.onProgress must be a function when supplied');
    }

    // Shallow snapshot taken before the first await: later mutation of the
    // caller's array cannot affect this run.
    const snapshot = items.slice();
    const total = snapshot.length;
    const results = [];
    let stopped = false;

    if (total === 0) {
      return { results: results, stopped: false, processed: 0, total: 0 };
    }

    // Capture optional hooks once, bound to the hooks object. runItem is read
    // from the supplied hooks object on each iteration.
    const shouldStop = typeof hooks.shouldStop === 'function'
      ? hooks.shouldStop.bind(hooks)
      : null;
    const onProgress = typeof hooks.onProgress === 'function'
      ? hooks.onProgress.bind(hooks)
      : null;

    for (let index = 0; index < total; index += 1) {
      if (shouldStop !== null && shouldStop()) {
        stopped = true;
        break;
      }

      const item = snapshot[index];

      if (onProgress !== null) {
        // Awaited before runItem so UI updates always precede the work.
        await onProgress({ index: index, total: total, item: item });
        // Cancellation raised while the progress callback was awaited must
        // prevent this item from ever starting.
        if (shouldStop !== null && shouldStop()) {
          stopped = true;
          break;
        }
      }

      const record = await hooks.runItem(item, index);
      results.push(record);

      // `record?.stop === true` written without optional chaining so the file
      // also parses in browsers that predate ES2020.
      if (record !== null && record !== undefined && record.stop === true) {
        stopped = true;
        break;
      }
    }

    return {
      results: results,
      stopped: stopped,
      processed: results.length,
      total: total
    };
  }

  return { run: run };
}));
