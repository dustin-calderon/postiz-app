import { Agent, buildConnector } from 'undici';
import axios, { AxiosInstance } from 'axios';
import dns from 'node:dns';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import { isBlockedIp } from './webhook.url.validator';

// Pins DNS resolution: every resolved IP is checked with `isBlockedIp` and
// the caller connects to that same set. Closes the TOCTOU window
// `isSafePublicHttpsUrl` alone leaves open (see GHSA-f7jj-p389-4w45).
function ssrfSafeLookup(
  hostname: string,
  options: any,
  callback: (
    err: NodeJS.ErrnoException | null,
    address: any,
    family?: number
  ) => void
) {
  if (net.isIP(hostname)) {
    const family = net.isIP(hostname);
    if (isBlockedIp(hostname)) {
      return callback(new Error('Blocked IP'), '', 0);
    }
    return options && (options as any).all
      ? callback(null, [{ address: hostname, family }] as any, family)
      : callback(null, hostname, family);
  }

  dns.lookup(hostname, options, (err, address: any, family: any) => {
    if (err) return callback(err, '', 0);
    if (Array.isArray(address)) {
      for (const entry of address) {
        if (isBlockedIp(entry.address)) {
          return callback(new Error('Blocked IP'), '', 0);
        }
      }
      return callback(null, address as any, 0);
    }
    if (isBlockedIp(address)) {
      return callback(new Error('Blocked IP'), '', 0);
    }
    callback(null, address, family);
  });
}

// Node only calls `lookup` for names: a URL that already carries an IP
// (http://127.0.0.1, http://[::1], http://169.254.169.254) connects without
// it, so the lookup alone lets every literal through. Both connectors below
// check the literal before dialing.
function isBlockedLiteral(host?: string | null) {
  const bare = (host || '').replace(/^\[|\]$/g, '');
  return net.isIP(bare) !== 0 && isBlockedIp(bare);
}

const ssrfSafeConnect = buildConnector({ lookup: ssrfSafeLookup } as any);

export const ssrfSafeDispatcher = new Agent({
  connect(options, callback) {
    if (isBlockedLiteral(options.hostname)) {
      return callback(new Error('Blocked IP'), null);
    }
    return ssrfSafeConnect(options, callback);
  },
});

// Same literal-IP check for axios: node's http(s) agents hand every new socket
// to `createConnection`, redirects (follow-redirects) included.
function withSsrfSafeLiterals<T extends http.Agent>(agent: T): T {
  const createConnection = (agent as any).createConnection.bind(agent);
  (agent as any).createConnection = (options: any, callback: any) => {
    if (isBlockedLiteral(options?.host)) {
      callback(new Error('Blocked IP'));
      return undefined;
    }
    return createConnection(options, callback);
  };
  return agent;
}

// axios can't use an undici dispatcher, but Node's http(s) agents accept the
// same `lookup` hook, so axios requests (providers that need form-data /
// stream uploads) get the identical pinned-DNS guard as `this.fetch`.
const ssrfSafeAxios = axios.create({
  httpAgent: withSsrfSafeLiterals(
    new http.Agent({ lookup: ssrfSafeLookup } as http.AgentOptions)
  ),
  httpsAgent: withSsrfSafeLiterals(
    new https.Agent({
      lookup: ssrfSafeLookup,
    } as https.AgentOptions)
  ),
});

// Self-hosters legitimately connect Postiz to WordPress/Mastodon/Lemmy/Listmonk
// instances that live on a private network (e.g. the same Docker network or VPC).
// Setting DISABLE_SSRF_PROTECTION=true opts those deployments out of the IP
// guard. It stays ON by default so the hosted product is protected.
export function getSsrfSafeDispatcher(): Agent | undefined {
  return process.env.DISABLE_SSRF_PROTECTION === 'true'
    ? undefined
    : ssrfSafeDispatcher;
}

export function getSsrfSafeAxios(): AxiosInstance {
  return process.env.DISABLE_SSRF_PROTECTION === 'true' ? axios : ssrfSafeAxios;
}
