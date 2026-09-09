// A production Intuit OAuth flow needs a redirect URI that Intuit will accept:
// public HTTPS, never a loopback address. The interactive flow is only worth
// starting on a production server when this holds (a reverse proxy then routes
// the public callback back to the local listener; see deploy/README.md).
export function isPublicHttpsRedirect(uri: string): boolean {
  try {
    const parsed = new URL(uri);
    const host = parsed.hostname.toLowerCase();
    const loopback = host === 'localhost' || host === '[::1]' || host === '::1' || host.startsWith('127.');
    return parsed.protocol === 'https:' && !loopback;
  } catch {
    return false;
  }
}
