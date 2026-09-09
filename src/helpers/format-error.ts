import { getIntuitTid } from './intuit-tid.js';

/**
 * Formats an error into a standardized error message. When the error carries
 * an Intuit transaction id (see intuit-tid.ts) it is appended so the caller
 * can quote it to Intuit support.
 * @param error Any error object to format
 * @returns A formatted error message as a string
 */
export function formatError(error: unknown): string {
  const tid = getIntuitTid(error);
  const suffix = tid ? ` (intuit_tid: ${tid})` : '';
  if (error instanceof Error) {
    return `Error: ${error.message}${suffix}`;
  } else if (typeof error === 'string') {
    return `Error: ${error}`;
  } else {
    return `Unknown error: ${JSON.stringify(error)}${suffix}`;
  }
}
