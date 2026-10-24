/**
 * Cloudflare Worker & Cloudflare Pages Advanced Mode Proxy
 * Proxies /api/* and /ws/* (WebSockets) to the DigitalOcean origin server (139.59.19.128).
 * Eliminates browser Mixed Content restrictions and provides secure wss:// WebSocket streaming.
 */

const BACKEND_HOST = '139.59.19.128';
const BACKEND_ORIGIN = `http://${BACKEND_HOST}`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const upgradeHeader = request.headers.get('Upgrade');

    // 1. WebSocket Proxy for real-time live ANPR scan events
    if ((upgradeHeader && upgradeHeader.toLowerCase() === 'websocket') || url.pathname.startsWith('/ws')) {
      const backendWsUrl = new URL(`${BACKEND_ORIGIN}${url.pathname}${url.search}`);
      const headers = new Headers(request.headers);
      headers.set('Host', BACKEND_HOST);

      const originRequest = new Request(backendWsUrl.toString(), {
        method: request.method,
        headers: headers,
      });

      try {
        const originResponse = await fetch(originRequest);
        if (originResponse.webSocket) {
          return new Response(null, {
            status: 101,
            webSocket: originResponse.webSocket,
          });
        }
        return originResponse;
      } catch (err) {
        return new Response(`WebSocket upstream proxy error: ${err.message}`, { status: 502 });
      }
    }

    // 2. REST API & Media Proxy
    if (url.pathname.startsWith('/api/')) {
      // Direct response for CORS preflight OPTIONS requests
      if (request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Max-Age': '86400',
          },
        });
      }

      const backendApiUrl = new URL(`${BACKEND_ORIGIN}${url.pathname}${url.search}`);
      const headers = new Headers(request.headers);
      headers.set('Host', BACKEND_HOST);

      const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
      const proxyRequest = new Request(backendApiUrl.toString(), {
        method: request.method,
        headers: headers,
        body: hasBody ? request.body : undefined,
        redirect: 'follow',
      });

      try {
        const response = await fetch(proxyRequest);
        const respHeaders = new Headers(response.headers);
        respHeaders.set('Access-Control-Allow-Origin', '*');
        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers: respHeaders,
        });
      } catch (err) {
        return new Response(
          JSON.stringify({ detail: `API upstream proxy error: ${err.message}` }),
          {
            status: 502,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
            },
          }
        );
      }
    }

    // 3. Serve Frontend SPA Static Assets
    if (env && env.ASSETS) {
      const assetRes = await env.ASSETS.fetch(request);
      if (assetRes.status === 404 && request.method === 'GET') {
        // SPA Fallback: serve / for client-side routing
        return env.ASSETS.fetch(new URL('/', request.url));
      }
      return assetRes;
    }

    return new Response('Asset not found', { status: 404 });
  },
};
