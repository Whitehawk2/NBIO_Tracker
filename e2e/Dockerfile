# Derived from the pinned Playwright image (browsers bundled, matched to
# @playwright/test@1.60.0). Dependencies are installed at BUILD time and the
# suite is COPYed in, so nothing is ever bind-mounted from — or written to — a
# developer host (resolves the node_modules-ownership concern from the #94
# review). npm ci is a cached layer, so editing a spec rebuilds in seconds.
FROM mcr.microsoft.com/playwright:v1.60.0-noble

WORKDIR /work
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY playwright.config.js global-setup.js ./
COPY specs ./specs

CMD ["npx", "playwright", "test"]
