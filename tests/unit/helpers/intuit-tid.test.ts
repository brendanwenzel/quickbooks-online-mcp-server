import { attachIntuitTid, getIntuitTid, withIntuitTid } from '../../../src/helpers/intuit-tid';
import { formatError } from '../../../src/helpers/format-error';

const res = (tid?: string) => ({ headers: tid === undefined ? {} : { intuit_tid: tid } });

describe('attachIntuitTid / getIntuitTid', () => {
  it('pins the header onto a Fault body object', () => {
    const fault = { Fault: { Error: [{ Message: 'Invalid Reference Id' }] } };
    expect(getIntuitTid(attachIntuitTid(fault, res('abc-123')))).toBe('abc-123');
  });

  it('pins the header onto an Error instance', () => {
    const err = attachIntuitTid(new Error('boom'), res('tid-1'));
    expect(getIntuitTid(err)).toBe('tid-1');
    expect(err.message).toBe('boom');
  });

  it('accepts an array-valued header', () => {
    expect(getIntuitTid(attachIntuitTid({ x: 1 }, { headers: { intuit_tid: ['first', 'second'] } }))).toBe('first');
  });

  it('leaves errors alone when there is no header or no response', () => {
    expect(getIntuitTid(attachIntuitTid({ x: 1 }, res()))).toBeUndefined();
    expect(getIntuitTid(attachIntuitTid({ x: 1 }, undefined))).toBeUndefined();
    expect(getIntuitTid(attachIntuitTid({ x: 1 }, 'not a response'))).toBeUndefined();
  });

  it('does not overwrite an already attached id', () => {
    const err = attachIntuitTid({ intuit_tid: 'keep' }, res('other'));
    expect(getIntuitTid(err)).toBe('keep');
  });

  it('passes through non-object errors', () => {
    expect(attachIntuitTid('string error', res('t'))).toBe('string error');
    expect(attachIntuitTid(null, res('t'))).toBeNull();
    expect(getIntuitTid('string error')).toBeUndefined();
  });

  it('survives a frozen error object', () => {
    const frozen = Object.freeze({ code: 1 });
    expect(() => attachIntuitTid(frozen, res('t'))).not.toThrow();
  });
});

describe('withIntuitTid proxy', () => {
  class FakeQbo {
    label = 'plain-property';
    findBills(_criteria: unknown, cb: (err: unknown, data: unknown, res?: unknown) => void) {
      cb({ Fault: { Error: [{ Message: 'nope' }] } }, null, res('proxied-tid'));
    }
    getBill(_id: string, cb: (err: unknown, data: unknown, res?: unknown) => void) {
      cb(null, { Id: '1' }, res('ok-tid'));
    }
    noCallback(a: number, b: number) {
      return a + b;
    }
    usesThis(cb: (err: unknown, data: unknown) => void) {
      cb(null, this.label);
    }
  }

  it('attaches the id to errors returned through callbacks', (done) => {
    const qbo = withIntuitTid(new FakeQbo());
    qbo.findBills({}, (err, data) => {
      expect(getIntuitTid(err)).toBe('proxied-tid');
      expect(data).toBeNull();
      done();
    });
  });

  it('leaves successful callbacks and their data untouched', (done) => {
    const qbo = withIntuitTid(new FakeQbo());
    qbo.getBill('1', (err, data, r) => {
      expect(err).toBeNull();
      expect(data).toEqual({ Id: '1' });
      expect(r).toEqual(res('ok-tid'));
      done();
    });
  });

  it('passes through methods without a callback and plain properties', () => {
    const qbo = withIntuitTid(new FakeQbo());
    expect(qbo.noCallback(2, 3)).toBe(5);
    expect(qbo.label).toBe('plain-property');
  });

  it('preserves `this` for the wrapped method', (done) => {
    const qbo = withIntuitTid(new FakeQbo());
    qbo.usesThis((_err, data) => {
      expect(data).toBe('plain-property');
      done();
    });
  });
});

describe('formatError with intuit_tid', () => {
  it('appends the id for Error instances', () => {
    expect(formatError(attachIntuitTid(new Error('boom'), res('t-1')))).toBe('Error: boom (intuit_tid: t-1)');
  });

  it('appends the id for Fault bodies', () => {
    const out = formatError(attachIntuitTid({ Fault: { Error: [{ Message: 'bad' }] } }, res('t-2')));
    expect(out).toMatch(/^Unknown error: \{.*"intuit_tid":"t-2".*\} \(intuit_tid: t-2\)$/);
  });

  it('is unchanged when no id is present', () => {
    expect(formatError(new Error('boom'))).toBe('Error: boom');
  });
});
