import { isPublicHttpsRedirect } from '../../../src/helpers/redirect-uri';

describe('isPublicHttpsRedirect', () => {
  it.each([
    'https://mcp.example.com/oauth/company/callback',
    'https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl',
  ])('accepts public HTTPS redirect %s', (uri) => {
    expect(isPublicHttpsRedirect(uri)).toBe(true);
  });

  it.each([
    'http://localhost:8000/callback',
    'https://localhost:8000/callback',
    'http://127.0.0.1:8000/callback',
    'https://[::1]:8000/callback',
    'http://mcp.example.com/callback',
    'not a url',
    '',
  ])('rejects %s', (uri) => {
    expect(isPublicHttpsRedirect(uri)).toBe(false);
  });
});
