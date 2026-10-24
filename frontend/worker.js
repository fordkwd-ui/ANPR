export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Server-side proxy for backend API to avoid browser Mixed Content errors
    if (url.pathname.startsWith('/api/')) {
      const backendUrl = new URL(`http://139.59.19.128${url.pathname}${url.search}`);
      const newHeaders = new Headers(request.headers);
      newHeaders.set('Host', '139.59.19.128');

      const proxyRequest = new Request(backendUrl.toString(), {
        method: request.method,
        headers: newHeaders,
        body: request.body,
        redirect: 'follow',
      });

      return fetch(proxyRequest);
    }

    // Serve frontend SPA static assets
    return env.ASSETS.fetch(request);
  },
};
