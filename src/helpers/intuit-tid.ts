/**
 * Intuit tags every QuickBooks API response with an `intuit_tid` header.
 * Intuit support asks for it when troubleshooting, so we capture it on
 * failures and surface it in the error returned to the caller.
 *
 * node-quickbooks invokes every callback as `(err, data, res)`, where `res` is
 * the axios response. Handlers only consume `(err, data)`, so this wrapper
 * intercepts the callback, reads the header from `res`, and pins it onto the
 * error object before the handler sees it.
 */

export const INTUIT_TID_HEADER = 'intuit_tid';

type Headers = Record<string, unknown> | undefined;

function headerValue(res: unknown): string | undefined {
  if (!res || typeof res !== 'object') return undefined;
  const headers = (res as { headers?: Headers }).headers;
  if (!headers || typeof headers !== 'object') return undefined;
  const raw = headers[INTUIT_TID_HEADER] ?? headers[INTUIT_TID_HEADER.toUpperCase()];
  if (typeof raw === 'string' && raw.length > 0) return raw;
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0];
  return undefined;
}

/** Reads a previously attached intuit_tid from an error, if any. */
export function getIntuitTid(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const tid = (error as { intuit_tid?: unknown }).intuit_tid;
  return typeof tid === 'string' && tid.length > 0 ? tid : undefined;
}

/**
 * Attaches the intuit_tid from `res` to `err` when both are present. Returns
 * the (possibly same) error so callers can chain it.
 */
export function attachIntuitTid<E>(err: E, res: unknown): E {
  if (!err || typeof err !== 'object') return err;
  const tid = headerValue(res);
  if (!tid || getIntuitTid(err)) return err;
  try {
    Object.defineProperty(err, 'intuit_tid', {
      value: tid,
      enumerable: true,
      configurable: true,
      writable: true,
    });
  } catch {
    // Frozen error objects: nothing to do, the caller still gets the error.
  }
  return err;
}

/**
 * Wraps a node-quickbooks instance so every callback-style method attaches the
 * intuit_tid to errors. Non-function properties and methods called without a
 * trailing callback pass through untouched.
 */
export function withIntuitTid<T extends object>(instance: T): T {
  return new Proxy(instance, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      if (typeof value !== 'function') return value;
      return function (this: unknown, ...args: unknown[]) {
        const last = args.length - 1;
        if (last >= 0 && typeof args[last] === 'function') {
          const callback = args[last] as (...cbArgs: unknown[]) => unknown;
          args[last] = (err: unknown, data: unknown, res: unknown, ...rest: unknown[]) =>
            callback(attachIntuitTid(err, res), data, res, ...rest);
        }
        return Reflect.apply(value, target, args);
      };
    },
  });
}
